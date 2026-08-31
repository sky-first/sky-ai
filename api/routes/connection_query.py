# api/routes/connection_query.py
"""
Rotas de Query e Sugestões

Arquitetura dos Agentes:
- Sherlock (bootstrap): Gera sugestões inteligentes quando usuário abre o chat
  - Investiga dados disponíveis
  - Coleta estatísticas reais (row_count, totals, date ranges)
  - Gera greeting + cards de sugestões personalizadas
  - Varia sugestões a cada N minutos (configurável, default: 5 minutos)

- Sistema de Query (graph): Executa perguntas usando orchestrator → specialist → formatter
  - Orchestrator: Escolhe quais tabelas usar
  - Specialist: Gera SQL e executa
  - Formatter: Formata resposta em linguagem natural

- Davinci: Gera planos de dashboards (ver davinci_dashboard_agent.py)
"""

from __future__ import annotations

from core.llm.lingua_da_resposta import (
    NOME_DA_LINGUA,
    lingua_da_resposta,
    nome_da_lingua,
)

from typing import Optional, List, Dict, Tuple, Any
from uuid import UUID
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Query
from core.auth.models import User, UserContext  # Import User specifically
from db.models import Space, Crew, UserPermission, DataConnection, ChatHistory
from db.session import engine
from sqlalchemy import text, select, desc
from sqlalchemy.orm import Session
from sqlalchemy.exc import NoResultFound
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
import os
import json
import asyncio
import time
import hashlib
from collections import defaultdict
from typing import AsyncGenerator
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

import logging

logger = logging.getLogger(__name__)

from api.schemas import (
    QueryRequest,
    QueryResponse,
    QueryResultMeta,
    ChatBootstrapRequest,
    ChatBootstrapResponse,
    ChatBootstrapSuggestion,
    DashboardPlanRequest,
    DashboardPlanResponse,
    DashboardPlanWidget,
    ValidateSQLRequest,
    ValidateSQLResponse,
)
from core.agents.generic_sql_agent import AgentConfig, TableSchema, run_agent_once
from core.agents.davinci_dashboard_agent import generate_dashboard_plan
from core.agents.factory import _normalize_logical_name
from core.llm.factory import (
    create_llm_orchestrator,
    create_llm_specialist,
    create_llm_formatter,
    create_embedding_provider,
)
from core.rag.vector_store import search_embeddings_async
from core.rag.context_retrieval import build_retrieval_context_for_question
from core.data_sources.factory import DataSourceFactory
from core.logging_utils import log_event
from core.auth.service import get_user_crew_ids_in_space, resolve_crew_ids_for_context
from core.i18n.i18n import (
    _normalize_lang_code,
    detect_language,
    get_message,
    language_decision,
    unsupported_language_message,
)
from core.security.rate_limiter_redis import _rate_limiter
from core.security.audit import log_query_audit
from core.security.progressive_escalation import detect_progressive_escalation
from core.sql.validator_advanced import AdvancedSQLValidator
from db.session import get_db
from db.base import SyncSessionLocal
from core.tenant_db import tenant_connection_manager
from core.agents.generic_sql_agent import UserContext  # Import UserContext
from datetime import datetime, timedelta
from core.context.analysis_session_store import AnalysisSessionStore  # NEW IMPORT

router = APIRouter(prefix="/connections", tags=["connection_query"])

# ============================================================================
# Cache para bootstrap suggestions (em memória, pode migrar para Redis depois)
# ============================================================================
_bootstrap_cache: Dict[str, Tuple[ChatBootstrapResponse, datetime]] = {}
CACHE_TTL_MINUTES = 10  # Sugestões válidas por 10 minutos
MAX_CACHE_SIZE = 100  # Limitar tamanho do cache para evitar uso excessivo de memória

# ✅ Cache reativado para respostas rápidas (varia a cada 30 segundos)
DISABLE_BOOTSTRAP_CACHE = False  # Cache habilitado para melhor performance
# ── As sugestões do Sherlock ─────────────────────────────────────────
#
# **Estiveram desligadas seis meses, cravadas no código.**
#
# A linha era `DISABLE_BOOTSTRAP_EXECUTION = True  # PAUSADO A PEDIDO DO
# CLIENTE (Step 547)`, escrita a 05/02/2026 dentro de um PR sobre a lógica
# dos dashboards. Ninguém voltou lá. O `/chat/bootstrap` respondia
# «Bootstrap is paused (Maintenance Mode)» com zero sugestões, e a web caía
# nas duas genéricas de reserva — «Que dados tenho?» e «Dá-me exemplos».
#
# O Lucas pediu exactamente isto de volta, a 31/08:
#
# > *"na conexao que fazemos, já gerarmos ali algumas perguntas e respostas
# > ... ou até mesmo na tela de descobertas apresentarmos um: olha nao
# > encontramos isso, mas essas outras opcoes parecem também ser
# > interessantes, quer saber mais sobre 1 2 3 (opcoes como botões) assim
# > nao matamos a iteração"*
#
# Passa a ser uma variável de ambiente, ligada por omissão: uma pausa
# operacional (custo, latência, um modelo em baixo) resolve-se sem tocar no
# código nem esperar por uma imagem nova — que foi o que fez esta ficar seis
# meses ligada ao contrário.
def _erro_para_quem_pergunta(lang: str, detalhe=None, traceback_texto=None) -> str:
    """A mensagem que a pessoa le. O detalhe tecnico fica nos registos.

    **Estava a ser colado na resposta.** Quatro sitios faziam
    ``f"{TECHNICAL_ERROR} | DEBUG: {erro}"``, e dois juntavam-lhe **o
    traceback inteiro**. O Lucas apanhou o resultado no telemovel:

        Algo correu mal do nosso lado ao responder a esta pergunta — nao e
        problema dos seus dados nem do seu acesso. O erro ficou registado.
        Tente de novo e avise um administrador se continuar.
        | DEBUG:  (status code: 404)

    A frase diz «o erro ficou registado» e logo a seguir despeja-o na mesma.
    Um codigo de estado nao diz a ninguem o que fazer, e um traceback num
    balao de chat e uma fuga: mostra caminhos de ficheiros e nomes internos
    a quem nao tem nada com isso.

    O registo fica com tudo, e com muito mais contexto do que cabe ali.
    """
    if detalhe:
        logger.error("Erro tecnico devolvido ao utilizador: %s", detalhe)
    if traceback_texto:
        logger.error("Traceback do erro acima:\n%s", traceback_texto)
    return get_message("TECHNICAL_ERROR", lang)


DISABLE_BOOTSTRAP_EXECUTION = (
    os.getenv("DISABLE_BOOTSTRAP_EXECUTION", "false").strip().lower()
    in {"1", "true", "yes", "on"}
)

# ============================================================================
# Cache para dashboard plans (Davinci) (em memória, pode migrar para Redis depois)
# ============================================================================
_dashboard_plan_cache: Dict[str, Tuple[DashboardPlanResponse, datetime]] = {}
DASHBOARD_PLAN_CACHE_TTL_MINUTES = (
    60  # Planos válidos por 60 minutos (mais longo que bootstrap)
)
DASHBOARD_PLAN_MAX_CACHE_SIZE = 50  # Menor que bootstrap (planos são maiores)

# ============================================================================
# Cache para estatísticas de tabelas (separado do cache de bootstrap)
# ============================================================================
_table_stats_cache: Dict[str, Tuple[Dict[str, Any], datetime]] = {}
TABLE_STATS_CACHE_TTL_MINUTES = 5  # Stats mudam mais rápido que schema
TABLE_STATS_MAX_CACHE_SIZE = 50

# ✅ NOVO: Frequência de variação das sugestões (configurável via env)
from config.settings import settings

BOOTSTRAP_VARIATION_WINDOW_SECONDS = settings.bootstrap_variation_window_seconds


def _get_cache_key(
    connection_id: str,
    space_id: str,
    crew_ids: Optional[List[str]],
    is_personal: bool,
    language: str,
    time_window: Optional[int] = None,
) -> str:
    """
    Gera chave única para o cache baseada nos parâmetros relevantes.

    Args:
        connection_id: ID da conexão
        space_id: ID do space
        crew_ids: Lista de crew_ids (será ordenada para consistência)
        is_personal: Se está em modo personal
        language: Idioma das sugestões
        time_window: Janela de tempo em segundos (opcional, para variação)

    Returns:
        String única que identifica esta combinação de parâmetros
    """
    # Ordenar crew_ids para garantir consistência (mesma chave para mesma combinação)
    crew_ids_str = ",".join(sorted(crew_ids or []))
    # ✅ INCLUIR time_window na chave para variação periódica
    time_part = f":{time_window}" if time_window is not None else ""
    return f"bootstrap:{connection_id}:{space_id}:{crew_ids_str}:{is_personal}:{language}{time_part}"


def _get_cached_bootstrap(cache_key: str) -> Optional[ChatBootstrapResponse]:
    """
    Retorna sugestões do cache se ainda válidas.

    Args:
        cache_key: Chave do cache

    Returns:
        ChatBootstrapResponse se encontrado e válido, None caso contrário
    """
    # ✅ Para testes: desabilitar cache
    if DISABLE_BOOTSTRAP_CACHE:
        return None

    if cache_key not in _bootstrap_cache:
        return None

    cached_response, cached_time = _bootstrap_cache[cache_key]
    age = datetime.now() - cached_time

    if age > timedelta(minutes=CACHE_TTL_MINUTES):
        # Cache expirado, remover
        del _bootstrap_cache[cache_key]
        log_event(
            "bootstrap_cache_expired",
            {
                "cache_key": cache_key,
                "age_minutes": age.total_seconds() / 60,
            },
        )
        return None

    return cached_response


def _set_cached_bootstrap(cache_key: str, response: ChatBootstrapResponse):
    """
    Armazena sugestões no cache.

    Args:
        cache_key: Chave do cache
        response: Resposta a ser armazenada
    """
    _bootstrap_cache[cache_key] = (response, datetime.now())

    # Limpar cache antigo se exceder tamanho máximo
    if len(_bootstrap_cache) > MAX_CACHE_SIZE:
        # Remover entrada mais antiga
        oldest_key = min(
            _bootstrap_cache.keys(),
            key=lambda k: _bootstrap_cache[k][1],
        )
        del _bootstrap_cache[oldest_key]
        log_event(
            "bootstrap_cache_evicted",
            {
                "cache_key": oldest_key,
                "cache_size": len(_bootstrap_cache),
            },
        )


def _get_table_stats_cache_key(
    connection_id: str, space_id: str, crew_ids: Optional[List[str]]
) -> str:
    """Gera chave única para cache de estatísticas."""
    crew_ids_str = ",".join(sorted(crew_ids or []))
    return f"table_stats:{connection_id}:{space_id}:{crew_ids_str}"


def _get_cached_table_stats(cache_key: str) -> Optional[Dict[str, Any]]:
    """Retorna estatísticas do cache se ainda válidas."""
    if cache_key not in _table_stats_cache:
        return None

    cached_stats, cached_time = _table_stats_cache[cache_key]
    age = datetime.now() - cached_time

    if age > timedelta(minutes=TABLE_STATS_CACHE_TTL_MINUTES):
        del _table_stats_cache[cache_key]
        return None

    return cached_stats


def _set_cached_table_stats(cache_key: str, stats: Dict[str, Any]):
    """Armazena estatísticas no cache."""
    _table_stats_cache[cache_key] = (stats, datetime.now())

    # Limpar cache antigo se exceder tamanho máximo
    if len(_table_stats_cache) > TABLE_STATS_MAX_CACHE_SIZE:
        oldest_key = min(
            _table_stats_cache.keys(),
            key=lambda k: _table_stats_cache[k][1],
        )
        del _table_stats_cache[oldest_key]


def _get_dashboard_plan_cache_key(
    connection_id: str,
    space_id: str,
    crew_ids: Optional[List[str]],
    is_personal: bool,
    goal: str,
    max_widgets: int,
    language: str,
    original_question: Optional[str] = None,
    initial_ai_response: Optional[str] = None,
    context_spaces: Optional[List[str]] = None,
    context_crews: Optional[List[str]] = None,
    context_tables: Optional[List[str]] = None,
    mode: str = "mix",
) -> str:
    """
    Gera chave única para o cache de planos de dashboard.

    Args:
        connection_id: ID da conexão
        space_id: ID do space
        crew_ids: Lista de crew_ids (será ordenada para consistência)
        is_personal: Se está em modo personal
        goal: Objetivo do dashboard (ex: "Performance overview", "Analytical dashboard")
        max_widgets: Número máximo de widgets
        language: Idioma
        original_question: Pergunta original do usuário (opcional)
        initial_ai_response: Resposta anterior da IA (opcional)
        context_spaces: Spaces disponíveis (opcional)
        context_crews: Crews disponíveis (opcional)
        context_tables: Tabelas acessíveis (opcional)

    Returns:
        String única que identifica esta combinação de parâmetros
    """
    # Ordenar crew_ids para garantir consistência
    crew_ids_str = ",".join(sorted(crew_ids or []))
    # Normalizar goal (lowercase, remover espaços extras)
    goal_normalized = " ".join(goal.strip().lower().split())
    # Normalizar original_question se existir
    original_q_normalized = ""
    if original_question:
        original_q_normalized = " ".join(original_question.strip().lower().split())

    # Normalizar contextos
    initial_resp_norm = str(
        len(initial_ai_response or "")
    )  # Usar comprimento para evitar chave gigante, ou hash
    if initial_ai_response:
        # Usar os primeiros 50 chars + hash para a chave não ficar gigante mas ser única
        initial_resp_hash = hashlib.md5(initial_ai_response.encode()).hexdigest()[:8]
        initial_resp_norm = initial_resp_hash

    spaces_str = ",".join(sorted(context_spaces or []))
    crews_str = ",".join(sorted(context_crews or []))
    tables_str = str(
        len(context_tables or [])
    )  # Apenas contagem para cache, pois tabelas mudam pouco

    # ✅ NOVO: Adicionar versão para invalidar cache antigo após melhorias
    # Incrementar versão quando houver mudanças significativas na lógica de geração
    # v2: validação menos restritiva + fallback melhorado
    # v3: cache key fix + table query improvements
    CACHE_VERSION = "v4_no_cache_debug"

    # ✅ FIX: Usar hash completo da resposta inicial para diferenciar contextos
    # Problema: dashboards idênticos para perguntas diferentes porque initial_ai_response
    # não estava sendo usado corretamente na chave de cache
    if initial_ai_response:
        # Usar hash completo (não apenas primeiros 8 chars) para garantir unicidade
        initial_resp_hash = hashlib.md5(initial_ai_response.encode()).hexdigest()
        initial_resp_norm = initial_resp_hash
    else:
        initial_resp_norm = "no_context"

    # Ensure mode is normalized
    mode_norm = mode.strip().lower()
    return f"dashboard_plan:{CACHE_VERSION}:{mode_norm}:{connection_id}:{space_id}:{crew_ids_str}:{is_personal}:{goal_normalized}:{max_widgets}:{language}:{original_q_normalized}:{initial_resp_norm}:{spaces_str}:{crews_str}:{tables_str}"


def _get_cached_dashboard_plan(cache_key: str) -> Optional[DashboardPlanResponse]:
    """
    Retorna plano de dashboard do cache se ainda válido.

    Args:
        cache_key: Chave do cache

    Returns:
        DashboardPlanResponse se encontrado e válido, None caso contrário
    """
    # ✅ DEBUG FORCE NO CACHE
    return None

    if cache_key not in _dashboard_plan_cache:
        return None

    cached_response, cached_time = _dashboard_plan_cache[cache_key]
    age = datetime.now() - cached_time

    if age > timedelta(minutes=DASHBOARD_PLAN_CACHE_TTL_MINUTES):
        # Cache expirado, remover
        del _dashboard_plan_cache[cache_key]
        log_event(
            "dashboard_plan_cache_expired",
            {
                "cache_key": cache_key,
                "age_minutes": age.total_seconds() / 60,
            },
        )
        return None

    return cached_response


def _set_cached_dashboard_plan(cache_key: str, response: DashboardPlanResponse):
    """
    Armazena plano de dashboard no cache.

    Args:
        cache_key: Chave do cache
        response: Resposta a ser armazenada
    """
    _dashboard_plan_cache[cache_key] = (response, datetime.now())

    # Limpar cache antigo se exceder tamanho máximo
    if len(_dashboard_plan_cache) > DASHBOARD_PLAN_MAX_CACHE_SIZE:
        # Remover entrada mais antiga
        oldest_key = min(
            _dashboard_plan_cache.keys(),
            key=lambda k: _dashboard_plan_cache[k][1],
        )
        del _dashboard_plan_cache[oldest_key]
        log_event(
            "dashboard_plan_cache_evicted",
            {
                "cache_key": oldest_key,
                "cache_size": len(_dashboard_plan_cache),
            },
        )


async def _build_merged_agent_config_for_scan(
    db: AsyncSession,
    dispatch_map: dict,
    space_ids: List[str],
    crew_ids: Optional[List[str]],
    base_config: "AgentConfig",
) -> "AgentConfig":
    """Merge TableSchema objects from all connections in dispatch_map into one AgentConfig.

    Each TableSchema retains data_connection_id so full_context_agent can route
    query_table() calls to the right database via _find_datasource_for_sql.
    Only used for personal mode scan, where the user has access to all their connections.
    Falls back to base_config on any error.
    """
    if not dispatch_map:
        return base_config

    merged_tables: list[TableSchema] = []
    seen_physicals: set = set()

    for conn_id in dispatch_map:
        try:
            cfg = await load_agent_config_from_connection(
                db=db,
                space_id=space_ids[0] if space_ids else "",
                connection_id=conn_id,
                crew_ids=crew_ids or None,
                authorized_tables=None,
                connection_ids=None,
                space_ids=space_ids or None,
            )
            for t in cfg.tables:
                if t.physical_name not in seen_physicals:
                    seen_physicals.add(t.physical_name)
                    t.data_connection_id = conn_id
                    merged_tables.append(t)
        except Exception as _exc:
            logger.warning(
                "_build_merged_agent_config_for_scan: skipping connection %s: %s",
                conn_id,
                _exc,
            )

    if not merged_tables:
        return base_config

    log_event(
        "scan_merged_agent_config_built",
        {
            "space_ids": space_ids,
            "num_connections": len(dispatch_map),
            "num_tables": len(merged_tables),
        },
    )

    return AgentConfig(
        id=base_config.id,
        name=base_config.name,
        tables=merged_tables,
        dialect=base_config.dialect,
        extra=base_config.extra,
    )


def _dispatch_map_from_conn_rows(rows) -> dict:
    """Build {connection_id: DataSource} from ``data_connections`` rows.

    Each row is expected as ``(id, name, connector_id, config)``. A connection
    that fails to build (bad credentials, unreachable host) is skipped and
    logged, so one broken source never breaks routing for the others.
    """
    from core.data_sources.factory import DataSourceFactory
    from core.security.config_decryption import decrypt_config as _decrypt

    class _TempConn:
        def __init__(self, id, name, type, config):
            self.id = id
            self.name = name
            self.type = type
            self.config = config

    dispatch_map: dict = {}
    for row in rows:
        conn_id = str(row[0])
        name = row[1] or conn_id
        conn_type = (row[2] or "postgres").lower()
        raw_config = row[3]
        try:
            if isinstance(raw_config, str):
                raw_config = json.loads(raw_config)
            config = _decrypt(raw_config or {})
            ds = DataSourceFactory.build_from_dataconnection(
                _TempConn(conn_id, name, conn_type, config)
            )
            # Attach label so list_tables can show a human-readable source name
            ds.label = f"{name} ({conn_type})"
            dispatch_map[conn_id] = ds
        except Exception as exc:
            logger.warning(
                "dispatch_map: skipping connection %s (%s): %s", conn_id, name, exc
            )
    return dispatch_map


async def _build_dispatch_map_for_scan(
    db: AsyncSession,
    space_ids: List[str],
) -> dict:
    """Build {connection_id: DataSource} for all connections in the given spaces.

    Used by the full_context_agent in scan mode so it can route query_table()
    calls to the right database when the user has multiple connections.
    Returns an empty dict on failure (agent falls back to single data_source).
    """
    if not space_ids:
        return {}

    try:
        rows = await db.execute(
            text("""
                SELECT dc.id, dc.name, dc.connector_id, dc.config
                FROM data_connections dc
                WHERE dc.id IN (
                    SELECT DISTINCT sc.connection_id
                    FROM space_connections sc
                    WHERE sc.space_id = ANY(CAST(:space_ids AS uuid[]))
                )
                """),
            {"space_ids": space_ids},
        )
    except Exception as exc:
        logger.warning("_build_dispatch_map_for_scan: query failed: %s", exc)
        return {}

    dispatch_map = _dispatch_map_from_conn_rows(rows.fetchall())
    log_event(
        "scan_dispatch_map_built",
        {
            "space_ids": space_ids,
            "num_connections": len(dispatch_map),
            "connection_ids": list(dispatch_map.keys()),
        },
    )
    return dispatch_map


async def _build_dispatch_map_for_connections(
    db: AsyncSession,
    connection_ids: List[str],
) -> dict:
    """Build {connection_id: DataSource} for an explicit set of connections.

    Used by the collaborative query path when a question spans more than one
    connection (``body.connection_ids``), so each table's sub-query runs against
    its own database and the partial results are merged in-memory (DuckDB).
    Returns an empty dict on failure (caller falls back to the single primary
    source).
    """
    if not connection_ids:
        return {}

    try:
        rows = await db.execute(
            text("""
                SELECT dc.id, dc.name, dc.connector_id, dc.config
                FROM data_connections dc
                WHERE dc.id = ANY(CAST(:ids AS uuid[]))
                """),
            {"ids": connection_ids},
        )
    except Exception as exc:
        logger.warning("_build_dispatch_map_for_connections: query failed: %s", exc)
        return {}

    dispatch_map = _dispatch_map_from_conn_rows(rows.fetchall())
    log_event(
        "cross_connection_dispatch_map_built",
        {
            "num_connections": len(dispatch_map),
            "connection_ids": list(dispatch_map.keys()),
        },
    )
    return dispatch_map


async def _load_connection_metadata_tables(
    db: AsyncSession, connection_id: str
) -> list[dict]:
    """
    Backend-compatible catalog loader.

    In this project, the source-of-truth catalog is stored by the backend in `connection_metadata.tables`
    (JSON containing [{name, schema, columns:[{name,type,nullable}, ...]}, ...]).
    """
    # IMPORTANT:
    # Some environments end up with `db` bound to a different DATABASE_URL than `db.base.engine`
    # (due to import timing / dotenv overrides). We use `db.base.engine` here as the single source of truth.
    try:
        result = await db.execute(
            text(
                "SELECT tables FROM connection_metadata WHERE connection_id = CAST(:cid AS uuid) LIMIT 1"
            ),
            {"cid": connection_id},
        )
        tables = result.scalar_one_or_none()
        if isinstance(tables, list):
            return [t for t in tables if isinstance(t, dict)]
        return []
    except Exception as e:
        log_event(
            "ai_connection_metadata_load_error",
            {"connection_id": connection_id, "error": str(e)},
        )
        return []


async def _load_connection_relationships(
    db: AsyncSession,
    connection_id: str,
    allowed_logical_names: Optional[List[str]] = None,
) -> List[dict]:
    """
    Carrega os relacionamentos documentados pelo cliente da tabela connection_metadata.

    Os relacionamentos são armazenados no campo JSON `relationships` dentro do registro
    de ConnectionMetadata pelo backend (separado do campo `tables`).

    Só retorna relacionamentos onde AMBAS as tabelas (from_table e to_table) estejam
    na lista de tabelas autorizadas para o usuário (allowed_logical_names).
    Garante que usuários sem acesso a uma tabela não veem os JOINs relacionados.

    Args:
        db: Sessão async do banco
        connection_id: UUID da conexão
        allowed_logical_names: logical_names das tabelas que o usuário tem acesso.
            Se None ou vazio, retorna todos os relacionamentos sem filtro de permissão.

    Returns:
        Lista de dicts com: from_table, from_column, to_table, to_column,
        join_type, label, confidence.
    """
    try:
        result = await db.execute(
            text(
                "SELECT relationships FROM connection_metadata "
                "WHERE connection_id = CAST(:cid AS uuid) LIMIT 1"
            ),
            {"cid": connection_id},
        )
        raw = result.scalar_one_or_none()

        if not raw or not isinstance(raw, list):
            return []

        relationships = [r for r in raw if isinstance(r, dict)]

        # Filtro de permissão: ambas as tabelas devem ter acesso autorizado
        if allowed_logical_names:
            allowed_set = set(allowed_logical_names)
            relationships = [
                rel
                for rel in relationships
                if rel.get("from_table") in allowed_set
                and rel.get("to_table") in allowed_set
            ]

        log_event(
            "connection_relationships_loaded",
            {
                "connection_id": connection_id,
                "total": len(relationships),
                "filtered_by_permission": allowed_logical_names is not None,
            },
        )
        return relationships

    except Exception as e:
        error_msg = str(e)
        # Se a coluna ainda não existe (migration pendente no backend), é esperado
        if "UndefinedColumnError" in error_msg or "relationships" in error_msg:
            log_event(
                "connection_relationships_column_missing",
                {
                    "connection_id": connection_id,
                    "hint": "Run backend migration to add 'relationships' column to connection_metadata",
                },
            )
        else:
            log_event(
                "connection_relationships_load_error",
                {"connection_id": connection_id, "error": error_msg[:300]},
            )
        # Rollback obrigatório: asyncpg entra em estado de erro após ProgrammingError
        # Se não fizer rollback, todas as queries seguintes nesta sessão falharão
        try:
            await db.rollback()
        except Exception:
            pass
        return []


async def _enrich_tables_with_ai_metadata(
    db: AsyncSession, connection_id: str, tables: list[dict]
) -> list[dict]:
    """
    Enriches the cached backend metadata with AI-specific metadata
    (row_counts, temporal ranges, etc.) from TableMetadata.
    """
    if not tables:
        return []

    try:
        # Fetch all TableMetadata for this connection
        from db.models import TableMetadata

        result = await db.execute(
            select(TableMetadata).where(
                TableMetadata.data_connection_id == connection_id
            )
        )
        ai_meta_rows = result.scalars().all()

        # Group by table name (normalized)
        meta_by_table = defaultdict(list)
        for row in ai_meta_rows:
            meta_by_table[row.table_name].append(row)

        enriched = []
        for t in tables:
            name = t.get("name")
            if not name:
                enriched.append(t)
                continue

            # Find matching metadata row (usually one per column, so we pick the first to get table-level info)
            table_rows = meta_by_table.get(name)
            if not table_rows:
                # Try with schema-qualified name
                full_name = f"{t.get('schema')}.{name}" if t.get("schema") else name
                table_rows = meta_by_table.get(full_name)

            if table_rows:
                # Update table-level info (using first row)
                row0 = table_rows[0]
                t["row_count"] = getattr(
                    row0, "row_count", 0
                )  # if we had a row_count field

                # Merge columns status
                col_meta = {r.column_name: r for r in table_rows}
                for col in t.get("columns", []):
                    cname = col.get("name")
                    if cname in col_meta:
                        rmeta = col_meta[cname]
                        col["extra"] = rmeta.extra or {}
                        # Extract ranges for Davinci's schema summary if needed
                        if rmeta.extra and "min_date" in rmeta.extra:
                            col["min_date"] = rmeta.extra["min_date"]
                        if rmeta.extra and "max_date" in rmeta.extra:
                            col["max_date"] = rmeta.extra["max_date"]

            enriched.append(t)
        return enriched
    except Exception as e:
        log_event("ai_metadata_enrich_error", {"error": str(e)})
        return tables


async def _filter_tables_by_permissions(
    db: AsyncSession,
    connection_id: str,
    space_id: str,
    tables: list[dict],
    crew_ids: Optional[List[str]] = None,
    strict_mode: bool = False,
) -> list[dict]:
    """
    Filtra tabelas baseado em permissões (space_id + crew_ids).

    Regras de permissão (agnósticas, funcionam para qualquer domínio):
    - Se crew_ids for None ou vazio: retorna apenas tabelas públicas (crew_id IS NULL)
    - Se crew_ids fornecido: retorna tabelas onde crew_id IS NULL OU crew_id IN crew_ids

    Args:
        db: Sessão do banco
        connection_id: ID da conexão
        space_id: ID do space
        tables: Lista de tabelas do connection_metadata.tables
        crew_ids: Lista opcional de crew_ids para filtrar
        strict_mode: Se True (modo colaborativo), falhas de permissão retornam lista vazia
                     em vez de todas as tabelas. Previne vazamento de dados em modo crew.

    Returns:
        Lista filtrada de tabelas que o usuário tem permissão
    """
    if not tables:
        return []

    # Se não há crew_ids, retornar todas as tabelas (modo personal ou sem restrições)
    # Na prática, vamos verificar se há permissões específicas em table_metadata
    if crew_ids is None or len(crew_ids) == 0:
        # Sem crew_ids: retornar todas as tabelas (assumindo que são públicas ou o backend já filtrou)
        # Para ser mais seguro, podemos verificar table_metadata, mas por enquanto retornamos todas
        return tables

    # Com crew_ids: verificar permissões em table_metadata
    try:
        # Extrair nomes de tabelas (normalizados)
        table_names = set()
        for t in tables:
            schema = str(t.get("schema") or "").strip()
            name = str(t.get("name") or "").strip()
            if name:
                # Normalizar nome (pode ter schema.table ou apenas table)
                full_name = f"{schema}.{name}" if schema else name
                table_names.add(full_name)
                # Também adicionar apenas o nome (sem schema)
                table_names.add(name)

        if not table_names:
            return tables  # Se não conseguimos extrair nomes, retornar todas

        # Buscar tabelas permitidas em table_metadata
        # Construir query: crew_id IS NULL (público) OU crew_id IN crew_ids
        allowed_table_names = set()
        try:
            query = text("""
                SELECT DISTINCT table_name
                FROM table_metadata
                WHERE data_connection_id = CAST(:conn_id AS uuid)
                AND (
                    space_id = CAST(:space_id AS uuid)
                    OR space_id IS NULL
                )
                -- Sem filtro por equipa: o projeto é a fronteira e a
                -- equipa é uma etiqueta (decisão de 2026-08-27). Esta era
                -- a TERCEIRA cópia da mesma regra — as outras duas estão
                -- no `factory.py` e mais abaixo neste ficheiro.
            """)

            result = await db.execute(
                query,
                {
                    "space_id": space_id,
                    "conn_id": connection_id,
                    "crew_ids": crew_ids,
                },
            )

            allowed_table_names = {row[0] for row in result}
        except Exception as e:
            # Se a tabela não existir ou outro erro de DB, logar e continuar sem filtrar
            log_event("table_metadata_query_error", {"error": str(e)})

            # CRITICAL: Rollback se a transação falhou (ex: UndefinedTableError)
            try:
                await db.rollback()
            except Exception:
                pass

            # SEGURANÇA: Em strict_mode (modo colaborativo), falha de DB => lista vazia.
            # Em modo personal/fallback, retornar todas as tabelas.
            if strict_mode:
                log_event(
                    "table_filter_strict_mode_db_error",
                    {
                        "connection_id": connection_id,
                        "space_id": space_id,
                        "crew_ids": crew_ids,
                        "error": str(e)[:200],
                    },
                )
                return []  # Fail-closed: não vazar dados de outras crews
            return tables

        # Filtrar tabelas baseado em allowed_table_names
        filtered_tables = []
        for t in tables:
            schema = str(t.get("schema") or "").strip()
            name = str(t.get("name") or "").strip()
            if not name:
                continue

            # Verificar se a tabela está permitida
            full_name = f"{schema}.{name}" if schema else name
            if full_name in allowed_table_names or name in allowed_table_names:
                filtered_tables.append(t)

        # Se não encontramos correspondências em table_metadata:
        if not filtered_tables and allowed_table_names:
            # Há allowed_table_names no DB mas nenhuma tabela do metadata coincide.
            # Pode ser problema de normalização de nome (schema.table vs table).
            log_event(
                "bootstrap_table_filter_no_matches",
                {
                    "connection_id": connection_id,
                    "space_id": space_id,
                    "crew_ids": crew_ids,
                    "total_tables": len(tables),
                    "allowed_table_names_count": len(allowed_table_names),
                    "strict_mode": strict_mode,
                },
            )
            # SEGURANÇA: Em strict_mode (modo colaborativo), problema de normalização
            # NÃO deve abrir acesso a todas as tabelas — retornar vazio.
            if strict_mode:
                return []  # Fail-closed
            return tables  # Modo personal: fail-open (sem dados de crew configurados)

        # Se não há nenhum registro em table_metadata (tabela não configurada)
        if not filtered_tables and not allowed_table_names:
            # table_metadata não tem registros para este space/connection
            # Em modo personal: retornar todas (sem restrições configuradas ainda)
            # Em strict_mode: retornar vazio (política de negação por padrão)
            if strict_mode:
                log_event(
                    "table_filter_strict_mode_no_metadata",
                    {
                        "connection_id": connection_id,
                        "space_id": space_id,
                        "crew_ids": crew_ids,
                    },
                )
                return []  # Fail-closed
            return tables

        return filtered_tables

    except Exception as e:
        # Se der erro ao filtrar:
        log_event(
            "bootstrap_table_filter_error",
            {
                "connection_id": connection_id,
                "space_id": space_id,
                "error": str(e)[:500],
                "strict_mode": strict_mode,
            },
        )
        # SEGURANÇA: Em strict_mode, erro => lista vazia (fail-closed)
        if strict_mode:
            return []
        return tables


async def _get_allowed_tables_for_validation(
    db: AsyncSession,
    connection_id: str,
    space_id: str,
    crew_ids: Optional[List[str]] = None,
) -> List[str]:
    """
    Obtém lista de nomes de tabelas permitidas para validação.
    Retorna apenas os nomes (não objetos completos).
    """
    try:
        # Carregar tabelas do connection_metadata
        all_tables = await _load_connection_metadata_tables(
            db=db, connection_id=connection_id
        )

        if not all_tables:
            return []

        # Filtrar por permissões
        # strict_mode=True quando há crew_ids (modo colaborativo) para evitar vazamento de dados
        filtered_tables = await _filter_tables_by_permissions(
            db=db,
            connection_id=connection_id,
            space_id=space_id,
            tables=all_tables,
            crew_ids=crew_ids,
            strict_mode=bool(
                crew_ids
            ),  # Fail-closed quando restrito a crews específicas
        )

        # Extrair apenas nomes
        table_names = []
        for table in filtered_tables:
            schema = table.get("schema", "")
            name = table.get("name", "")
            if name:
                # Retornar nome completo (schema.table) ou apenas nome
                if schema:
                    table_names.append(f"{schema}.{name}")
                else:
                    table_names.append(name)

        return table_names

    except Exception as e:
        log_event(
            "get_allowed_tables_for_validation_error",
            {
                "connection_id": connection_id,
                "space_id": space_id,
                "error": str(e)[:200],
            },
        )
        return []


def _schema_summary_from_tables(
    tables: list[dict], max_tables: int = 30
) -> tuple[list[str], str]:
    logical_tables: list[str] = []
    lines: list[str] = []

    for t in (tables or [])[: max(0, int(max_tables))]:
        schema = str(t.get("schema") or "").strip()
        name = str(t.get("name") or "").strip()
        if not name:
            continue
        logical = f"{schema}.{name}" if schema else name
        logical_tables.append(logical)

        cols = t.get("columns") or []
        col_names: list[str] = []
        if isinstance(cols, list):
            for c in cols[:20]:
                if isinstance(c, dict) and c.get("name"):
                    col_names.append(str(c["name"]))
        if col_names:
            lines.append(f"- {logical} cols: {', '.join(col_names)}")
        else:
            lines.append(f"- {logical}")

    # unique preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for lt in logical_tables:
        if lt not in seen:
            seen.add(lt)
            unique.append(lt)

    return unique, "\n".join(lines)


def _safe_json_loads(text: str) -> Optional[dict]:
    """
    Best-effort JSON parsing for LLM outputs.
    Returns dict on success, None on failure.
    """
    import json as _json

    if not text:
        return None
    try:
        return _json.loads(text)
    except Exception:
        # try extracting first {...} block
        try:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                return _json.loads(text[start : end + 1])
        except Exception:
            return None
    return None


async def _get_table_metadata_stats(
    data_source: Any,  # BaseDataSource, mas usando Any para evitar import circular
    table_name: str,
    schema: str,
    connection_type: str,
) -> Optional[Dict[str, Any]]:
    """
    Obtém row_count via metadados do sistema (INFORMATION_SCHEMA).
    Muito mais rápido que COUNT(*) e sem custo de processamento.
    """
    try:
        full_name = f"{schema}.{table_name}" if schema else table_name

        if connection_type == "bigquery":
            # BigQuery: usar __TABLES__ para row_count (mais rápido que COUNT)
            table_only = table_name.split(".")[-1]
            query = f"""
                SELECT 
                    table_id as table_name,
                    row_count,
                    size_bytes,
                    TIMESTAMP_MILLIS(creation_time) as last_modified
                FROM `{schema}.__TABLES__`
                WHERE table_id = '{table_only}'
                LIMIT 1
            """
        elif connection_type == "postgres":
            # PostgreSQL pg_stat_user_tables (mais rápido)
            table_only = table_name.split(".")[-1]
            query = f"""
                SELECT 
                    schemaname,
                    relname as table_name,
                    n_live_tup as row_count,
                    pg_size_pretty(pg_total_relation_size(schemaname||'.'||relname)) as size
                FROM pg_stat_user_tables
                WHERE relname = '{table_only}'
                LIMIT 1
            """
        else:
            return None

        # Executar com timeout curto
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as executor:
            result = await asyncio.wait_for(
                loop.run_in_executor(executor, data_source.run_query, query),
                timeout=3.0,  # 3 segundos máximo
            )

        if result and len(result) > 0:
            row = result[0]
            return {
                "row_count": int(row.get("row_count", 0)),
                "size_bytes": row.get("size_bytes") or row.get("size"),
                "last_modified": row.get("last_modified"),
            }
    except (FutureTimeoutError, asyncio.TimeoutError):
        log_event("table_metadata_stats_timeout", {"table": table_name})
    except Exception as e:
        log_event(
            "table_metadata_stats_error", {"table": table_name, "error": str(e)[:200]}
        )

    return None


async def _get_table_sample_stats(
    data_source: Any,  # BaseDataSource, mas usando Any para evitar import circular
    table_name: str,
    schema: str,
    columns: List[Dict[str, Any]],
    row_count: int,
    connection_type: str,
) -> Optional[Dict[str, Any]]:
    """
    Coleta estatísticas básicas usando sampling para tabelas grandes.
    Sempre limita o número de linhas processadas.
    """
    try:
        full_name = f"{schema}.{table_name}" if schema else table_name

        # Identificar colunas numéricas (amount, total, value, etc.)
        amount_cols = [
            c.get("name")
            for c in columns
            if any(
                keyword in (c.get("name", "") or "").lower()
                for keyword in ["amount", "total", "value", "revenue", "price", "cost"]
            )
            and any(
                t in (c.get("type", "") or "").upper()
                for t in ["INT", "FLOAT", "NUMERIC", "DECIMAL", "INT64", "FLOAT64"]
            )
        ]

        # Identificar colunas de data
        date_cols = [
            c.get("name")
            for c in columns
            if "DATE" in (c.get("type", "") or "").upper()
        ]

        stats = {}

        # Se tabela é muito grande (> 1M linhas), usar sampling
        use_sampling = row_count > 1_000_000

        # Query para estatísticas de valores (apenas se houver coluna de amount)
        if amount_cols:
            amount_col = amount_cols[0]

            if use_sampling and connection_type == "bigquery":
                # BigQuery: TABLESAMPLE SYSTEM (1 PERCENT)
                query = f"""
                    SELECT 
                        COUNT(*) as sample_count,
                        SUM({amount_col}) as total,
                        AVG({amount_col}) as avg,
                        MIN({amount_col}) as min_val,
                        MAX({amount_col}) as max_val
                    FROM `{full_name}` TABLESAMPLE SYSTEM (1 PERCENT)
                    WHERE {amount_col} IS NOT NULL
                    LIMIT 1
                """
            elif use_sampling and connection_type == "postgres":
                # PostgreSQL: TABLESAMPLE SYSTEM (1)
                query = f"""
                    SELECT 
                        COUNT(*) as sample_count,
                        SUM({amount_col}) as total,
                        AVG({amount_col}) as avg,
                        MIN({amount_col}) as min_val,
                        MAX({amount_col}) as max_val
                    FROM {full_name} TABLESAMPLE SYSTEM (1)
                    WHERE {amount_col} IS NOT NULL
                    LIMIT 1
                """
            else:
                # Para tabelas menores, query completa mas limitada
                if connection_type == "bigquery":
                    query = f"""
                        SELECT 
                            COUNT(*) as sample_count,
                            SUM({amount_col}) as total,
                            AVG({amount_col}) as avg,
                            MIN({amount_col}) as min_val,
                            MAX({amount_col}) as max_val
                        FROM `{full_name}`
                        WHERE {amount_col} IS NOT NULL
                        LIMIT 1
                    """
                else:
                    query = f"""
                        SELECT 
                            COUNT(*) as sample_count,
                            SUM({amount_col}) as total,
                            AVG({amount_col}) as avg,
                            MIN({amount_col}) as min_val,
                            MAX({amount_col}) as max_val
                        FROM {full_name}
                        WHERE {amount_col} IS NOT NULL
                        LIMIT 1
                    """

            try:
                loop = asyncio.get_event_loop()
                with ThreadPoolExecutor() as executor:
                    result = await asyncio.wait_for(
                        loop.run_in_executor(executor, data_source.run_query, query),
                        timeout=5.0,  # 5 segundos máximo
                    )

                if result and len(result) > 0:
                    row = result[0]
                    stats["amount_stats"] = {
                        "total": (
                            float(row.get("total", 0)) if row.get("total") else None
                        ),
                        "avg": float(row.get("avg", 0)) if row.get("avg") else None,
                        "min": (
                            float(row.get("min_val", 0)) if row.get("min_val") else None
                        ),
                        "max": (
                            float(row.get("max_val", 0)) if row.get("max_val") else None
                        ),
                        "sample_count": int(row.get("sample_count", 0)),
                        "is_sampled": use_sampling,
                    }
            except (FutureTimeoutError, asyncio.TimeoutError):
                pass  # Se timeout, continua sem essas stats
            except Exception:
                pass  # Se erro, continua sem essas stats

        # Query para range de datas (apenas se houver coluna de data)
        if date_cols:
            date_col = date_cols[0]

            if connection_type == "bigquery":
                query = f"""
                    SELECT 
                        MIN({date_col}) as min_date,
                        MAX({date_col}) as max_date
                    FROM `{full_name}`
                    WHERE {date_col} IS NOT NULL
                    LIMIT 1
                """
            else:
                query = f"""
                    SELECT 
                        MIN({date_col}) as min_date,
                        MAX({date_col}) as max_date
                    FROM {full_name}
                    WHERE {date_col} IS NOT NULL
                    LIMIT 1
                """

            try:
                loop = asyncio.get_event_loop()
                with ThreadPoolExecutor() as executor:
                    result = await asyncio.wait_for(
                        loop.run_in_executor(executor, data_source.run_query, query),
                        timeout=5.0,
                    )

                if result and len(result) > 0:
                    row = result[0]
                    if row.get("min_date") and row.get("max_date"):
                        stats["date_range"] = {
                            "min": str(row.get("min_date")),
                            "max": str(row.get("max_date")),
                        }
            except (FutureTimeoutError, asyncio.TimeoutError):
                pass
            except Exception:
                pass

        return stats if stats else None

    except Exception as e:
        log_event(
            "table_sample_stats_error", {"table": table_name, "error": str(e)[:200]}
        )
        return None


async def _collect_table_statistics_optimized(
    data_source: Any,  # BaseDataSource, mas usando Any para evitar import circular
    tables: List[Dict[str, Any]],
    connection_id: str,
    connection_type: str,
    max_tables: int = 3,
) -> Dict[str, Any]:
    """
    Coleta estatísticas otimizadas seguindo melhores práticas do mercado:
    - Usa metadados do sistema (rápido, sem custo)
    - Sampling para tabelas grandes
    - Sempre limita linhas processadas
    - Timeout curto e fail-safe
    """
    stats = {}

    # 1. Selecionar tabelas para análise (agnóstico de domínio)
    # Usa as primeiras tabelas disponíveis, limitadas pelo max_tables
    # A seleção será baseada nas tabelas que o usuário tem acesso, não em tipos específicos
    selected_tables = tables[:max_tables]  # Limitar a max_tables tabelas

    if not selected_tables:
        return stats

    # 2. Coletar metadados em paralelo (row_count via INFORMATION_SCHEMA)
    metadata_tasks = []
    for table in selected_tables:
        schema = table.get("schema", "")
        name = table.get("name", "")
        task = _get_table_metadata_stats(data_source, name, schema, connection_type)
        metadata_tasks.append((table, task))

    # Executar todas as queries de metadados em paralelo
    metadata_results = await asyncio.gather(
        *[task for _, task in metadata_tasks], return_exceptions=True
    )

    # 3. Para cada tabela com metadados válidos, coletar stats adicionais
    sample_tasks = []
    for (table, _), metadata_result in zip(metadata_tasks, metadata_results):
        if isinstance(metadata_result, Exception):
            continue

        if not metadata_result or metadata_result.get("row_count", 0) == 0:
            continue

        schema = table.get("schema", "")
        name = table.get("name", "")
        full_name = f"{schema}.{name}" if schema else name
        columns = table.get("columns", [])
        row_count = metadata_result.get("row_count", 0)

        # Incluir row_count nos stats
        stats[full_name] = {
            "row_count": row_count,
            "size_bytes": metadata_result.get("size_bytes"),
            "last_modified": metadata_result.get("last_modified"),
        }

        # Coletar stats adicionais apenas se tabela não for muito grande
        # e tiver menos de 10M linhas (evitar queries muito lentas)
        if 0 < row_count < 10_000_000:
            task = _get_table_sample_stats(
                data_source, name, schema, columns, row_count, connection_type
            )
            sample_tasks.append((full_name, task))

    # Executar queries de sample em paralelo (máximo 3)
    if sample_tasks:
        sample_results = await asyncio.gather(
            *[task for _, task in sample_tasks], return_exceptions=True
        )

        # Adicionar stats de sample aos stats principais
        for (full_name, _), sample_result in zip(sample_tasks, sample_results):
            if isinstance(sample_result, Exception):
                continue

            if sample_result and full_name in stats:
                stats[full_name].update(sample_result)

    return stats


def _fallback_bootstrap(lang: str, max_suggestions: int) -> ChatBootstrapResponse:
    """
    Generic bootstrap suggestions (domain agnostic).
    Used when there isn't enough data for personalized suggestions.
    """
    # ── A reserva fala a lingua de quem pergunta. ─────────────────────
    #
    # O `lang` chegava aqui e era ignorado: com `language=pt` as sugestoes
    # saiam «Monthly performance», «Top results», «Time-based analysis».
    #
    # E esta lista e a que aparece mais vezes, nao menos: e usada sempre que
    # o modelo nao consegue personalizar — que e o caso de qualquer projeto
    # acabado de ligar, ou seja, o primeiro ecra de quem chega.
    _RESERVA = {
        "pt": (
            "Em que posso ajudá-lo com os seus dados?",
            [
                # Perguntas INTEIRAS e auto-suficientes.
                #
                # Estas frases são o rótulo dos botões, e o Lucas apanhou-as
                # numa captura a morrer a meio: «Os maiores» — os maiores
                # quê? «Ao longo do tempo» — o quê ao longo do tempo? Os
                # títulos eram etiquetas de categoria e liam-se como
                # fragmentos.
                #
                # Cada uma tem de dizer sozinha o que vai perguntar, porque é
                # exactamente isso que vai ser perguntado.
                ("Desempenho do mês", "Como correu este mês em comparação com o mês anterior?"),
                ("Os maiores", "Quais são os cinco maiores valores nos meus dados, e de quê?"),
                ("Ao longo do tempo", "O que é que tem subido ou descido ao longo dos últimos meses?"),
                ("Por categoria", "Como é que os totais se dividem por categoria?"),
            ],
        ),
        "es": (
            "¿En qué puedo ayudarle con sus datos?",
            [
                ("Rendimiento del mes", "¿Cómo fue este mes en comparación con el anterior?"),
                ("Los mayores", "¿Cuáles son los cinco mayores valores en mis datos, y de qué?"),
                ("A lo largo del tiempo", "¿Qué ha subido o bajado en los últimos meses?"),
                ("Por categoría", "¿Cómo se reparten los totales por categoría?"),
            ],
        ),
        "en": (
            "How can I help you with your data?",
            [
                ("Monthly performance", "How did this month compare with last month?"),
                ("Top results", "What are the five largest values in my data, and of what?"),
                ("Time-based analysis", "What has gone up or down over the last few months?"),
                ("Category breakdown", "How do the totals split by category?"),
            ],
        ),
    }
    greeting, pares = _RESERVA.get(lang, _RESERVA["en"])
    suggestions: list[ChatBootstrapSuggestion] = [
        ChatBootstrapSuggestion(title=titulo, kind="question", question=pergunta)
        for titulo, pergunta in pares
    ]

    out = suggestions[:max_suggestions]
    while len(out) < max_suggestions:
        _EXEMPLO = {
            "pt": ("Exemplo", "Mostre-me algo interessante nos meus dados."),
            "es": ("Ejemplo", "Muéstreme algo interesante en mis datos."),
            "en": ("Example", "Show me something interesting from my data."),
        }
        _t, _q = _EXEMPLO.get(lang, _EXEMPLO["en"])
        out.append(
            ChatBootstrapSuggestion(
                title=_t,
                kind="question",
                question=_q,
            )
        )
    return ChatBootstrapResponse(
        greeting=greeting, suggestions=out, meta={"fallback": True}
    )


@router.post("/{connection_id}/chat/bootstrap", response_model=ChatBootstrapResponse)
async def chat_bootstrap(
    connection_id: str,
    body: ChatBootstrapRequest,
    db: AsyncSession = Depends(get_db),
) -> ChatBootstrapResponse:
    """
    Sherlock - Gerador de Sugestões Inteligentes

    Generate greeting + suggestion cards for a new chat session.
    This is the "Sherlock" agent that investigates available data and suggests
    relevant business questions the user can click on.

    Supports both Personal and Collaborative modes:
    - Personal mode (is_personal=True): Suggestions based on all crews/spaces user belongs to
    - Collaborative mode (is_personal=False): Suggestions based only on data from specific space/crew
    """
    from core.i18n.i18n import detect_language
    from uuid import UUID

    lang = (body.language or "en").lower()
    if lang not in {"en", "pt"}:
        lang = "en"

    # ✅ Feature Flag: Pausar Bootstrap se solicitado
    if DISABLE_BOOTSTRAP_EXECUTION:
        return ChatBootstrapResponse(
            greeting="Bootstrap is paused (Maintenance Mode)", suggestions=[]
        )

    # ✅ NOVA: Resolver crew_ids baseado no contexto (personal vs collaborative)
    resolved_crew_ids: Optional[List[str]] = None
    try:
        if body.crew_ids:
            # Se crew_ids foram fornecidos explicitamente, usar eles
            resolved_crew_ids = [str(x) for x in body.crew_ids]
        elif body.user_id:
            # Resolver crew_ids automaticamente baseado no modo
            resolved = await resolve_crew_ids_for_context(
                db=db,
                user_id=UUID(body.user_id),
                space_id=UUID(body.space_id) if body.space_id else None,
                request_crew_ids=body.crew_ids,
                is_personal=bool(body.is_personal),
            )
            resolved_crew_ids = [str(x) for x in (resolved or [])]
    except Exception as e:
        log_event(
            "bootstrap_resolve_crew_ids_error",
            {
                "connection_id": connection_id,
                "space_id": body.space_id,
                "user_id": body.user_id,
                "is_personal": bool(body.is_personal),
                "error": str(e),
            },
        )
        # Se falhar, usar lista vazia (apenas dados públicos)
        resolved_crew_ids = []

    # ✅ Calcular time_window baseado em configuração (5 minutos por padrão)
    current_time = datetime.now()
    time_window = int(current_time.timestamp() // BOOTSTRAP_VARIATION_WINDOW_SECONDS)

    # ✅ NOVA: Verificar cache antes de gerar sugestões
    # A chave inclui time_window para variação periódica
    cache_key = _get_cache_key(
        connection_id=connection_id,
        space_id=body.space_id,
        crew_ids=resolved_crew_ids,
        is_personal=bool(body.is_personal),
        language=lang,
        time_window=time_window,  # ✅ MUDANÇA: usa time_window (5 min por padrão)
    )

    cached_response = _get_cached_bootstrap(cache_key)
    if cached_response:
        # Remover qualquer card "create_dashboard" que possa estar no cache antigo
        cached_response.suggestions = [
            sug
            for sug in cached_response.suggestions
            if not (sug.kind == "action" and sug.action_id == "create_dashboard")
        ]

        # Ajustar contagem se necessário após filtrar
        if len(cached_response.suggestions) > body.max_suggestions:
            cached_response.suggestions = cached_response.suggestions[
                : body.max_suggestions
            ]
        while len(cached_response.suggestions) < body.max_suggestions:
            cached_response.suggestions.append(
                ChatBootstrapSuggestion(
                    title="Example",
                    kind="question",
                    question="Show me something interesting from my data.",
                )
            )

        log_event(
            "bootstrap_cache_hit",
            {
                "connection_id": connection_id,
                "space_id": body.space_id,
                "cache_key": cache_key,
                "num_suggestions": len(cached_response.suggestions),
            },
        )
        return cached_response

    log_event(
        "bootstrap_cache_miss",
        {
            "connection_id": connection_id,
            "space_id": body.space_id,
            "cache_key": cache_key,
        },
    )

    # Backend-compatible: read catalog from `connection_metadata`.
    all_tables = await _load_connection_metadata_tables(
        db=db, connection_id=connection_id
    )
    if not all_tables:
        return _fallback_bootstrap(lang=lang, max_suggestions=body.max_suggestions)

    # ✅ NOVA: Filtrar tabelas por permissões (agnóstico, funciona para qualquer domínio)
    # Filtramos sempre, garantindo que o usuário só veja sugestões para dados que ele tem permissão.
    # No modo personal, `resolved_crew_ids` contém todas as crews do usuário.
    # No modo collaborative, contém apenas a crew ativa.
    is_strict = not bool(body.is_personal)  # modo colaborativo = strict

    tables = await _filter_tables_by_permissions(
        db=db,
        connection_id=connection_id,
        space_id=body.space_id,
        tables=all_tables,
        crew_ids=resolved_crew_ids,
        strict_mode=is_strict,
    )

    if not tables:
        # Se após filtrar não há tabelas, retornar fallback
        log_event(
            "bootstrap_no_tables_after_filter",
            {
                "connection_id": connection_id,
                "space_id": body.space_id,
                "is_personal": bool(body.is_personal),
                "crew_ids": resolved_crew_ids,
                "total_tables_before_filter": len(all_tables),
            },
        )
        return _fallback_bootstrap(lang=lang, max_suggestions=body.max_suggestions)

    # Build a compact schema summary for the LLM.
    max_tables_in_prompt = min(30, len(tables))
    _logical, schema_summary = _schema_summary_from_tables(
        tables, max_tables=max_tables_in_prompt
    )

    # ✅ NOVO: Coletar estatísticas dos dados reais (seguindo melhores práticas)
    table_statistics = {}
    stats_cache_key = _get_table_stats_cache_key(
        connection_id, body.space_id, resolved_crew_ids
    )

    # Verificar cache de estatísticas primeiro
    cached_stats = _get_cached_table_stats(stats_cache_key)
    if cached_stats:
        table_statistics = cached_stats
        log_event(
            "bootstrap_table_stats_cache_hit",
            {
                "connection_id": connection_id,
                "num_tables_with_stats": len(table_statistics),
            },
        )
    else:
        # Coletar estatísticas (com timeout total de 8 segundos)
        try:
            # Criar DataSource temporário
            result = await db.execute(
                text(
                    "SELECT id, name, connector_id AS type, config FROM data_connections WHERE id = :id"
                ),
                {"id": connection_id},
            )
            conn_result = result.first()

            if conn_result:

                class TempDataConnection:
                    def __init__(self, id, name, type, config):
                        self.id = id
                        self.name = name
                        self.type = type
                        self.config = (
                            config
                            if isinstance(config, dict)
                            else json.loads(config) if isinstance(config, str) else {}
                        )

                conn_config = conn_result[3]
                if isinstance(conn_config, str):
                    try:
                        conn_config = json.loads(conn_config)
                    except:
                        conn_config = {}
                elif conn_config is None:
                    conn_config = {}

                # Backend stores config encrypted as {"__encrypted": "..."};
                # decrypt with the shared ENCRYPTION_KEY before the factory
                # tries to read host/port/user/password.
                from core.security.config_decryption import decrypt_config

                conn_config = decrypt_config(conn_config)

                data_conn = TempDataConnection(
                    id=str(conn_result[0]),
                    name=conn_result[1],
                    type=conn_result[2] or "bigquery",
                    config=conn_config,
                )

                data_source = DataSourceFactory.build_from_dataconnection(data_conn)
                connection_type = conn_result[2] or "bigquery"

                # Coletar estatísticas com timeout total
                table_statistics = await asyncio.wait_for(
                    _collect_table_statistics_optimized(
                        data_source=data_source,
                        tables=tables[:5],  # Apenas primeiras 5 tabelas
                        connection_id=connection_id,
                        connection_type=connection_type,
                        max_tables=3,  # Máximo 3 tabelas principais
                    ),
                    timeout=8.0,  # Timeout total de 8 segundos
                )

                # Armazenar no cache
                _set_cached_table_stats(stats_cache_key, table_statistics)

                log_event(
                    "bootstrap_table_stats_collected",
                    {
                        "connection_id": connection_id,
                        "num_tables_with_stats": len(table_statistics),
                    },
                )
        except (asyncio.TimeoutError, FutureTimeoutError):
            log_event("bootstrap_table_stats_timeout", {"connection_id": connection_id})
            # Continuar sem stats se timeout
        except Exception as e:
            log_event(
                "bootstrap_table_stats_error",
                {"connection_id": connection_id, "error": str(e)[:200]},
            )
            # Continuar sem stats se erro (fail-safe)

    # Formatar estatísticas para o prompt
    stats_summary = ""
    if table_statistics:
        stats_lines = []
        for table_name, stats in table_statistics.items():
            lines = [f"📊 {table_name}:"]
            if "row_count" in stats:
                row_count = stats["row_count"]
                lines.append(f"  • Total records: {row_count:,}")
            if "amount_stats" in stats:
                amt = stats["amount_stats"]
                if amt.get("total") is not None:
                    lines.append(f"  • Total value: {amt['total']:,.2f}")
                if amt.get("avg") is not None:
                    lines.append(f"  • Average value: {amt['avg']:,.2f}")
                if amt.get("is_sampled"):
                    lines.append(f"  • (Statistics based on sample)")
            if "date_range" in stats:
                dr = stats["date_range"]
                lines.append(f"  • Período: {dr['min']} até {dr['max']}")
            stats_lines.append("\n".join(lines))

        if stats_lines:
            stats_summary = "\n\n".join(stats_lines)

    # ✅ NOVA: Contexto de permissões para o LLM (agnóstico)
    mode_context = ""
    if body.is_personal:
        mode_context = "The user is in PERSONAL mode and has access to all their data across all crews/spaces."
    else:
        mode_context = f"The user is in COLLABORATIVE mode and has access only to data from the specific space/crew (space_id: {body.space_id})."
        if resolved_crew_ids:
            mode_context += f" They have access to {len(resolved_crew_ids)} crew(s)."

    # ── Phase 2.10: Strategic context from the brain ────────────────────
    # Sherlock now retrieves the space's pillars / goals / OKRs / KPIs
    # alongside the discoverable data so its suggestions align with
    # what leadership actually tracks. Empty brain → legacy behaviour.
    try:
        from core.rag.brain_access import (
            fetch_brain_context_for_surface,
            sherlock_context_section,
        )

        _brain_access = await fetch_brain_context_for_surface(
            surface="chat_bootstrap",
            question="strategic priorities pillars goals okrs key metrics",
            db=db,
            embedding_provider=create_embedding_provider(),
            space_id=body.space_id,
            crew_ids=resolved_crew_ids,
            user_id=getattr(body, "user_id", None),
        )
        _brain_section = sherlock_context_section(_brain_access)
    except Exception:
        log_event("sherlock_brain_fetch_failed", {"connection_id": connection_id})
        _brain_section = ""

    system = (
        "You generate a greeting and suggestion cards for a data analytics chat.\n"
        "Rules:\n"
        "- Output STRICT JSON only.\n"
        '- JSON schema: {"greeting": string, "suggestions": [{"title": string, "question": string}]}\n'
        "- Provide EXACTLY N suggestions.\n"
        "- Suggestions must be answerable using ONLY the provided tables/columns.\n"
        "- Avoid mentioning table physical names; prefer natural questions.\n"
        "- Keep questions short and actionable.\n"
        "- IMPORTANT: Avoid time-based filters that might return no data (e.g., 'this month', 'last month', 'recent', 'upcoming', 'pending').\n"
        "- IMPORTANT: Prefer general questions that will return data (e.g., 'What are the main reasons?' instead of 'What are the reasons this month?').\n"
        "- IMPORTANT: Focus on aggregations, summaries, and general analysis rather than specific time periods.\n"
        f"- Language: {lang}\n"
        f"\nContext: {mode_context}\n"
        "- Generate suggestions that are relevant to the user's accessible data only.\n"
        "- Ensure suggestions will return meaningful data when executed.\n"
    )

    # ✅ Calcular seed baseado em janela de tempo configurável
    # Combinar com hash do schema para mais estabilidade e variação entre conexões
    schema_hash = hashlib.md5(schema_summary.encode()).hexdigest()
    combined_seed = f"{connection_id}_{schema_hash}_{time_window}"
    variation_seed = int(hashlib.md5(combined_seed.encode()).hexdigest()[:8], 16) % 6

    # Mapear seed para diferentes ênfases que rotacionam periodicamente
    emphasis_hints = [
        "Focus on performance metrics and KPIs (growth rates, efficiency, profitability, ROI, key indicators).",
        "Focus on comparative analysis (compare performance across regions, categories, segments, dimensions).",
        "Focus on distributions and patterns (how data is spread, identify top/bottom performers, outliers).",
        "Focus on relationships and correlations (connections between different entities, cause-effect analysis).",
        "Focus on segmentation and grouping (breakdowns by dimensions like types, categories, cohorts, statuses).",
        "Focus on aggregations and summaries (totals, averages, percentages, counts, ratios, trends).",
    ]

    current_emphasis = emphasis_hints[variation_seed]

    user = (
        f"N={body.max_suggestions}\n"
        f"User has access to {len(tables)} tables (filtered by permissions).\n\n"
        f"Schema (sample):\n{schema_summary}\n\n"
    )

    # ✅ Adicionar estatísticas reais se disponíveis
    if stats_summary:
        user += (
            f"REAL DATA STATISTICS (use these to generate personalized, data-driven suggestions):\n"
            f"{stats_summary}\n\n"
            f"CRITICAL: Use these real statistics to make suggestions more specific and relevant.\n"
            f"For example:\n"
        )
        # Adicionar exemplos baseados nas stats reais
        first_table_stats = (
            list(table_statistics.values())[0] if table_statistics else {}
        )
        if first_table_stats.get("row_count"):
            user += f"- If a table has {first_table_stats['row_count']:,} rows, suggest 'How many X do we have?'\n"
        if first_table_stats.get("amount_stats", {}).get("total"):
            user += f"- If there's a total amount, suggest 'What is the total revenue?' or 'What is the average value?'\n"
        if first_table_stats.get("date_range"):
            user += (
                f"- If there's a date range, suggest questions about that time period\n"
            )
        user += (
            f"- Make suggestions that will return meaningful data based on these statistics\n"
            f"- Personalize the greeting to mention the data available (e.g., 'You have X records in your main table')\n\n"
        )

    user += (
        f"Context: {mode_context}\n\n"
        "Generate greeting + STRATEGIC BUSINESS QUESTIONS based ONLY on the accessible tables shown above.\n"
        "\n"
        f"Current emphasis (to add variety): {current_emphasis}\n"
        "But ensure you include a DIVERSE MIX of different question types and business perspectives.\n"
        "\n"
        "CRITICAL: Generate questions that:\n"
        "- Focus on BUSINESS METRICS (revenue, profit, value, amounts, totals, averages)\n"
        "- Enable PERFORMANCE ANALYSIS (top performers, rankings, comparisons)\n"
        "- Reveal PATTERNS (distributions, concentrations, correlations, relationships)\n"
        "- Support DECISION-MAKING (segmentation, optimization, opportunity identification)\n"
        "- Provide ACTIONABLE INSIGHTS (specific, measurable, relevant to business goals)\n"
        "\n"
        "VARY the questions across:\n"
        "- Question structures: 'What are...', 'Which...', 'How is...', 'What percentage...', 'Compare...'\n"
        "- Business dimensions: regions, categories, segments, types, statuses, groups, classifications\n"
        "- Analysis methods: top N, average, total, percentage, distribution, correlation, comparison\n"
        "- Business metrics: amounts, values, totals, counts, averages, rates, percentages, indicators\n"
        "\n"
        "FORBIDDEN: Do NOT generate questions about:\n"
        "- Data structure, tables, columns, or schema\n"
        "- Generic exploration ('What data...', 'Which tables...', 'What columns...')\n"
        "- Examples or meta-questions\n"
        "\n"
        "REQUIRED: Each question must:\n"
        "- Be about BUSINESS PERFORMANCE or METRICS\n"
        "- Use the actual column names from the schema (but phrase naturally)\n"
        "- Return meaningful business insights when executed\n"
        "- Be unique and non-repetitive\n"
        "- Avoid time-based filters that might return no data\n"
        "\n"
        "IMPORTANT: Generate questions that will return data - avoid specific time filters like 'this month', 'last month', 'recent', 'upcoming', 'pending'.\n"
        "Prefer general business questions about trends, summaries, aggregations, distributions, and overall business analysis.\n"
        "\n"
        "Think like a C-level executive asking their data team: 'What should I know about my business performance?'\n"
        "Generate questions that a business leader would actually ask to make strategic decisions."
    )

    # Append the brain section to the user prompt (if any). Keeping it
    # at the end means the LLM sees the data shape first, then the
    # strategic priorities it should tilt suggestions toward.
    if _brain_section:
        user = f"{user}\n\n{_brain_section}\n"

    try:
        llm = create_llm_orchestrator(creativity=15, length=20)
        resp = llm.invoke(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )
        parsed = _safe_json_loads(getattr(resp, "content", "") or "")
        if not isinstance(parsed, dict):
            return _fallback_bootstrap(lang=lang, max_suggestions=body.max_suggestions)

        greeting = str(parsed.get("greeting") or "").strip()
        suggestions_raw = parsed.get("suggestions") or []
        suggestions: list[ChatBootstrapSuggestion] = []
        if isinstance(suggestions_raw, list):
            for item in suggestions_raw:
                if isinstance(item, dict):
                    title = str(item.get("title") or "").strip()
                    question = str(item.get("question") or "").strip()
                    if title and question:
                        suggestions.append(
                            ChatBootstrapSuggestion(
                                title=title, kind="question", question=question
                            )
                        )

        if not greeting or len(suggestions) == 0:
            return _fallback_bootstrap(lang=lang, max_suggestions=body.max_suggestions)

        # ✅ NOVA: Validar e filtrar sugestões problemáticas usando SuggestionValidator
        try:
            from core.validation.question_validator import QuestionValidator
            from core.validation.suggestion_validator import SuggestionValidator

            # Preparar metadados para o validador
            available_tables_meta = [
                {
                    "name": t.get("name", ""),
                    "logical_name": t.get("logical_name") or t.get("name", ""),
                    "columns": [
                        c.get("name") if isinstance(c, dict) else str(c)
                        for c in (t.get("columns") or [])
                    ],
                }
                for t in tables[:max_tables_in_prompt]
            ]
            available_columns = {
                (t.get("logical_name") or t.get("name", "")): [
                    c.get("name") if isinstance(c, dict) else str(c)
                    for c in (t.get("columns") or [])
                ]
                for t in tables[:max_tables_in_prompt]
            }

            question_validator = QuestionValidator(
                available_tables_meta, available_columns
            )
            suggestion_validator = SuggestionValidator(question_validator)

            # Filtrar sugestões problemáticas
            filtered_suggestions: list[ChatBootstrapSuggestion] = []
            filtered_count = 0

            for sug in suggestions:
                # Filtrar ações "create_dashboard" - não queremos mais esse card
                if sug.kind == "action" and sug.action_id == "create_dashboard":
                    filtered_count += 1
                    log_event(
                        "bootstrap_suggestion_filtered",
                        {
                            "connection_id": connection_id,
                            "title": sug.title,
                            "reason": "create_dashboard action removed",
                        },
                    )
                    continue  # Pular esta sugestão

                # Validar perguntas
                question_text = sug.question or ""
                if question_text:
                    should_filter = suggestion_validator.should_filter_suggestion(
                        question_text
                    )
                    if should_filter:
                        filtered_count += 1
                        log_event(
                            "bootstrap_suggestion_filtered",
                            {
                                "connection_id": connection_id,
                                "title": sug.title,
                                "question": question_text[:200],
                                "reason": "Failed validation",
                            },
                        )
                        continue  # Pular esta sugestão

                filtered_suggestions.append(sug)

            suggestions = filtered_suggestions

            # Se filtramos muitas sugestões, adicionar algumas de fallback
            if filtered_count > 0 and len(suggestions) < body.max_suggestions:
                log_event(
                    "bootstrap_suggestions_filtered_summary",
                    {
                        "connection_id": connection_id,
                        "filtered_count": filtered_count,
                        "remaining_count": len(suggestions),
                        "requested_count": body.max_suggestions,
                    },
                )
        except Exception as e:
            # Se a validação falhar, não quebra o fluxo - apenas loga
            log_event(
                "bootstrap_validation_exception",
                {
                    "connection_id": connection_id,
                    "error": str(e)[:500],
                },
            )
            # Continua normalmente sem validação

        # Remover qualquer card "create_dashboard" que possa ter sido gerado pela LLM
        suggestions = [
            sug
            for sug in suggestions
            if not (sug.kind == "action" and sug.action_id == "create_dashboard")
        ]

        # Normalize count
        if len(suggestions) > body.max_suggestions:
            suggestions = suggestions[: body.max_suggestions]
        while len(suggestions) < body.max_suggestions:
            suggestions.append(
                ChatBootstrapSuggestion(
                    title="Example",
                    kind="question",
                    question=(
                        suggestions[-1].question
                        if suggestions
                        else "Show me something interesting from my data."
                    ),
                )
            )

        # ── Popular-questions splice ──────────────────────────
        # Mix in the top anonymised questions other people in the
        # space have actually asked. Cap at 2 popular cards so the
        # Sherlock suggestions still dominate. Each card carries
        # `payload.popular = True` so the FE can render the
        # "Asked N×" badge.
        try:
            from core.clients.backend_client import get_backend_client

            popular = get_backend_client().get_popular_questions(
                limit=2, space_id=body.space_id
            )
            if popular:
                # Avoid dupes vs. what Sherlock already produced.
                existing_q = {
                    (s.question or "").strip().lower()
                    for s in suggestions
                    if s.question
                }
                popular_cards: list[ChatBootstrapSuggestion] = []
                for p in popular:
                    q = (p.get("question") or "").strip()
                    if not q or q.lower() in existing_q:
                        continue
                    cnt = int(p.get("count") or 0)
                    popular_cards.append(
                        ChatBootstrapSuggestion(
                            title=q[:48],
                            kind="question",
                            question=q,
                            payload={"popular": True, "count": cnt},
                        )
                    )
                # Replace the LAST N Sherlock suggestions with popular
                # ones (keeps the total at body.max_suggestions).
                if popular_cards:
                    keep = max(1, body.max_suggestions - len(popular_cards))
                    suggestions = suggestions[:keep] + popular_cards
                    suggestions = suggestions[: body.max_suggestions]
        except Exception as exc:
            log_event("bootstrap_popular_skip", {"reason": str(exc)})

        response = ChatBootstrapResponse(
            greeting=greeting,
            suggestions=suggestions,
            meta={
                "fallback": False,
                "num_tables": len(tables),
                "num_tables_total": len(all_tables),
                "prompt_tables": max_tables_in_prompt,
                "agent_id": None,
                "is_personal": bool(body.is_personal),
                "crew_ids": resolved_crew_ids,
                "mode": "personal" if body.is_personal else "collaborative",
                "cached": False,
                "variation_seed": variation_seed,
                "time_window_seconds": BOOTSTRAP_VARIATION_WINDOW_SECONDS,  # ✅ NOVO
                "has_table_stats": len(table_statistics) > 0,  # ✅ NOVO
            },
        )

        # ✅ NOVA: Armazenar no cache após gerar
        _set_cached_bootstrap(cache_key, response)
        log_event(
            "bootstrap_cache_set",
            {
                "connection_id": connection_id,
                "space_id": body.space_id,
                "cache_key": cache_key,
                "cache_size": len(_bootstrap_cache),
            },
        )

        return response
    except Exception:
        return _fallback_bootstrap(lang=lang, max_suggestions=body.max_suggestions)


@router.post("/{connection_id}/dashboards/plan", response_model=DashboardPlanResponse)
async def dashboards_plan(
    connection_id: str,
    body: DashboardPlanRequest,
    db: AsyncSession = Depends(get_db),
) -> DashboardPlanResponse:
    """
    Generate a dashboard plan ("Davinci") for the given connection.
    This does not execute queries; it only proposes widgets/questions.
    """
    lang = (body.language or "en").lower()
    if lang not in {"en", "pt", "es"}:
        lang = "en"

    agent_config = None
    tables = []

    # A língua do painel.
    #
    # Havia aqui um "GLOBAL LANGUAGE GUARD" que devolvia um painel de
    # bloqueio com uma promessa de duas línguas cravada no código.
    # Nunca corria: duas linhas acima o `detected_lang` já era forçado
    # para dentro das línguas conhecidas, portanto o `if` seguinte era
    # sempre falso. Código morto desde antes deste trabalho.
    #
    # **O comportamento a sério é este, e não mudou:** uma pergunta em
    # alemão não bloqueia — responde-se em inglês. Foi por isso que o
    # bloco saiu em vez de ser traduzido: traduzi-lo dava a impressão de
    # que alguém o lê, e ninguém o lê.
    from core.i18n.i18n import detect_language

    detected_lang = lingua_da_resposta(detect_language(body.goal))

    # Sem `language` no pedido, manda a língua do texto do objectivo.
    if not body.language:
        lang = detected_lang

    logical_tables: list[str] = []
    schema_summary = ""
    max_tables_in_prompt = 0

    # ✅ SECURITY: Check for prompt injection in original_question
    original_question = getattr(body, "original_question", None)
    if original_question:
        try:
            from core.security.security_guard import evaluate_security
            from core.llm.factory import create_llm_orchestrator

            # Use orchestrator LLM for security checks (it's a smart model)
            llm_provider = create_llm_orchestrator()
            security_decision = await evaluate_security(
                question=original_question,
                llm_provider=llm_provider,
            )

            if security_decision.is_blocked():
                log_event(
                    "dashboard_plan_security_guard_blocked",
                    {
                        "connection_id": connection_id,
                        "space_id": body.space_id,
                        "user_id": body.user_id,
                        "reason": security_decision.reason,
                        "risk_score": security_decision.risk_score,
                        "llm_category": security_decision.llm_category,
                        "question_preview": original_question[:100],
                    },
                )
                raise HTTPException(
                    status_code=400,
                    detail="I can't help with that request. Please rephrase your question about your data.",
                )
        except HTTPException:
            raise
        except Exception as e:
            log_event("dashboard_plan_security_check_error", {"error": str(e)})

    # Resolve crew_ids based on context (personal vs collaborative).
    # If we don't resolve, the metadata query will default to public-only (crew_id IS NULL),
    # which breaks Personal mode dashboards when metadata is scoped to crews.
    resolved_crew_ids: list[str] = []
    try:
        if body.crew_ids:
            resolved_crew_ids = [str(x) for x in body.crew_ids]
        elif body.user_id:
            from uuid import UUID

            resolved = await resolve_crew_ids_for_context(
                db=db,
                user_id=UUID(body.user_id),
                space_id=UUID(body.space_id) if body.space_id else None,
                request_crew_ids=None,
                is_personal=bool(getattr(body, "is_personal", False)),
            )
            resolved_crew_ids = [str(x) for x in (resolved or [])]
    except Exception as e:
        log_event(
            "dashboards_plan_resolve_crew_ids_error",
            {
                "connection_id": connection_id,
                "space_id": body.space_id,
                "user_id": body.user_id,
                "is_personal": bool(getattr(body, "is_personal", False)),
                "error": str(e),
            },
        )
        resolved_crew_ids = []

    # ✅ NOVA: Verificar cache antes de gerar plano (incluindo original_question e contexto)
    cache_key = _get_dashboard_plan_cache_key(
        connection_id=connection_id,
        space_id=body.space_id,
        crew_ids=resolved_crew_ids,
        is_personal=bool(getattr(body, "is_personal", False)),
        goal=body.goal,
        max_widgets=body.max_widgets,
        language=lang,
        original_question=getattr(body, "original_question", None),
        initial_ai_response=getattr(body, "initial_ai_response", None),
        context_spaces=getattr(body, "context_spaces", None),
        context_crews=getattr(body, "context_crews", None),
        context_tables=getattr(body, "context_tables", None),
        mode=getattr(body, "mode", "mix"),
    )

    # CACHE DISABLED per user request to ensure fresh generation and avoid stale errors.
    # cached_response = _get_cached_dashboard_plan(cache_key)
    # if cached_response:
    #     log_event(
    #         "dashboard_plan_cache_hit",
    #         {
    #             "connection_id": connection_id,
    #             "space_id": body.space_id,
    #             "cache_key": cache_key,
    #             "num_widgets": len(cached_response.widgets),
    #         },
    #     )
    #     # Atualizar meta para indicar que veio do cache
    #     if cached_response.meta:
    #         cached_response.meta["cached"] = True
    #     return cached_response

    log_event(
        "dashboard_plan_cache_miss",
        {
            "connection_id": connection_id,
            "space_id": body.space_id,
            "cache_key": cache_key,
        },
    )

    # Prefer backend-provided overrides (avoids needing this service to query the DB schema correctly).
    try:
        if body.logical_tables_override:
            logical_tables = [
                str(x) for x in body.logical_tables_override if str(x).strip()
            ]
            schema_summary = str(body.schema_summary_override or "").strip()
            max_tables_in_prompt = min(30, len(logical_tables))
        else:
            tables = await _load_connection_metadata_tables(
                db=db, connection_id=connection_id
            )

            # 🔥 SECURITY FIX: Filtrar tabelas por permissões de Crew antes do enrichment e do LLM.
            # Isso impede que o Davinci planeje widgets usando tabelas não autorizadas.
            is_strict = not bool(getattr(body, "is_personal", False))
            tables = await _filter_tables_by_permissions(
                db=db,
                connection_id=connection_id,
                space_id=body.space_id,
                tables=tables,
                crew_ids=resolved_crew_ids,
                strict_mode=is_strict,
            )

            # ✅ Enrich with AI metadata (date ranges!)
            tables = await _enrich_tables_with_ai_metadata(
                db=db, connection_id=connection_id, tables=tables
            )

            # ✅ SEMANTIC RE-RANKING (Hybrid Logic)
            # If we have an original question, use vector search to bubble up relevant tables.
            original_q_for_rank = getattr(body, "original_question", None) or body.goal
            if original_q_for_rank and len(tables) > 0:
                try:
                    # 1. Instantiate Provider using Factory
                    provider = create_embedding_provider()

                    # 2. Search (Top 50 to get good coverage)
                    # We search for the question + goal to maximize context
                    search_query = f"{original_q_for_rank}"

                    # We pass connection_id to enable "Hybrid Search" (Global + Local) if supported,
                    # but typically we want to search within this specific connection's metadata scope.
                    # search_embeddings_async arguments: space_id, crew_ids, query, top_k...
                    # NOTE: Schema embeddings are usually linked to connection_id via TableMetadata -> data_connection_id logic.
                    # vector_store.search_embeddings_async supports connection_id filtering.

                    # Flatten selected_context into a single allowlist of
                    # document_ids for the RAG. An empty allowlist (no
                    # selection provided) disables the filter.
                    _sel_ctx = getattr(body, "selected_context", None) or {}
                    _allowed_doc_ids = [
                        str(_id) for ids in _sel_ctx.values() if ids for _id in ids
                    ] or None

                    top_records = await search_embeddings_async(
                        db=db,
                        embedding_provider=provider,
                        space_id=body.space_id,
                        crew_ids=resolved_crew_ids,
                        query_text=search_query,
                        top_k=50,
                        connection_id=connection_id,
                        is_personal=bool(getattr(body, "is_personal", False)),
                        user_id=getattr(body, "user_id", None),
                        allowed_document_ids=_allowed_doc_ids,
                        caller_space_ids=getattr(body, "space_ids", None),
                    )

                    # 3. Extract scores
                    # Record: extra_metadata={'table_name': '...'}
                    # We want to map Table -> Min Distance (Best Match)
                    # Lower distance is better.
                    table_scores = {}
                    for rec in top_records:
                        t_name = (rec.extra_metadata or {}).get("table_name")
                        if not t_name:
                            continue

                        # Use a simple score: 1.0 for top result, decreasing.
                        # Or just use rank order.
                        # Let's use rank order boosting.
                        if t_name not in table_scores:
                            table_scores[t_name] = 0
                        table_scores[t_name] += 1  # Frequency boost?
                        # Actually simple presence in top K is a strong signal.

                    # 4. Sort 'tables' list
                    # Tables is a list of dicts. We need to match names.
                    # Sort key: -score (descending), then name (asc)
                    def get_score(t_meta):
                        tn = t_meta.get("name", "")
                        return table_scores.get(tn, 0) + table_scores.get(
                            t_meta.get("logical_name", ""), 0
                        )

                    # Stable sort: relevant first, then original order
                    tables.sort(key=lambda t: get_score(t), reverse=True)

                    log_event(
                        "dashboard_plan_semantic_rerank",
                        {
                            "query": search_query[:50],
                            "top_tables": [t.get("name") for t in tables[:5]],
                        },
                    )

                except Exception as e:
                    log_event("dashboard_plan_rerank_error", {"error": str(e)})

            max_tables_in_prompt = min(30, len(tables))
            logical_tables, schema_summary = _schema_summary_from_tables(
                tables, max_tables=max_tables_in_prompt
            )
    except Exception:
        tables = []
        logical_tables = []
        schema_summary = ""
        max_tables_in_prompt = 0

    try:
        llm = create_llm_specialist(creativity=10, length=35)  # gpt-4o by default
        # ✅ NOVO: Passar original_question e contextos para generate_dashboard_plan
        # A IA só será chamada aqui (quando o endpoint é invocado ao clicar em "Criar Dashboard")
        original_question = getattr(body, "original_question", None)
        initial_ai_response = getattr(body, "initial_ai_response", None)
        context_spaces = getattr(body, "context_spaces", None)
        context_crews = getattr(body, "context_crews", None)
        context_tables = getattr(body, "context_tables", None)

        # 🔗 NEW: Analysis Context Bridge
        # Try to retrieve validated intent from the chat session
        user_id_str = (
            str(body.user_id) if hasattr(body, "user_id") and body.user_id else "anon"
        )
        analysis_context = AnalysisSessionStore.get(user_id_str, connection_id)

        if analysis_context:
            log_event(
                "dashboard_plan_context_found",
                {
                    "user_id": user_id_str,
                    "analysis_type": analysis_context.detected_analysis_type,
                    "entity": analysis_context.primary_entity,
                },
            )

        # ── Phase 2.10: Brain context for Davinci ────────────────────
        # Pull pillars / goals / OKRs / KPIs / connections / widgets
        # relevant to the user's goal + original_question so the plan
        # aligns with company strategy — not just the raw schema.
        try:
            from core.rag.brain_access import (
                davinci_context_section,
                fetch_brain_context_for_surface,
            )

            _davinci_query = (
                " ".join(q for q in [original_question, body.goal] if q).strip()
                or body.goal
            )
            _brain_access = await fetch_brain_context_for_surface(
                surface="dashboard_plan",
                question=_davinci_query,
                db=db,
                embedding_provider=create_embedding_provider(),
                space_id=getattr(body, "space_id", None),
                crew_ids=context_crews or [],
                user_id=getattr(body, "user_id", None),
                connection_id=connection_id,
            )
            _brain_section = davinci_context_section(_brain_access)
        except Exception:
            log_event("davinci_brain_fetch_failed", {"connection_id": connection_id})
            _brain_section = ""

        # 🏃 ASYNC FIX: Offload synchronous agent to thread to prevent loop blocking
        plan = await asyncio.to_thread(
            generate_dashboard_plan,
            llm=llm,
            goal=body.goal,
            language=lang,
            max_widgets=body.max_widgets,
            logical_tables=logical_tables,
            schema_summary=schema_summary,
            original_question=original_question,
            initial_ai_response=initial_ai_response,
            context_spaces=context_spaces,
            context_crews=context_crews,
            context_tables=context_tables,
            table_metadata=tables,  # ✅ Pass full metadata for Schema Intelligence
            analysis_context=analysis_context,  # 🔗 Pass the context bridge
            mode=getattr(body, "mode", "mix"),
            brain_context=_brain_section,  # Phase 2.10
        )
        widgets = [DashboardPlanWidget(**w) for w in plan.widgets]
        response = DashboardPlanResponse(
            dashboard_name=plan.dashboard_name,
            title=plan.dashboard_name,
            description=plan.description,
            widgets=widgets,
            meta={
                **(plan.meta or {}),
                "num_tables": len(logical_tables),
                "prompt_tables": max_tables_in_prompt,
                "agent_id": None,
                "cached": False,
                "has_original_question": original_question is not None,
            },
            full_results=plan.full_results,  # ✅ Pass raw insights to frontend
        )

        # ✅ NOVA: Armazenar no cache após gerar
        # CACHE DISABLED per user request
        # _set_cached_dashboard_plan(cache_key, response)
        log_event(
            "dashboard_plan_cache_set",
            {
                "connection_id": connection_id,
                "space_id": body.space_id,
                "cache_key": cache_key,
                "cache_size": len(_dashboard_plan_cache),
            },
        )

        return response
    except HTTPException:
        raise  # Re-raise HTTP exceptions without modification
    except Exception as e:
        # Log technical details internally
        logger.error(
            "Dashboard generation failed",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
                "connection_id": connection_id,
                "user_id": str(body.user_id) if body.user_id else None,
                "space_id": str(body.space_id) if body.space_id else None,
            },
        )

        # User-friendly message (NO stack trace or technical details)
        raise HTTPException(
            status_code=500,
            detail="Unable to generate dashboard. Please try selecting specific tables or simplifying your request.",
        )


@router.get("/{connection_id}/tables")
async def list_available_tables(
    connection_id: str,
    space_id: str = Query(..., description="ID do space (obrigatório)"),
    user_id: Optional[str] = Query(None, description="ID do usuário (opcional)"),
    crew_ids: Optional[List[str]] = Query(
        None, description="Lista de crew_ids (opcional)"
    ),
    is_personal: bool = Query(
        False, description="Modo personal (acesso a todos os crews)"
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Lista todas as tabelas disponíveis para uma conexão, respeitando permissões do usuário.

    Parâmetros:
    - connection_id: ID da conexão
    - space_id: ID do space (query parameter obrigatório)
    - user_id: ID do usuário (opcional, para filtrar por permissões)
    - crew_ids: Lista de crew_ids (opcional, será resolvido automaticamente se user_id fornecido)
    - is_personal: Se True, retorna tabelas de todos os crews do usuário (modo personal)

    Retorna:
    - Lista de tabelas com seus schemas (nome, colunas, tipos)
    """
    from core.auth.service import resolve_crew_ids_for_context
    from uuid import UUID

    # Resolver crew_ids baseado no contexto (personal vs collaborative)
    resolved_crew_ids = crew_ids or []
    if user_id:
        try:
            resolved_crew_ids = await resolve_crew_ids_for_context(
                db=db,
                user_id=UUID(user_id),
                space_id=UUID(space_id) if space_id else None,
                request_crew_ids=crew_ids,
                is_personal=is_personal,
            )
            resolved_crew_ids = [str(crew_id) for crew_id in resolved_crew_ids]
        except Exception as e:
            log_event(
                "api_list_tables_resolve_crew_ids_error",
                {
                    "connection_id": connection_id,
                    "user_id": user_id,
                    "space_id": space_id,
                    "error": str(e),
                },
            )
            # Se falhar ao resolver, usar lista vazia (apenas dados públicos)
            resolved_crew_ids = []

    # Load raw tables from connection_metadata
    raw_tables = await _load_connection_metadata_tables(
        db=db, connection_id=connection_id
    )

    # FIX 3: Apply crew-level permission filtering in collaborative mode.
    # Previously, this endpoint resolved crew_ids but did NOT filter the tables.
    # Now we enforce strict_mode=True when specific crews are active.
    if not is_personal and resolved_crew_ids:
        raw_tables = await _filter_tables_by_permissions(
            db=db,
            connection_id=connection_id,
            space_id=space_id,
            tables=raw_tables,
            crew_ids=resolved_crew_ids,
            strict_mode=True,  # fail-closed: collaborative mode must not expose other crews
        )
        log_event(
            "api_list_tables_filtered_by_crew",
            {
                "connection_id": connection_id,
                "space_id": space_id,
                "crew_ids": resolved_crew_ids,
                "num_tables_after_filter": len(raw_tables),
            },
        )

    tables_info = []
    for t in raw_tables:
        schema = str(t.get("schema") or "").strip()
        name = str(t.get("name") or "").strip()
        if not name:
            continue
        full_name = f"{schema}.{name}" if schema else name

        cols = t.get("columns") or []
        columns = []
        if isinstance(cols, list):
            for c in cols:
                if not isinstance(c, dict):
                    continue
                cname = c.get("name")
                if not cname:
                    continue
                columns.append(
                    {
                        "name": str(cname),
                        "type": str(c.get("type") or "STRING"),
                        "nullable": bool(c.get("nullable", True)),
                        "description": c.get("description"),
                    }
                )

        tables_info.append(
            {"name": full_name, "columns": columns, "num_columns": len(columns)}
        )

    log_event(
        "api_list_tables_success",
        {
            "connection_id": connection_id,
            "space_id": space_id,
            "user_id": user_id,
            "num_tables": len(tables_info),
            "crew_ids": resolved_crew_ids,
            "is_personal": is_personal,
        },
    )

    return {
        "connection_id": connection_id,
        "space_id": space_id,
        "tables": tables_info,
        "total_tables": len(tables_info),
    }


def _source_qualifier(physical_name: str) -> str:
    """Short source token from a physical name, used to disambiguate same-named
    tables across connections: the dataset for project.dataset.table, the schema
    for schema.table, else the bare name."""
    parts = [p for p in str(physical_name).replace("`", "").split(".") if p]
    if len(parts) >= 3:
        return parts[-2]
    if len(parts) == 2:
        return parts[0]
    return parts[-1] if parts else "src"


def _disambiguate_table_labels(table_schemas: list) -> None:
    """When two connections expose tables with the same logical_name, give the
    colliding ones a display_name qualified by source (e.g. 'finance.invoices'
    vs 'billing_silver.invoices') so the orchestrator can pick the right one.
    logical_name/physical_name stay untouched — RAG, relationships and
    authorized_tables keep matching on the originals. No-op without collisions."""
    from collections import defaultdict

    by_logical = defaultdict(list)
    for t in table_schemas:
        by_logical[t.logical_name].append(t)
    for logical, group in by_logical.items():
        conns = {getattr(t, "data_connection_id", None) for t in group}
        if len(group) > 1 and len(conns) > 1:
            for t in group:
                t.display_name = f"{_source_qualifier(t.physical_name)}.{logical}"


async def load_agent_config_from_connection(
    db: AsyncSession,
    space_id: str,
    connection_id: str,
    crew_ids: Optional[List[str]] = None,
    authorized_tables: Optional[List[str]] = None,
    connection_ids: Optional[List[str]] = None,
    space_ids: Optional[List[str]] = None,
) -> AgentConfig:
    """
    Carrega TableMetadata e monta AgentConfig automaticamente para uma conexão.
    Compatível com schema real do banco (usa SQL raw).
    """
    log_event(
        "load_agent_config_start",
        {"space_id": space_id, "connection_id": connection_id, "crew_ids": crew_ids},
    )

    from core.dialects import Dialect

    # 1. Fetch connection type and config
    conn_result = await db.execute(
        text(
            "SELECT connector_id AS type, config FROM data_connections WHERE id = :id"
        ),
        {"id": connection_id},
    )
    row = conn_result.first()
    if not row:
        raise HTTPException(404, detail="Connection not found")

    ds_type = (row[0] or "").lower()
    config = row[1] if row[1] else {}
    if isinstance(config, str):
        config = json.loads(config)
    # Backend writes config encrypted; decrypt before downstream uses
    # host/database/etc. (no-op when already plaintext).
    from core.security.config_decryption import decrypt_config

    config = decrypt_config(config)

    # Map type to Dialect
    dialect = Dialect.POSTGRES  # default fallback
    if ds_type == "bigquery":
        dialect = Dialect.BIGQUERY
    elif ds_type == "api":
        dialect = Dialect.NOSQL  # APIs are NoSQL
    elif ds_type == "mysql":
        dialect = Dialect.MYSQL
    elif ds_type == "snowflake":
        dialect = Dialect.SNOWFLAKE

    # Prefer backend-native catalog (poc backend writes to connection_metadata.tables).
    try:
        result = await db.execute(
            text(
                "SELECT tables FROM connection_metadata WHERE connection_id = CAST(:cid AS uuid) LIMIT 1"
            ),
            {"cid": connection_id},
        )
        tables_json = result.scalar_one_or_none()

        if isinstance(tables_json, list) and len(tables_json) > 0:
            project_id = None
            if isinstance(config, dict):
                project_id = config.get("project_id") or config.get("gcp_project_id")

            # 🔥 SECURITY FIX: Filtrar tabelas recuperadas via JSON do connection_metadata
            # Se authorized_tables for fornecido (Backend), essa é a fonte absoluta de permissão.
            if authorized_tables is not None:
                tables_json = [
                    t
                    for t in tables_json
                    if str(t.get("name") or "").strip() in authorized_tables
                ]
                logger.info(
                    f"Filtro estrito via authorized_tables. Tabelas retidas: {len(tables_json)}"
                )
            # Caso contrário, fallback para a checagem falha de crew_id no DB (apenas log/alert ou legacy)
            elif crew_ids is not None:
                tables_json = await _filter_tables_by_permissions(
                    db=db,
                    connection_id=connection_id,
                    space_id=space_id,
                    tables=tables_json,
                    crew_ids=crew_ids,
                    strict_mode=True,
                )

            # ✅ ENRICH with user-defined descriptions from table_metadata
            # This allows users to add semantic descriptions to tables/columns via UI
            # and have the AI use them for better table selection.
            try:
                # Em modo personal space_ids contém todos os spaces do utilizador;
                # em modo collaborative usa apenas space_id (singular).
                _eff_space_ids = (
                    space_ids if space_ids else ([space_id] if space_id else [])
                )
                if _eff_space_ids:
                    desc_result = await db.execute(
                        text("""
                            SELECT table_name, column_name, description
                            FROM table_metadata
                            WHERE data_connection_id = :conn_id
                              AND (space_id = ANY(CAST(:space_ids AS uuid[])) OR space_id IS NULL)
                              AND description IS NOT NULL
                            """),
                        {"conn_id": connection_id, "space_ids": _eff_space_ids},
                    )
                else:
                    desc_result = await db.execute(
                        text("""
                            SELECT table_name, column_name, description
                            FROM table_metadata
                            WHERE data_connection_id = :conn_id
                              AND space_id IS NULL
                              AND description IS NOT NULL
                            """),
                        {"conn_id": connection_id},
                    )
                desc_rows = desc_result.fetchall()
                if desc_rows:
                    # Build lookup: { table_name -> { col_name -> description, "_table_" -> description } }
                    desc_lookup: dict = {}
                    for row in desc_rows:
                        tname, cname, desc = row[0], row[1], row[2]
                        if tname not in desc_lookup:
                            desc_lookup[tname] = {}
                        if cname:
                            desc_lookup[tname][cname] = desc
                        else:
                            desc_lookup[tname]["_table_"] = desc

                    # Inject descriptions into tables_json
                    for t in tables_json:
                        tname = str(t.get("name") or "").strip()
                        if tname in desc_lookup:
                            # Inject table-level description (use first column desc as fallback)
                            if "_table_" in desc_lookup[tname]:
                                t["description"] = desc_lookup[tname]["_table_"]
                            elif not t.get("description"):
                                # Use first non-null column desc as table description
                                first_desc = next(
                                    iter(desc_lookup[tname].values()), None
                                )
                                if first_desc:
                                    t["description"] = first_desc
                            # Inject column-level descriptions
                            for col in t.get("columns") or []:
                                cname = str(col.get("name") or "").strip()
                                if cname in desc_lookup.get(tname, {}):
                                    col["description"] = desc_lookup[tname][cname]

                    log_event(
                        "load_agent_config_descriptions_enriched",
                        {
                            "connection_id": connection_id,
                            "tables_enriched": list(desc_lookup.keys()),
                        },
                    )
            except Exception as desc_err:
                log_event(
                    "load_agent_config_descriptions_enrich_error",
                    {"error": str(desc_err)[:300]},
                )

            table_schemas: list[TableSchema] = []
            for t in tables_json:
                if not isinstance(t, dict):
                    continue
                schema = str(t.get("schema") or "").strip()
                name = str(t.get("name") or "").strip()
                if not name:
                    continue

                # Physical name for BigQuery: project.dataset.table (best-effort)
                if schema and project_id:
                    physical_name = f"{project_id}.{schema}.{name}"
                elif schema:
                    physical_name = f"{schema}.{name}"
                else:
                    physical_name = name

                # Use logical_name from metadata if exists, otherwise normalize
                logical_name = t.get("logical_name") or _normalize_logical_name(name)
                cols = t.get("columns") or []
                columns = []
                if isinstance(cols, list):
                    for c in cols:
                        if not isinstance(c, dict):
                            continue
                        cname = c.get("name")
                        if not cname:
                            continue
                        columns.append(
                            {
                                "name": str(cname),
                                "type": str(
                                    c.get("type") or c.get("data_type") or "STRING"
                                ),
                                "nullable": bool(c.get("nullable", True)),
                                "description": c.get("description"),
                            }
                        )

                table_schemas.append(
                    TableSchema(
                        logical_name=logical_name,
                        physical_name=physical_name,
                        description=t.get("description"),
                        columns=columns,
                        data_connection_id=connection_id,
                    )
                )

            if table_schemas:
                # Merge extra connection metadata when multiple connections are
                # requested (e.g. all Space connections for cross-schema queries).
                extra_conn_ids = [
                    cid
                    for cid in (connection_ids or [])
                    if cid and cid != connection_id
                ]
                if extra_conn_ids:
                    # Track physical names already present so the same table
                    # surfaced by overlapping connections is not merged twice.
                    # Distinct physical names from different connections are
                    # kept side by side (each tagged with its source below),
                    # which is what lets the orchestrator disambiguate tables
                    # that share a logical name across connections.
                    seen_physicals = {ts.physical_name for ts in table_schemas}
                    for extra_cid in extra_conn_ids:
                        try:
                            extra_meta = await db.execute(
                                text(
                                    "SELECT tables FROM connection_metadata WHERE connection_id = CAST(:cid AS uuid) LIMIT 1"
                                ),
                                {"cid": extra_cid},
                            )
                            extra_tables_json = extra_meta.scalar_one_or_none()
                            if isinstance(extra_tables_json, list):
                                extra_cfg = await db.execute(
                                    text(
                                        "SELECT connector_id, config FROM data_connections WHERE id = :id"
                                    ),
                                    {"id": extra_cid},
                                )
                                extra_row = extra_cfg.first()
                                extra_project_id = None
                                if extra_row and extra_row[1]:
                                    extra_config = (
                                        extra_row[1]
                                        if isinstance(extra_row[1], dict)
                                        else json.loads(extra_row[1])
                                    )
                                    from core.security.config_decryption import (
                                        decrypt_config,
                                    )

                                    extra_config = decrypt_config(extra_config)
                                    extra_project_id = extra_config.get(
                                        "project_id"
                                    ) or extra_config.get("gcp_project_id")
                                for t in extra_tables_json:
                                    if not isinstance(t, dict):
                                        continue
                                    extra_schema = str(t.get("schema") or "").strip()
                                    extra_name = str(t.get("name") or "").strip()
                                    if not extra_name:
                                        continue
                                    if extra_schema and extra_project_id:
                                        extra_physical = f"{extra_project_id}.{extra_schema}.{extra_name}"
                                    elif extra_schema:
                                        extra_physical = f"{extra_schema}.{extra_name}"
                                    else:
                                        extra_physical = extra_name
                                    if extra_physical in seen_physicals:
                                        continue
                                    seen_physicals.add(extra_physical)
                                    extra_logical = t.get(
                                        "logical_name"
                                    ) or _normalize_logical_name(extra_name)
                                    extra_cols = []
                                    for c in t.get("columns") or []:
                                        if not isinstance(c, dict) or not c.get("name"):
                                            continue
                                        extra_cols.append(
                                            {
                                                "name": str(c["name"]),
                                                "type": str(
                                                    c.get("type")
                                                    or c.get("data_type")
                                                    or "STRING"
                                                ),
                                                "nullable": bool(
                                                    c.get("nullable", True)
                                                ),
                                                "description": c.get("description"),
                                            }
                                        )
                                    table_schemas.append(
                                        TableSchema(
                                            logical_name=extra_logical,
                                            physical_name=extra_physical,
                                            description=t.get("description"),
                                            columns=extra_cols,
                                            data_connection_id=extra_cid,
                                        )
                                    )
                        except Exception as merge_err:
                            log_event(
                                "load_agent_config_merge_extra_conn_error",
                                {"extra_cid": extra_cid, "error": str(merge_err)[:300]},
                            )

                # Disambiguate same logical_name across merged connections.
                _disambiguate_table_labels(table_schemas)

                agent = AgentConfig(
                    id=f"agent-conn-{connection_id}",
                    name=f"Agent for connection {connection_id}",
                    tables=table_schemas,
                    dialect=dialect,  # 🔥 Pass correct dialect
                    extra={"project_id": project_id},
                )
                log_event(
                    "load_agent_config_from_connection_metadata",
                    {
                        "space_id": space_id,
                        "connection_id": connection_id,
                        "extra_connection_ids": extra_conn_ids,
                        "dialect": dialect.value,
                        "num_tables": len(table_schemas),
                    },
                )
                return agent
    except Exception as e:
        log_event(
            "load_agent_config_connection_metadata_error",
            {
                "space_id": space_id,
                "connection_id": connection_id,
                "error": str(e)[:500],
            },
        )

        if (
            not tables_json
            or not isinstance(tables_json, list)
            or len(tables_json) == 0
        ):
            log_event(
                "load_agent_config_no_connection_metadata",
                {"connection_id": connection_id},
            )
            # Proceed to legacy table_metadata check

    # Construir query SQL com filtro de permissões.
    #
    # Incident 2026-04-15 / migration 003: legacy rows created before
    # space_id was added to `data_connections` / `table_metadata` have
    # space_id = NULL. Migration 003 backfills whatever it can resolve,
    # but truly orphan rows (no space_connections link, creator has no
    # space membership) stay NULL. Accepting `space_id IS NULL` here as
    # a last resort keeps those connections usable — they simply aren't
    # scoped to any particular space and fall through permission filters
    # the way public metadata always has.
    query_sql = """
        SELECT table_name, column_name, data_type, is_nullable, description
        FROM table_metadata
        WHERE data_connection_id = :conn_id
          AND (space_id = :space_id OR space_id IS NULL)
    """
    query_params = {"space_id": space_id, "conn_id": connection_id}

    # ── O filtro por equipa saiu daqui ────────────────────────────────
    #
    # Estava assim:
    #
    #     if crew_ids:  AND (crew_id IS NULL OR crew_id = ANY(:crew_ids))
    #     else:         AND crew_id IS NULL
    #
    # e este é o caminho do `/connections/{id}/query` — o que responde às
    # perguntas. Bastava a descoberta escrever um `crew_id` numa linha para
    # essa tabela desaparecer de quem não estivesse nessa equipa exacta; e
    # quem não estivesse em equipa nenhuma via só o que tivesse `crew_id`
    # nulo. Foi metade da causa do «Ainda não há dados ligados aqui» com
    # cinco ligações à vista.
    #
    # **Eu já tinha tirado este filtro — no sítio errado.** Tirei-o do
    # `core/agents/factory.py` e dei a fatia por fechada, sem procurar as
    # outras cópias da mesma regra. Esta é a que estava no caminho quente.
    #
    # O acesso ao projeto já foi decidido antes de chegar aqui; o `space_id`
    # acima é a fronteira. A equipa é uma etiqueta (decisão de 2026-08-27) e
    # um segundo filtro só podia estreitar o que já estava certo.
    _ = crew_ids  # mantido no contexto para os registos, não filtra

    query_sql += " ORDER BY table_name, column_name"

    # Buscar metadados via SQL direto (compatível com UUID)
    db_result = await db.execute(text(query_sql), query_params)
    result = db_result.fetchall()

    log_event(
        "load_agent_config_metadata_query",
        {
            "space_id": space_id,
            "connection_id": connection_id,
            "num_rows_found": len(result) if result else 0,
        },
    )

    if not result:
        log_event(
            "load_agent_config_no_metadata",
            {
                "space_id": space_id,
                "connection_id": connection_id,
            },
        )
        raise HTTPException(
            status_code=404,
            detail=f"No metadata found for this connection. Please execute table discovery first.",
        )

    # Agrupar por tabela
    tables: dict[str, list] = {}
    for row in result:
        table_name = row[0]
        if table_name not in tables:
            tables[table_name] = []
        tables[table_name].append(
            {
                "column_name": row[1],
                "data_type": row[2] or "STRING",
                "is_nullable": row[3] or False,
                "description": row[4],
            }
        )

    log_event(
        "load_agent_config_tables_grouped",
        {
            "space_id": space_id,
            "connection_id": connection_id,
            "num_unique_tables": len(tables),
            "table_names": list(tables.keys()),
        },
    )

    # Detectar dataset baseado no nome da tabela ou config da conexão
    def detect_dataset(table_name: str, conn_config: dict) -> str:
        """Detecta o dataset correto baseado no nome da tabela ou config"""
        # Tabelas do web_silver
        web_tables = [
            "silver_events_enriquecido",
            "silver_pageviews_enriquecido",
            "silver_sessions_enriquecido",
            "silver_sources_enriquecido",
            "silver_users_enriquecido",
            "silver_web_data_enriquecido",
        ]
        if table_name in web_tables:
            return "data-mesh-gcp.web_silver"

        # Usar dataset do config da conexão
        # Fallback genérico: usar o dataset configurado ou None (será tratado apropriadamente)
        dataset = conn_config.get("dataset")
        if not dataset:
            return None
        # Se já tem projeto, usar direto; senão, adicionar projeto
        if "." in dataset and not dataset.startswith("data-mesh-gcp."):
            return dataset
        return dataset

    # Buscar config da conexão (REMOVIDO - já carregado no início da função)
    # config já existe no escopo local

    # Processar type para metadados
    project_id = None
    if isinstance(config, dict):
        project_id = config.get("project_id") or config.get("gcp_project_id")

    # Criar TableSchemas
    table_schemas: list[TableSchema] = []
    for table_name, columns in tables.items():
        # Lógica de dataset
        dataset = detect_dataset(table_name, config)

        # Nome físico
        if dataset:
            if project_id and not dataset.startswith(f"{project_id}."):
                physical_name = f"{project_id}.{dataset}.{table_name}"
            else:
                physical_name = f"{dataset}.{table_name}"
        else:
            physical_name = table_name

        # Tentar inferir descrição da tabela (usando a primeira disponível nas colunas)
        table_desc = None
        for c in columns:
            if c.get("description"):
                table_desc = c.get("description")
                break

        table_schemas.append(
            TableSchema(
                logical_name=_normalize_logical_name(table_name),
                physical_name=physical_name,
                description=table_desc,
                columns=[
                    {
                        "name": c["column_name"],
                        "type": c["data_type"],
                        "nullable": c["is_nullable"],
                        "description": c["description"],
                    }
                    for c in columns
                ],
            )
        )

    # DEBUG: Log description of planets table
    for t in table_schemas:
        if t.logical_name == "planets":
            log_event(
                "debug_planets_metadata",
                {
                    "logical_name": t.logical_name,
                    "description": t.description,
                    "num_cols": len(t.columns),
                },
            )

    agent = AgentConfig(
        id=f"agent-conn-{connection_id}",
        name=f"Agent for connection {connection_id}",
        tables=table_schemas,
        dialect=dialect,  # 🔥 Pass correct dialect
        extra={"project_id": project_id},
    )

    log_event(
        "load_agent_config_complete",
        {
            "space_id": space_id,
            "connection_id": connection_id,
            "agent_id": agent.id,
            "num_tables": len(table_schemas),
            "table_schemas": [
                {
                    "logical_name": t.logical_name,
                    "physical_name": t.physical_name,
                    "num_columns": len(t.columns),
                }
                for t in table_schemas
            ],
        },
    )

    return agent


def resolve_temporal_bucket(question: str) -> str:
    """
    Resolves relative temporal expressions in the question to an absolute period string.

    Returns "absoluto" when the question has no relative temporal keyword — meaning
    it is safe to serve the same cached answer regardless of when it was stored.

    Examples (today = 2026-06-09):
      "faturas deste ano"      → "2026"
      "vendas do último mês"   → "2026-05"
      "this quarter"           → "2026-Q2"
      "last week"              → "2026-W23"
      "faturas de janeiro 2024"→ "absoluto"  (absolute date — safe to share)
      "total de clientes"      → "absoluto"
    """
    import re
    from datetime import date, timedelta

    q = question.lower()
    today = date.today()
    y, m = today.year, today.month
    quarter = (m - 1) // 3 + 1

    # Year — includes contractions "deste ano", "neste ano"
    if re.search(
        r"\b(?:(?:d?este|neste)\s+ano|esse\s+ano|this\s+year|ano\s+atual|current\s+year)\b",
        q,
    ):
        return str(y)
    if re.search(r"\b(ano passado|último ano|last year|previous year)\b", q):
        return str(y - 1)

    # Quarter — includes contractions "deste trimestre", "neste trimestre"
    if re.search(
        r"\b(?:(?:d?este|neste)\s+trimestre|esse\s+trimestre|this\s+quarter|trimestre\s+atual|current\s+quarter)\b",
        q,
    ):
        return f"{y}-Q{quarter}"
    if re.search(
        r"\b(trimestre passado|último trimestre|last quarter|previous quarter)\b", q
    ):
        prev_q = quarter - 1 if quarter > 1 else 4
        prev_y = y if quarter > 1 else y - 1
        return f"{prev_y}-Q{prev_q}"

    # Month — includes contractions "deste mês", "neste mês"
    if re.search(
        r"\b(?:(?:d?este|neste)\s+m[êe]s|esse\s+m[êe]s|this\s+month|m[êe]s\s+atual|current\s+month)\b",
        q,
    ):
        return f"{y}-{m:02d}"
    if re.search(r"\b(mês passado|último mês|last month|previous month)\b", q):
        prev_m = m - 1 if m > 1 else 12
        prev_y = y if m > 1 else y - 1
        return f"{prev_y}-{prev_m:02d}"

    # Week — includes contractions "desta semana", "nesta semana"
    iso_week = today.isocalendar()[1]
    if re.search(
        r"\b(?:(?:d?esta|nesta)\s+semana|essa\s+semana|this\s+week|semana\s+atual|current\s+week)\b",
        q,
    ):
        return f"{y}-W{iso_week:02d}"
    if re.search(r"\b(semana passada|última semana|last week|previous week)\b", q):
        prev = today - timedelta(weeks=1)
        pw_y, pw_w, _ = prev.isocalendar()
        return f"{pw_y}-W{pw_w:02d}"

    # Day
    if re.search(r"\b(hoje|today|dia de hoje|current day)\b", q):
        return str(today)
    if re.search(r"\b(ontem|yesterday)\b", q):
        return str(today - timedelta(days=1))

    # Absolute year ("de 2019", "em 2027") — same detection used by periodo_decision
    # Uses "abs-YYYY" prefix to distinguish from relative buckets like "2026" (este ano)
    m_abs = re.search(
        r"\b(?:em|de|do\s+ano|no\s+ano|in(?:\s+the\s+year)?|of|for|from)\s+((?:19|20)\d{2})\b",
        q,
        re.IGNORECASE,
    )
    if m_abs:
        return f"abs-{m_abs.group(1)}"

    return "absoluto"


@router.post("/{connection_id}/query", response_model=QueryResponse)
async def query_connection(
    connection_id: str,
    body: QueryRequest,
    db: AsyncSession = Depends(get_db),
) -> QueryResponse:
    from latency_timing import new_trace

    new_trace(body.thread_id if body.thread_id else None)
    # ✅ SEMANTIC CACHE LAYER (Lookup)
    query_embedding = None
    try:
        from core.llm.factory import create_embedding_provider
        from db.models import SemanticCacheRecord
        from sqlalchemy import text

        # Só fazemos cache para requisições de resposta ou dashboard gerado,
        # desconsiderando vazamentos se houver comandos curtos muito vagos.
        if body.question and len(body.question.strip()) >= 10:
            embed_provider = create_embedding_provider()
            query_embedding = await embed_provider.embed_async([body.question])
            query_embedding = query_embedding[0]

            # FIX 2: Filter semantic cache by crew_id to prevent cross-crew data leakage.
            # - In collaborative mode (crew_ids present): only return records cached for the
            #   same crew (crew_id = active_crew) OR generic personal-mode records (crew_id IS NULL).
            # - In personal mode (no crew restriction): only return records with crew_id IS NULL.
            active_cache_crew = None
            is_personal_cache = getattr(body, "is_personal", True)
            cache_user_id = getattr(body, "user_id", None)
            body_crew_ids = getattr(body, "crew_ids", None) or []
            if not is_personal_cache and len(body_crew_ids) == 1:
                # Exactly one crew = strict collaborative mode; use it for cache isolation
                active_cache_crew = body_crew_ids[0]

            # Resolve the request locale for cache lookup.
            # locale is a categorical dimension — pre-filter in WHERE (not
            # post-retrieval Python) so a valid PT hit is never shadowed by
            # an EN hit that ranks higher in vector similarity.
            #
            # We use resolve_language (same logic as the orchestrator) instead
            # of a plain `body.locale or "en"` fallback.  Plain fallback breaks
            # when body.locale is None and the question is in PT:
            #   body.locale=None + PT question → fallback="en", but
            #   orchestrator detects "pt" → response generated in PT →
            #   stored under "en" → next EN request with locale="en" hits
            #   the PT response.  resolve_language sees no locale and detects
            #   "pt" from the question text — same prediction the orchestrator
            #   will make — so store key and generated language agree.
            from core.i18n.i18n import resolve_language as _resolve_lang

            request_locale = _resolve_lang(
                body.question or "",
                locale=getattr(body, "locale", None),
            )
            _temporal_bucket = resolve_temporal_bucket(body.question or "")
            _CACHE_VERSION = 2  # bump when key schema changes; old rows keep 0

            if active_cache_crew:
                # Collaborative: match records cached for this specific crew.
                # Personal rows (user_id IS NOT NULL) must NOT surface here —
                # they belong to a single user, not the whole crew.
                sql_stmt = """
                    SELECT response_json, (1 - (embedding <=> :query_emb)) AS similarity
                    FROM semantic_cache
                    WHERE connection_id = :conn_id
                    AND (space_id = :space_id OR space_id IS NULL)
                    AND crew_id = :crew_id
                    AND user_id IS NULL
                    AND locale = :locale
                    AND cache_version = :cache_version
                    AND temporal_bucket = :temporal_bucket
                    AND (1 - (embedding <=> :query_emb)) >= 0.95
                    ORDER BY similarity DESC
                    LIMIT 1
                """
                db_res = await db.execute(
                    text(sql_stmt),
                    {
                        "query_emb": str(query_embedding),
                        "conn_id": connection_id,
                        "space_id": body.space_id,
                        "crew_id": active_cache_crew,
                        "locale": request_locale,
                        "cache_version": _CACHE_VERSION,
                        "temporal_bucket": _temporal_bucket,
                    },
                )
            elif is_personal_cache and cache_user_id:
                # Personal: only return records that belong to this user.
                # Without user_id filter, user B's Personal question would
                # return the cached answer computed on user A's private data.
                sql_stmt = """
                    SELECT response_json, (1 - (embedding <=> :query_emb)) AS similarity
                    FROM semantic_cache
                    WHERE connection_id = :conn_id
                    AND user_id = :user_id
                    AND locale = :locale
                    AND cache_version = :cache_version
                    AND temporal_bucket = :temporal_bucket
                    AND (1 - (embedding <=> :query_emb)) >= 0.95
                    ORDER BY similarity DESC
                    LIMIT 1
                """
                db_res = await db.execute(
                    text(sql_stmt),
                    {
                        "query_emb": str(query_embedding),
                        "conn_id": connection_id,
                        "user_id": cache_user_id,
                        "locale": request_locale,
                        "cache_version": _CACHE_VERSION,
                        "temporal_bucket": _temporal_bucket,
                    },
                )
            else:
                # Space mode (no crew, no user): only rows without owner/crew.
                sql_stmt = """
                    SELECT response_json, (1 - (embedding <=> :query_emb)) AS similarity
                    FROM semantic_cache
                    WHERE connection_id = :conn_id
                    AND (space_id = :space_id OR space_id IS NULL)
                    AND crew_id IS NULL
                    AND user_id IS NULL
                    AND locale = :locale
                    AND cache_version = :cache_version
                    AND temporal_bucket = :temporal_bucket
                    AND (1 - (embedding <=> :query_emb)) >= 0.95
                    ORDER BY similarity DESC
                    LIMIT 1
                """
                db_res = await db.execute(
                    text(sql_stmt),
                    {
                        "query_emb": str(query_embedding),
                        "conn_id": connection_id,
                        "space_id": body.space_id,
                        "locale": request_locale,
                        "cache_version": _CACHE_VERSION,
                        "temporal_bucket": _temporal_bucket,
                    },
                )

            cache_row = db_res.first()

            if cache_row:
                cached_json, sim_score = cache_row
                from core.logging_utils import log_event

                log_event(
                    "semantic_cache_hit",
                    {
                        "connection_id": connection_id,
                        "similarity_score": round(sim_score, 4),
                        "original_question": body.question[:50],
                        "crew_id": active_cache_crew,  # for audit
                    },
                )
                cached_response = QueryResponse.model_validate(cached_json)
                # Last-mile: apply format transform + infer widget type from raw cached data
                cached_response.data_sample = _transform_data_for_format(
                    cached_response.data_sample, body.response_format
                )
                cached_response.recommended_widget_type = _infer_widget_type(
                    cached_response.data_sample, body.response_format
                )
                return cached_response
    except Exception as sc_err:
        from core.logging_utils import log_event

        log_event("semantic_cache_lookup_error", {"error": str(sc_err)[:200]})
        # ⚠️ ALARM, not silence: a failing lookup means the cache is DOWN (e.g. a
        # missing column after a schema change). Swallowing this quietly is what
        # let the cache stay dead in prod for months. Surface it at error level.
        logger.error(
            "Semantic cache LOOKUP failed — cache may be DOWN (every query now "
            "pays full LLM+SQL cost): %s",
            str(sc_err)[:300],
        )
        # ✅ FIX: Rollback the session if the cache query failed (e.g. vector type mismatch)
        # Prevents the subsequent inner query from failing with "transaction aborted"
        try:
            await db.rollback()
        except Exception:
            pass

    # ✅ EXECUTE INNER LLM PIPELINE
    response = await _query_connection_inner(connection_id, body, db)

    # ✅ SEMANTIC CACHE LAYER (Store) — always stores raw data_sample (no format transform yet)
    try:
        if (
            query_embedding
            and response.meta
            and getattr(response.meta, "error", None) is None
        ):
            # We don't cache errors from security/language blocks.
            # Store and lookup MUST use the same locale source: the request's
            # target locale (body.locale).  Using detected_language here would
            # create a store/lookup asymmetry — e.g. body.locale=en + PT question
            # → detected=pt → stored under "pt", but next lookup with body.locale=en
            # searches under "en" → eternal miss.  The cache key is the intent
            # (what language the user WANTS the answer in), not the input language.
            _store_locale = (
                request_locale  # same variable used in all three lookups above
            )
            _is_blocked = response.answer and (
                "I'm sorry, but I only support questions" in response.answer
                or unsupported_language_message()[:30] in response.answer
            )
            if response.answer and not _is_blocked:
                cache_record = SemanticCacheRecord(
                    connection_id=connection_id,
                    space_id=body.space_id,
                    crew_id=active_cache_crew,
                    # Personal cache: stamp the owner so future lookups
                    # filter by caller. Non-Personal writes leave this
                    # NULL so the row is shared at Space/Crew scope.
                    user_id=cache_user_id if is_personal_cache else None,
                    question=body.question,
                    embedding=query_embedding,
                    response_json=response.model_dump(mode="json"),
                    locale=_store_locale,
                    cache_version=2,
                    temporal_bucket=_temporal_bucket,
                )
                db.add(cache_record)
                await db.commit()
    except Exception as sc_err:
        from core.logging_utils import log_event

        log_event("semantic_cache_store_error", {"error": str(sc_err)[:200]})
        # ⚠️ ALARM, not silence: a failing store means future identical questions
        # will never hit the cache. Surface it at error level so a dead cache is
        # visible instead of degrading quietly.
        logger.error(
            "Semantic cache STORE failed — answers are not being cached: %s",
            str(sc_err)[:300],
        )
        try:
            await db.rollback()
        except Exception:
            pass

    # Last-mile: apply format transform + infer widget type (runs for both cache miss and pipeline)
    response.data_sample = _transform_data_for_format(
        response.data_sample, body.response_format
    )
    response.recommended_widget_type = _infer_widget_type(
        response.data_sample, body.response_format
    )

    return response


# Cache of profiled categorical values, keyed by "connection|physical|column".
# A value of None marks a column already checked and found high-cardinality, so
# it is never re-queried. Values rarely change, so a process-level cache is
# enough here; the canonical home for this is discover-time enrichment.
_SAMPLE_VALUES_CACHE: Dict[str, Optional[List[str]]] = {}
_SAMPLE_VALUES_MAX_DISTINCT = 25  # only surface low-cardinality columns
_SAMPLE_VALUES_MAX_COLUMNS = 40  # safety cap on profiling work per request


def _is_text_column(col_type: str) -> bool:
    """True for string-like column types across dialects (BigQuery STRING,
    Postgres varchar/text, etc.)."""
    t = (col_type or "").upper()
    return any(k in t for k in ("STR", "CHAR", "TEXT", "VARCHAR", "ENUM"))


def _fetch_distinct_values(
    data_source: Any, physical: str, column: str
) -> Optional[List[str]]:
    """Return distinct non-null values for a column, or None when it is
    high-cardinality (more than the threshold) or unreadable. Source-agnostic:
    runs a bounded SELECT DISTINCT through the DataSource."""
    limit = _SAMPLE_VALUES_MAX_DISTINCT + 1
    sql = (
        f"SELECT DISTINCT {column} AS v FROM {physical} "
        f"WHERE {column} IS NOT NULL LIMIT {limit}"
    )
    try:
        rows = data_source.run_query(sql) or []
    except Exception as exc:
        log_event(
            "sample_values_profile_error",
            {"physical": physical, "column": column, "error": str(exc)[:160]},
        )
        return None
    values = [
        str(r.get("v"))
        for r in rows
        if isinstance(r, dict) and r.get("v") is not None
    ]
    # Too many distinct → not a categorical column; don't surface it.
    if not values or len(values) > _SAMPLE_VALUES_MAX_DISTINCT:
        return None
    return values


def _enrich_tables_with_sample_values(
    tables: list, data_source: Any, connection_id: str
) -> None:
    """Attach the real value domain of low-cardinality text columns to each
    column dict as ``sample_values``, so the schema shown to the LLM lists the
    actual values (e.g. status in {Paid, Pending, Overdue}). This stops the
    model from inventing logic for a value it cannot see (e.g. deriving
    "overdue" from dates instead of using the status column).

    Best-effort and cached per (connection, table, column); high-cardinality
    columns are remembered as skipped. Any failure leaves the column
    unannotated and never breaks the query path.
    """
    profiled = 0
    for table in tables or []:
        physical = getattr(table, "physical_name", None)
        if not physical:
            continue
        for col in getattr(table, "columns", None) or []:
            if not isinstance(col, dict):
                continue
            name = col.get("name")
            if not name or col.get("sample_values") is not None:
                continue
            if not _is_text_column(col.get("type") or col.get("data_type") or ""):
                continue
            key = f"{connection_id}|{physical}|{name}"
            if key in _SAMPLE_VALUES_CACHE:
                cached = _SAMPLE_VALUES_CACHE[key]
                if cached:
                    col["sample_values"] = cached
                continue
            if profiled >= _SAMPLE_VALUES_MAX_COLUMNS:
                continue
            profiled += 1
            values = _fetch_distinct_values(data_source, physical, name)
            _SAMPLE_VALUES_CACHE[key] = values
            if values:
                col["sample_values"] = values


async def _query_connection_inner(
    connection_id: str,
    body: QueryRequest,
    db: AsyncSession = Depends(get_db),
) -> QueryResponse:
    """
    Faz uma pergunta usando uma DataConnection diretamente.

    Requisitos:
    - A conexão deve ter metadados descobertos (execute /discover primeiro)
    - O space_id no body deve corresponder ao space_id da conexão

    Exemplo de uso:
    ```json
    {
        "question": "Qual é a performance de pageviews mensal?",
        "user_id": "user-123",
        "space_id": "00000000-0000-0000-0000-000000000001",
        "thread_id": "thread-456"
    }
    ```
    """
    # Medir tempo de execução para auditoria
    import time

    start_time = time.time()

    if not body.space_id:
        raise HTTPException(
            status_code=400, detail="space_id é obrigatório no body da requisição"
        )

    # ✅ CAMADA 1: Rate limiting
    user_key = body.user_id or f"conn_{connection_id}"
    allowed, error = _rate_limiter.check_rate_limit(user_key, "query")
    was_rate_limited = not allowed
    if not allowed:
        # Auditoria: rate limited
        log_query_audit(
            connection_id=connection_id,
            user_id=body.user_id,
            space_id=body.space_id,
            crew_ids=body.crew_ids,
            thread_id=body.thread_id,
            question=body.question,
            was_rate_limited=True,
        )
        raise HTTPException(status_code=429, detail=error)

    # ✅ CAMADA DE SEGURANÇA UNIFICADA (Audit Manager)
    from core.security.audit_manager import AuditManager
    from core.llm.factory import create_llm_orchestrator
    from core.i18n.i18n import detect_language, get_message

    # Criar provider LLM para avaliação de segurança
    llm_provider = create_llm_orchestrator()

    # Avaliação consolidada: PII + Injection + Escalation + Auditoria
    security_report = await AuditManager.evaluate_prompt(
        question=body.question,
        user_id=body.user_id,
        connection_id=connection_id,
        thread_id=body.thread_id,
        llm_provider=llm_provider,
    )

    # Detectar idioma para validação
    try:
        lang = detect_language(body.question or "")
    except:
        lang = "en"

    # Se houver bloqueio, interromper e retornar erro padronizado com mensagem amigável
    if security_report.is_blocked:
        # Mensagens amigáveis por tipo de bloqueio
        if security_report.blocked_by == "PII_SCANNER":
            message = get_message("PII_BLOCKED", lang)
            error_code = "pii_prompt_blocked"
        else:
            message = get_message("SECURITY_BLOCKED", lang)
            error_code = "security_blocked"

        # Auditoria legada (mantém compatibilidade com dashboards existentes)
        esc_info = security_report.scan_details.get("escalation", {})
        log_query_audit(
            connection_id=connection_id,
            user_id=body.user_id,
            space_id=body.space_id,
            crew_ids=body.crew_ids,
            thread_id=body.thread_id,
            question=security_report.redacted_prompt,
            pii_detected_in_prompt=(security_report.blocked_by == "PII_SCANNER"),
            pii_blocked=(security_report.blocked_by == "PII_SCANNER"),
            prompt_injection_detected=(security_report.blocked_by == "SECURITY_GUARD"),
            progressive_escalation_detected=(
                security_report.blocked_by == "PROGRESSIVE_ESCALATION"
            ),
            progressive_escalation_score=int(esc_info.get("score", 0)),
        )

        return QueryResponse(
            answer=message,
            data_sample=[],
            meta=QueryResultMeta(
                detected_language=lang,
                chosen_table=None,
                chosen_datasets=None,
                sql=None,
                num_rows=0,
                error=error_code,
            ),
        )

    # ✅ LANGUAGE GUARDRAIL (EN + PT) — locale-aware + mensagem bilíngue.
    # A estabilidade por thread é aplicada de forma autoritativa no orchestrator;
    # aqui só bloqueamos o caso claro: sem locale + detecção confiante de idioma
    # não suportado. Um locale suportado evita o bloqueio.
    _blocked, _ = language_decision(
        body.question or "", locale=getattr(body, "locale", None)
    )
    if _blocked:
        try:
            log_event(
                "query_blocked_language",
                {
                    "connection_id": connection_id,
                    "user_id": body.user_id,
                    "detected_language": lang,
                    "question": body.question[:200],
                },
            )
        except Exception:
            pass

        return QueryResponse(
            answer=unsupported_language_message(),
            data_sample=[],
            meta=QueryResultMeta(
                detected_language=lang,
                chosen_table=None,
                chosen_datasets=None,
                sql=None,
                num_rows=0,
                error="language_not_supported",
            ),
        )

    # Variáveis para compatibilidade com o resto da função
    pii_detected_in_prompt = (
        security_report.security_status == "FLAGGED"
        or "pii" in security_report.scan_details
    )
    prompt_injection_detected = False
    prompt_injection_pattern = None

    # ✅ FIM DA CAMADA DE SEGURANÇA UNIFICADA
    pii_detected_in_response = False

    pii_blocked = False
    thread_id = body.thread_id or f"{body.user_id or 'anon'}-{connection_id}"
    esc_info = security_report.scan_details.get("escalation", {})
    escalation_score = esc_info.get("score", 0.0)
    escalation_detected = (
        security_report.blocked_by == "PROGRESSIVE_ESCALATION"
        or security_report.security_status == "FLAGGED"
    )
    escalation_reason = esc_info.get("reason")

    # ✅ DASHBOARD INTENT DETECTION (Step 1.2)
    # Check if user wants direct dashboard generation instead of text answer
    from core.intent.detector import DashboardIntentDetector

    intent_detector = DashboardIntentDetector()
    is_dashboard_request = intent_detector.detect(body.question)

    if is_dashboard_request:
        # Log intent detection
        log_event(
            "dashboard_intent_detected",
            {
                "connection_id": connection_id,
                "user_id": body.user_id,
                "question": body.question[:200],
                "thread_id": thread_id,
            },
        )

        # ✅ DASHBOARD DIRECT GENERATION (Step 1.3)
        # Route to dashboard generation instead of normal query flow
        try:
            # Load table metadata for dashboard generation
            tables = await _load_connection_metadata_tables(
                db=db, connection_id=connection_id
            )
            tables = await _enrich_tables_with_ai_metadata(
                db=db, connection_id=connection_id, tables=tables
            )

            # Resolve crew_ids
            resolved_crew_ids = []
            if body.user_id:
                try:
                    from uuid import UUID

                    resolved = await resolve_crew_ids_for_context(
                        db=db,
                        user_id=UUID(body.user_id),
                        space_id=UUID(body.space_id) if body.space_id else None,
                        request_crew_ids=body.crew_ids,
                        is_personal=getattr(body, "is_personal", False),
                    )
                    resolved_crew_ids = [str(x) for x in (resolved or [])]
                except Exception as e:
                    log_event("dashboard_direct_resolve_crew_error", {"error": str(e)})

            # FIX 4: Apply crew-level permission filter in collaborative mode.
            # Previously the dashboard intent flow loaded all tables without filtering by crew.
            is_collab = not getattr(body, "is_personal", False)
            if is_collab and resolved_crew_ids:
                tables = await _filter_tables_by_permissions(
                    db=db,
                    connection_id=connection_id,
                    space_id=body.space_id,
                    tables=tables,
                    crew_ids=resolved_crew_ids,
                    strict_mode=True,  # fail-closed in collaborative mode
                )
                log_event(
                    "dashboard_direct_tables_filtered_by_crew",
                    {
                        "connection_id": connection_id,
                        "crew_ids": resolved_crew_ids,
                        "num_tables_after_filter": len(tables),
                    },
                )

            # Generate schema summary
            max_tables_in_prompt = min(30, len(tables))
            logical_tables, schema_summary = _schema_summary_from_tables(
                tables, max_tables=max_tables_in_prompt
            )

            # Create LLM for Davinci
            llm = create_llm_specialist(creativity=10, length=35)

            # Generate dashboard plan using Davinci
            plan = await asyncio.to_thread(
                generate_dashboard_plan,
                llm=llm,
                goal=body.question,  # Use question as goal
                language=lang,
                max_widgets=8,  # Default to 8 widgets for direct requests
                logical_tables=logical_tables,
                schema_summary=schema_summary,
                original_question=None,  # No prior question
                initial_ai_response=None,  # Direct request, no prior answer
                context_spaces=None,
                context_crews=None,
                context_tables=None,
                table_metadata=tables,
                analysis_context=None,
            )

            # Return dashboard plan as QueryResponse with special meta
            log_event(
                "dashboard_direct_generation_success",
                {
                    "connection_id": connection_id,
                    "user_id": body.user_id,
                    "num_widgets": len(plan.widgets),
                    "dashboard_name": plan.dashboard_name,
                },
            )

            # Format dashboard plan as answer (frontend will handle rendering)
            if lang == "pt":
                loading_message = (
                    f'Seu dashboard "{plan.dashboard_name}" está sendo criado.\n\n'
                    f"Estamos analisando os dados para gerar {len(plan.widgets)} insights relevantes — isso levará apenas um momento."
                )
            else:
                loading_message = (
                    f'Your dashboard "{plan.dashboard_name}" is being created.\n\n'
                    f"We are analyzing the data to generate {len(plan.widgets)} relevant insights — this will take just a moment."
                )

            return QueryResponse(
                answer=loading_message,
                data_sample=[],
                meta=QueryResultMeta(
                    detected_language=lang,
                    chosen_table=None,
                    chosen_datasets=None,
                    sql=None,
                    num_rows=0,
                    error=None,
                    # ✅ NEW: Dashboard metadata for frontend
                    dashboard_plan={
                        "dashboard_name": plan.dashboard_name,
                        "description": plan.description,
                        "widgets": plan.widgets,
                        "meta": plan.meta or {},
                        "is_direct_generation": True,  # Flag for frontend
                    },
                ),
            )

        except Exception as e:
            log_event(
                "dashboard_direct_generation_error",
                {
                    "connection_id": connection_id,
                    "user_id": body.user_id,
                    "error": str(e),
                    "question": body.question[:200],
                },
            )
            # Fall back to normal query flow on error
            log_event("dashboard_direct_fallback_to_normal_query", {"reason": str(e)})

    # Continue with normal query flow if not dashboard request or if generation failed
    # Verificar se conexão existe
    result = await db.execute(
        # Usar connector_id como alias para type para ser compatível com schemas antigos
        text(
            "SELECT id, name, connector_id AS type, config FROM data_connections WHERE id = :id"
        ),
        {"id": connection_id},
    )
    conn_result = result.first()

    if not conn_result:
        raise HTTPException(
            status_code=404, detail=f"Conexão {connection_id} não encontrada"
        )

    # Resolver crew_ids do usuário baseado no contexto (personal vs collaborative)
    crew_ids = body.crew_ids or []
    if body.user_id:
        try:
            from uuid import UUID

            u_id = (
                UUID(body.user_id) if body.user_id and len(body.user_id) == 36 else None
            )
            s_id = (
                UUID(body.space_id)
                if body.space_id and len(body.space_id) == 36
                else None
            )

            resolved_crew_ids = await resolve_crew_ids_for_context(
                db=db,
                user_id=u_id,
                space_id=s_id,
                request_crew_ids=body.crew_ids,
                is_personal=getattr(body, "is_personal", False),
            )
            crew_ids = [str(crew_id) for crew_id in resolved_crew_ids]
            log_event(
                "api_query_connection_resolved_crew_ids",
                {
                    "connection_id": connection_id,
                    "user_id": body.user_id,
                    "space_id": body.space_id,
                    "is_personal": getattr(body, "is_personal", False),
                    "resolved_crew_ids": crew_ids,
                },
            )
        except Exception as e:
            log_event(
                "api_query_connection_resolve_crew_ids_error",
                {
                    "connection_id": connection_id,
                    "user_id": body.user_id,
                    "space_id": body.space_id,
                    "error": str(e),
                },
            )
            # Se falhar ao resolver, usar lista vazia (apenas dados públicos)
            crew_ids = []

    # Carregar AgentConfig automaticamente com filtro de permissões
    try:
        agent_config = await load_agent_config_from_connection(
            db=db,
            space_id=body.space_id,
            connection_id=connection_id,
            crew_ids=crew_ids if crew_ids else None,
            authorized_tables=body.authorized_tables,
            connection_ids=body.connection_ids or None,
            space_ids=getattr(body, "space_ids", None) or None,
        )

        log_event(
            "api_query_connection_agent_config_loaded",
            {
                "connection_id": connection_id,
                "space_id": body.space_id,
                "user_id": body.user_id,
                "crew_ids": crew_ids,
                "agent_id": agent_config.id,
                "num_tables": len(agent_config.tables),
                "has_tables": len(agent_config.tables) > 0,
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        log_event(
            "api_query_connection_agent_config_error",
            {
                "connection_id": connection_id,
                "space_id": body.space_id,
                "error": str(e),
                "error_type": type(e).__name__,
            },
        )
        raise HTTPException(
            status_code=500, detail=f"Erro ao carregar configuração do agente: {str(e)}"
        )

    # Carregar relacionamentos documentados pelo cliente (explicit_relationships)
    # Filtrados pelas tabelas que o usuário tem acesso (segurança em camada)
    explicit_relationships: List[dict] = []
    try:
        allowed_logical_names = [t.logical_name for t in agent_config.tables]
        explicit_relationships = await _load_connection_relationships(
            db=db,
            connection_id=connection_id,
            allowed_logical_names=allowed_logical_names,
        )
        log_event(
            "api_query_explicit_relationships",
            {
                "connection_id": connection_id,
                "count": len(explicit_relationships),
            },
        )
    except Exception as e:
        # Fail-safe: se falhar ao carregar, continua sem relacionamentos explícitos
        log_event(
            "api_query_explicit_relationships_error",
            {"connection_id": connection_id, "error": str(e)[:200]},
        )
        explicit_relationships = []

    # Fast-path answers for catalog questions (avoid LLM/SQL for simple metadata requests).
    # This makes the UX consistent in both Portuguese and English.
    try:
        import re

        q_raw = (body.question or "").strip()
        q = q_raw.lower()
        tables = agent_config.tables or []
        logical_tables = [
            t.logical_name for t in tables if getattr(t, "logical_name", None)
        ]

        is_tables_question = bool(
            re.search(
                r"(\bwhat\b.*\btables?\b)|"
                r"(\bwhich\b.*\btables?\b)|"
                r"(\blist\b.*\btables?\b)|"
                r"(\bavailable\b.*\btables?\b)",
                q,
                flags=re.IGNORECASE,
            )
        )

        is_examples_question = bool(
            re.search(
                r"(\bexamples?\b.*\bquestions?\b)|"
                r"(\bexample\b.*\bquestions?\b)|"
                r"(\bwhat can i ask\b)",
                q,
                flags=re.IGNORECASE,
            )
        )

    except Exception:
        # Never fail the main query path due to these heuristics.
        pass

    # Criar DataSource da conexão
    class TempDataConnection:
        def __init__(self, id, name, type, config):
            self.id = id
            self.name = name
            self.type = type
            self.config = (
                config
                if isinstance(config, dict)
                else json.loads(config) if isinstance(config, str) else {}
            )

    # Parse config safely
    conn_config = conn_result[3]
    if isinstance(conn_config, str):
        try:
            conn_config = json.loads(conn_config)
        except json.JSONDecodeError:
            conn_config = {}
    elif conn_config is None:
        conn_config = {}
    elif not isinstance(conn_config, dict):
        conn_config = {}

    # Backend stores config encrypted as {"__encrypted": "..."}; decrypt
    # with the shared ENCRYPTION_KEY before the factory tries to read
    # host/port/user/password. No-op when already plaintext.
    from core.security.config_decryption import decrypt_config

    conn_config = decrypt_config(conn_config)

    data_conn = TempDataConnection(
        id=str(conn_result[0]),
        name=conn_result[1],
        type=conn_result[2] or "bigquery",
        config=conn_config,
    )

    try:
        data_source = DataSourceFactory.build_from_dataconnection(data_conn)
    except Exception as e:
        import traceback

        error_detail = f"Erro ao criar DataSource: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=error_detail)

    # Surface the real value domain of low-cardinality text columns (status,
    # category, method, ...) so the specialist maps business terms to actual
    # column values instead of inventing logic (e.g. date heuristics). Cached,
    # best-effort — never blocks the query.
    try:
        _enrich_tables_with_sample_values(
            agent_config.tables, data_source, connection_id
        )
    except Exception as _exc:
        logger.warning("sample-value enrichment skipped: %s", _exc)

    # For scan mode: build multi-source dispatch_map so the full_context_agent
    # can query any of the user's connections, not just the primary one.
    dispatch_map: Optional[dict] = None
    if getattr(body, "agent_mode", None) == "scan":
        _scan_space_ids = getattr(body, "space_ids", None) or (
            [body.space_id] if body.space_id else []
        )
        if _scan_space_ids:
            try:
                dispatch_map = await _build_dispatch_map_for_scan(db, _scan_space_ids)
            except Exception as _exc:
                logger.warning("Failed to build scan dispatch_map: %s", _exc)

        # Personal mode: merge tables from ALL connections so the agent sees
        # the full data landscape, not just the primary connection's tables.
        if dispatch_map and getattr(body, "is_personal", False):
            try:
                agent_config = await _build_merged_agent_config_for_scan(
                    db=db,
                    dispatch_map=dispatch_map,
                    space_ids=_scan_space_ids,
                    crew_ids=crew_ids if crew_ids else None,
                    base_config=agent_config,
                )
                log_event(
                    "scan_merged_agent_config_applied",
                    {
                        "connection_id": connection_id,
                        "num_tables": len(agent_config.tables),
                    },
                )
            except Exception as _exc:
                logger.warning("Failed to build merged agent config for scan: %s", _exc)

    # Collaborative cross-connection: when the loaded tables span more than one
    # connection (caller passed body.connection_ids), build a dispatch_map so the
    # specialist runs one sub-query per source and the orchestrator's merger
    # (DuckDB) consolidates them. Without this, is_multi_source stays False and
    # every table is queried against the primary connection only.
    if dispatch_map is None:
        table_conn_ids = {
            str(getattr(t, "data_connection_id", "") or "")
            for t in agent_config.tables
        }
        table_conn_ids.discard("")
        if len(table_conn_ids) > 1:
            try:
                dispatch_map = await _build_dispatch_map_for_connections(
                    db, sorted(table_conn_ids)
                )
            except Exception as _exc:
                logger.warning(
                    "Failed to build cross-connection dispatch_map: %s", _exc
                )

    # DatasetPriorityScorer: rank all tables and keep top-K most valuable ones
    # before handing the config to the agent (roadmap items 13-14).
    # Every CROSS_DATASET_EVERY_N runs, use cross_dataset_rank() to force
    # one table per connection and explore cross-source correlations (item 15).
    _is_cross_dataset_run = False
    if getattr(body, "agent_mode", None) == "scan" and agent_config.tables:
        try:
            from core.agents.dataset_priority_scorer import (
                CROSS_DATASET_EVERY_N,
                DatasetPriorityScorer,
                load_insights_for_scorer,
                load_okr_embeddings_for_scorer,
                load_dataset_embeddings_for_scorer,
                load_row_count_snapshots_for_scorer,
                save_row_count_snapshots,
            )
            from core.agents.scan_briefing import count_scan_insights
            from core.agents.depth_tracker import load_depth_combos_for_scorer

            _raw_insights = await load_insights_for_scorer(db, body.space_id)
            _run_count = await count_scan_insights(db, body.space_id)
            _is_cross_dataset_run = _run_count > 0 and (
                _run_count % CROSS_DATASET_EVERY_N == 0
            )

            # Items 17-18: load embeddings for cosine relevance scoring
            _okr_vectors = await load_okr_embeddings_for_scorer(db, body.space_id)
            _dataset_embeddings = await load_dataset_embeddings_for_scorer(
                db, body.space_id
            )
            _using_cosine = bool(_okr_vectors and _dataset_embeddings)

            # Item 20: load row_count snapshots for volatility scoring
            _row_count_snapshots = await load_row_count_snapshots_for_scorer(
                db, body.space_id
            )

            # Item 34: load explored depth combos for real depth scoring
            _depth_combos = await load_depth_combos_for_scorer(db, body.space_id)

            _scorer = DatasetPriorityScorer(
                brain_context="",
                top_k=5,
                okr_vectors=_okr_vectors,
                dataset_embeddings=_dataset_embeddings,
                row_count_snapshots=_row_count_snapshots,
                depth_combos=_depth_combos,
            )
            if _is_cross_dataset_run:
                _top_tables = _scorer.cross_dataset_rank(
                    agent_config.tables, _raw_insights
                )
            else:
                _top_tables = _scorer.rank(agent_config.tables, _raw_insights)

            if _top_tables:
                _breakdown = _scorer.score_breakdown(agent_config.tables, _raw_insights)
                logger.debug(
                    "DatasetPriorityScorer breakdown:\n%s",
                    "\n".join(f"  {s}" for s in _breakdown),
                )
                log_event(
                    "scan_dataset_priority_applied",
                    {
                        "space_id": body.space_id,
                        "total_tables": len(agent_config.tables),
                        "top_k_tables": [t.logical_name for t in _top_tables],
                        "num_insights": len(_raw_insights),
                        "run_count": _run_count,
                        "is_cross_dataset_run": _is_cross_dataset_run,
                        "using_cosine_relevance": _using_cosine,
                        "num_okr_vectors": len(_okr_vectors),
                        "num_dataset_embeddings": len(_dataset_embeddings),
                        "num_row_count_snapshots": len(_row_count_snapshots),
                        "num_depth_tracked_tables": len(_depth_combos),
                    },
                )

                # Item 20: persist row_count snapshot for all candidate tables
                # (all tables, not just top-K, so volatility history is complete)
                await save_row_count_snapshots(db, body.space_id, agent_config.tables)

                agent_config = AgentConfig(
                    id=agent_config.id,
                    name=agent_config.name,
                    tables=_top_tables,
                    dialect=agent_config.dialect,
                    extra=agent_config.extra,
                )
        except Exception as _exc:
            logger.warning("DatasetPriorityScorer failed, using all tables: %s", _exc)

    # Build scan briefing (direction for the proactive agent)
    scan_briefing = ""
    if getattr(body, "agent_mode", None) == "scan":
        try:
            from core.agents.scan_briefing import prepare_scan_briefing

            scan_briefing = await prepare_scan_briefing(
                db=db,
                space_id=body.space_id,
                user_id=getattr(body, "user_id", None),
                llm=create_llm_orchestrator(creativity=10, length=10),
                brain_context="",  # brain_context fetched inside agent; empty here is fine
                table_count=len(agent_config.tables),
                is_cross_dataset=_is_cross_dataset_run,
            )
        except Exception as _exc:
            logger.warning("Failed to build scan briefing: %s", _exc)

    # LLMs usando factory centralizado
    try:
        llm_orchestrator = create_llm_orchestrator()
        llm_specialist = create_llm_specialist()
        llm_formatter = create_llm_formatter()

        # Provider de embeddings (RAG) usando factory centralizado
        embedding_provider = create_embedding_provider()
    except Exception as e:
        log_event(
            "llm_factory_init_error",
            {
                "connection_id": connection_id,
                "error": str(e),
            },
        )
        # Retornar erro amigável em vez de 500 cru
        return QueryResponse(
            answer="I'm having trouble initializing my language models right now. Please execute a system check or contact support.",
            data_sample=[],
            meta=QueryResultMeta(
                detected_language=lang, error="llm_init_error", num_rows=0
            ),
        )

    # Buscar contexto RAG com crew_ids resolvidos.
    # Personal isolation: is_personal + user_id garantem que o RAG só
    # devolve embeddings que pertencem ao caller quando em Personal, e
    # exclui Personal de terceiros quando em Space/Crew.
    retrieval_context: list[str] = []
    knowledge_citations: list = []
    try:
        # Flatten selected_context (Universe-Intelligence pinning from
        # the agent, when present) into the allowlist the brain path
        # consumes. Empty flatten = no filter.
        _sel_ctx = getattr(body, "selected_context", None) or {}
        _allowed_doc_ids = [
            str(_id) for ids in _sel_ctx.values() if ids for _id in ids
        ] or None
        retrieval_context, knowledge_citations = (
            await build_retrieval_context_for_question(
                db=db,
                embedding_provider=embedding_provider,
                space_id=body.space_id,
                crew_ids=crew_ids if crew_ids else None,
                question=body.question,
                top_k=10,
                connection_id=connection_id,
                is_personal=bool(getattr(body, "is_personal", False)),
                user_id=getattr(body, "user_id", None),
                allowed_document_ids=_allowed_doc_ids,
                mentioned_file_ids=getattr(body, "mentioned_file_ids", None),
                caller_space_ids=getattr(body, "space_ids", None),
                authorized_tables=body.authorized_tables,
            )
        )
    except Exception:
        # Se RAG falhar, continua sem contexto
        retrieval_context = []
        knowledge_citations = []

    # ==================== MEMORY: LOADING CHAT HISTORY ====================
    # Initialize thread_id if missing (e.g. for anonymous/new interactions)
    # The 'thread_id' connects this query to previous ones.
    query_thread_id = body.thread_id
    if not query_thread_id and body.user_id:
        query_thread_id = f"{body.user_id}-{connection_id}"

    chat_history_list = []
    if query_thread_id:
        try:
            # Load last 10 messages for this thread
            hist_stmt = (
                select(ChatHistory)
                .where(ChatHistory.thread_id == query_thread_id)
                .order_by(desc(ChatHistory.created_at))
                .limit(10)
            )
            hist_result = await db.execute(hist_stmt)
            # Reverse to chronological order (oldest first)
            recent_msgs = hist_result.scalars().all()[::-1]

            chat_history_list = [
                {"role": msg.role, "content": msg.content} for msg in recent_msgs
            ]
        except Exception as e:
            logger.error(f"Error loading chat history: {e}")
            chat_history_list = []

    # Create User object (required by UserContext)
    # Use body user_id or random UUID if missing
    import uuid

    raw_uid = body.user_id
    if raw_uid:
        try:
            u_id = (
                uuid.UUID(str(raw_uid))
                if not isinstance(raw_uid, uuid.UUID)
                else raw_uid
            )
        except (ValueError, AttributeError):
            # user_id não é UUID válido — gerar um determinístico a partir da string
            u_id = uuid.uuid5(uuid.NAMESPACE_OID, str(raw_uid))
    else:
        u_id = uuid.uuid4()

    mock_user = User(
        id=u_id,
        email="mock@example.com",  # Placeholder
        name="Mock User",  # Placeholder
        is_active=True,
    )

    # Create UserContext object
    mock_user_ctx = UserContext(
        user=mock_user,
        space_id=body.space_id,
        crew_ids=crew_ids,
        platform_role=getattr(body, "platform_role", None) or "user",
        crew_role=getattr(body, "crew_role", None) or "guest",
        locale=getattr(body, "locale", None),
        permissions=getattr(body, "permissions", None) or [],
        # security_config removed (not in UserContext schema)
    )

    # 🏃 EXECUÇÃO: Roda o agente (graph) DE FORMA SÍNCRONA (em thread separada para não bloquear loop)
    # O grafo monta o plano, gera SQL e formata a resposta.
    try:
        final_state = await asyncio.to_thread(
            run_agent_once,
            question=body.question,
            user_ctx=mock_user_ctx,  # Contexto montado acima
            agent_config=agent_config,
            data_source=data_source,
            # Tenant-aware sync session for the LangGraph agent (Model B).
            # asyncio.to_thread propagates the tenant contextvar into the
            # worker thread, so sync_session_for() routes the agent's RAG /
            # checkpoint reads to the tenant DB; falls back to the global
            # sync session for the default context.
            db_session_factory=lambda: tenant_connection_manager.sync_session_for(),
            embedding_provider=embedding_provider,
            llm_orchestrator=llm_orchestrator,
            llm_specialist=llm_specialist,
            llm_formatter=llm_formatter,
            thread_id=query_thread_id,
            retrieval_context=retrieval_context,
            chat_history=chat_history_list,
            instructions=body.instructions,
            creativity=body.creativity,
            length=body.length,
            response_format=body.response_format,
            ai_tone=body.ai_tone,
            ai_style=body.ai_style,
            sql_instructions=body.sql_instructions,
            selected_datasets=body.selected_datasets,
            explicit_relationships=explicit_relationships or None,
            agent_mode=getattr(body, "agent_mode", None),
            dispatch_map=dispatch_map,
            briefing=scan_briefing,
        )
    except Exception as e:
        import traceback

        # Same empty-stringification trap as the backend: `str(e)` can be ""
        # for bare Exception()/custom exceptions with no message. Fall back to
        # repr(e) and finally the exception class name so error_detail is never
        # blank (otherwise the audit log + backend surface "Error: " with no
        # signal about what actually failed).
        error_detail = str(e).strip() or repr(e).strip() or type(e).__name__
        logger.error(
            f"Erro ao executar agente: {error_detail}\n{traceback.format_exc()}"
        )

        # Auditoria de erro
        log_query_audit(
            connection_id=connection_id,
            user_id=body.user_id,
            space_id=body.space_id,
            crew_ids=crew_ids,
            thread_id=thread_id,
            platform_role=getattr(body, "platform_role", None) or "user",
            crew_role=getattr(body, "crew_role", None) or "guest",
            question=body.question,
            has_error=True,
            error_message=error_detail,
        )

        return QueryResponse(
            answer=get_message("TECHNICAL_ERROR", lang),
            data_sample=[],
            meta=QueryResultMeta(
                detected_language=lang, error="technical_error", num_rows=0
            ),
        )

    # ==================== MEMORY: SAVING CHAT HISTORY ====================
    # Persist the interaction (User Q + AI A) asynchronously
    if query_thread_id:
        try:
            # Ensure clean transaction state — previous operations (semantic cache,
            # audit flush, etc.) may have left the transaction aborted.
            try:
                await db.rollback()
            except Exception:
                pass

            # Save User Message
            user_msg = ChatHistory(
                thread_id=query_thread_id, role="user", content=body.question
            )
            db.add(user_msg)

            # Save AI Response
            # Only save if there's a meaningful answer
            ai_text = final_state.get("answer")
            if ai_text:
                ai_msg = ChatHistory(
                    thread_id=query_thread_id,
                    role="assistant",
                    content=ai_text,
                    extra={
                        "sql": final_state.get("sql"),
                        "generated_title": final_state.get("generated_title"),
                    },
                )
                db.add(ai_msg)

            await db.commit()
        except Exception as e:
            logger.error(f"Error saving chat history: {e}")
            try:
                await db.rollback()
            except Exception:
                pass

    # Persist scan insight + notify (items 25-26, 33)
    _scan_silent: bool = True
    _scan_insight_title: Optional[str] = None
    if getattr(body, "agent_mode", None) == "scan" and final_state.get("answer"):
        from config.settings import settings as _settings

        _insight_text = final_state.get("answer", "")
        _is_silent = len(_insight_text.strip()) < _settings.scan_min_insight_length
        _scan_silent = _is_silent
        if not _is_silent:
            try:
                from core.agents.scan_briefing import (
                    save_scan_insight,
                    is_semantic_duplicate,
                )

                _title = _insight_text[:80].split("\n")[0].strip("# ").strip()
                _scan_insight_title = _title

                # Item 33: embed the insight and suppress if semantically duplicate
                _insight_embedding: Optional[list] = None
                try:
                    _embed_vecs = await embedding_provider.embed_async(
                        [_insight_text[:2000]]
                    )
                    _insight_embedding = _embed_vecs[0] if _embed_vecs else None
                except Exception as _emb_exc:
                    logger.debug(
                        "scan insight embed failed (non-critical): %s", _emb_exc
                    )

                if _insight_embedding:
                    _is_dup = await is_semantic_duplicate(
                        db=db,
                        space_id=body.space_id,
                        embedding_vec=_insight_embedding,
                        threshold=0.85,
                    )
                    if _is_dup:
                        _scan_silent = True
                        logger.debug(
                            "scan insight suppressed: semantic duplicate detected"
                        )

                if not _scan_silent:
                    await save_scan_insight(
                        db=db,
                        space_id=body.space_id,
                        user_id=getattr(body, "user_id", None),
                        text_content=_insight_text,
                        title=_title,
                        tables_queried=final_state.get("tables_queried") or [],
                        embedding=_insight_embedding,
                    )
                    # Notify backend so connected users receive a push notification
                    try:
                        from core.clients.backend_client import get_backend_client

                        get_backend_client().notify_scan_insight(
                            space_id=body.space_id,
                            title=_title,
                            summary=_insight_text[:500],
                        )
                    except Exception as _notify_exc:
                        logger.debug(
                            "notify_scan_insight failed (non-critical): %s", _notify_exc
                        )
            except Exception as _exc:
                logger.warning("Failed to save scan insight: %s", _exc)

        # Item 34: record explored (dimension × metric) combos for depth tracking.
        # Runs regardless of whether the insight was saved or marked silent.
        # For regular queries: uses final_state["sql"] (LangGraph specialist node).
        # For scan mode (full_context_agent): uses final_state["executed_sqls"]
        # — a list of every SQL run by query_table during the ReAct loop.
        try:
            from core.agents.depth_tracker import (
                extract_explored_combos,
                record_depth_combos,
            )

            _scan_tables = final_state.get("tables_queried") or []
            _sqls_to_track: list = []
            _single_sql = final_state.get("sql") or ""
            if _single_sql:
                _sqls_to_track = [_single_sql]
            else:
                _sqls_to_track = final_state.get("executed_sqls") or []

            if _sqls_to_track and _scan_tables:
                _all_combos: set = set()
                for _s in _sqls_to_track:
                    _all_combos |= extract_explored_combos(_s)
                if _all_combos:
                    for _tbl in _scan_tables:
                        await record_depth_combos(
                            db=db,
                            space_id=body.space_id,
                            table_name=_tbl,
                            combos=_all_combos,
                        )
        except Exception as _depth_exc:
            logger.debug("depth_tracker record failed (non-critical): %s", _depth_exc)

    answer = final_state.get("answer") or ""
    data = final_state.get("data") or []

    # ✅ CORREÇÃO ARROW: Converter pyarrow.Table para lista de dicts
    # ✅ CORREÇÃO ARROW: Converter pyarrow.Table para lista de dicts
    # A conversão DEVE acontecer imediatamente aqui para garantir que loggers e PII funcionem
    try:
        import pyarrow as pa

        # Verifica se é Table ou se tem método to_pylist (caso o isinstance falhe por reload de modulo)
        if isinstance(data, pa.Table) or hasattr(data, "to_pylist"):
            # Apenas converte se tiver to_pylist
            if hasattr(data, "to_pylist"):
                data = data.to_pylist()
            else:
                # Fallback muito improvável, mas seguro
                data = [row.as_py() for row in data]
    except Exception as e:
        print(f"ERROR converting Arrow data: {e}")
        # Se falhar, tenta manter o que tem ou vazio se for inusável
        if not isinstance(data, list):
            data = []
    detected_language = final_state.get("detected_language")
    chosen_table = final_state.get("chosen_table")
    chosen_tables = final_state.get("chosen_tables")  # List of tables (new)
    sql = final_state.get("sql")
    error = final_state.get("error")

    # ✅ CAMADA 3: Validação AST do SQL gerado
    # Multi-source results carry the DuckDB merger SQL (over in-memory datasets
    # like dataset_1/dataset_2), not a connection query. Each per-source
    # sub-query was already validated against its own source, so re-checking the
    # merge SQL against this connection's tables would wrongly reject it.
    if sql and not final_state.get("is_multi_source"):
        # Obter tabelas permitidas (usar physical_name porque SQL usa physical)
        allowed_tables = [t.physical_name for t in agent_config.tables]
        # Também adicionar logical_name para compatibilidade
        allowed_tables.extend([t.logical_name for t in agent_config.tables])

        # Obter tipo de conexão
        connection_type = conn_result[2] or "bigquery"

        validator = AdvancedSQLValidator(
            allowed_tables=allowed_tables,
            allowed_columns=None,  # Opcional: filtrar colunas também
            max_limit=5000,
            max_columns=50,
            max_group_by=10,
        )

        is_valid, validation_error = validator.validate(sql, connection_type)
        if not is_valid:
            log_event(
                "ai_generated_invalid_sql",
                {
                    "connection_id": connection_id,
                    "user_id": body.user_id,
                    "sql": sql[:500],
                    "error": validation_error,
                },
            )

            # Log technical details internally (NOT exposed to client)
            logger.error(
                "SQL validation failed - technical details",
                extra={
                    "full_sql": sql,
                    "validation_error": validation_error,
                    "user_id": str(body.user_id) if body.user_id else None,
                    "space_id": str(body.space_id) if body.space_id else None,
                    "connection_id": connection_id,
                },
            )

            # User-friendly message (NO technical/SQL details exposed)
            raise HTTPException(
                status_code=500,
                detail="I couldn't process your request. Please try rephrasing your question.",
            )

    # Debug: log all keys in final_state to see what's available
    log_event(
        "api_query_connection_final_state",
        {
            "connection_id": connection_id,
            "final_state_keys": list(final_state.keys()),
            "chosen_table": chosen_table,
            "chosen_tables": chosen_tables,
            "chosen_table_physical": final_state.get("chosen_table_physical"),
            "has_answer": bool(answer),
            "has_sql": bool(sql),
            "sql_preview": sql[:200] if sql else None,
        },
    )

    # Fallback: try to extract table name from SQL if chosen_table is not available
    if not chosen_table and not chosen_tables and sql:
        import re

        # Try to extract table name from SQL (FROM clause)
        from_match = re.search(r"FROM\s+([^\s,\(\)]+)", sql, re.IGNORECASE)
        if from_match:
            table_from_sql = from_match.group(1).strip()
            # Remove schema prefix if present (e.g., "dataset.table" -> "table")
            if "." in table_from_sql:
                table_from_sql = table_from_sql.split(".")[-1]
            chosen_table = table_from_sql
            log_event(
                "api_query_connection_extracted_from_sql",
                {
                    "connection_id": connection_id,
                    "extracted_table": chosen_table,
                    "sql_preview": sql[:200],
                },
            )

    # Use chosen_tables if available, otherwise fallback to chosen_table
    chosen_datasets = (
        chosen_tables if chosen_tables else ([chosen_table] if chosen_table else [])
    )

    # Debug log
    log_event(
        "api_query_connection_chosen_datasets",
        {
            "connection_id": connection_id,
            "chosen_table": chosen_table,
            "chosen_tables": chosen_tables,
            "final_chosen_datasets": chosen_datasets,
        },
    )

    # DEBUG: Log informações detalhadas do estado para identificar problema
    log_event(
        "api_query_connection_debug_state",
        {
            "connection_id": connection_id,
            "has_sql": bool(sql),
            "sql_preview": sql[:200] if sql else None,
            "has_data": bool(data),
            "data_rows": len(data) if isinstance(data, list) else 0,
            "has_error": bool(error),
            "error": error,
            "has_impossible_reason": bool(final_state.get("impossible_reason")),
            "impossible_reason": final_state.get("impossible_reason"),
            "has_answer": bool(final_state.get("answer")),
            "answer_preview": (final_state.get("answer") or "")[:200],
            "chosen_table": chosen_table,
            "chosen_tables": chosen_tables,
            "final_state_keys": list(final_state.keys()),
        },
    )

    # Raw sample — transform runs at the outer layer (after cache or pipeline)
    data_sample = data[:15] if isinstance(data, list) else []

    # ✅ CAMADA 4: Detecção de PII na resposta
    from core.security.pii_scanner import (
        scan_text_for_pii,
        scan_data_for_pii,
        should_allow_pii_exception,  # Usar nova função unificada
    )

    pii_response_text_result = scan_text_for_pii(answer) if answer else None
    # IMPORTANTE: Escanear dados originais ANTES de filtrar para verificação de contexto agregado
    # Usar dados completos (até 100 linhas) para detecção PII, mas apenas primeiras 15 para resposta
    data_for_pii_scan = data[:100] if isinstance(data, list) else []
    pii_response_data_result = (
        scan_data_for_pii(data_for_pii_scan) if data_for_pii_scan else None
    )

    pii_detected_in_response = (
        pii_response_text_result and pii_response_text_result.detected
    ) or (pii_response_data_result and pii_response_data_result.detected)

    # Verificar se PII deve ser permitido (exceções: agregado OU small result set)
    allow_pii_in_text = False
    allow_pii_in_data = False

    if pii_response_text_result and pii_response_text_result.should_block:
        allow_pii_in_text = should_allow_pii_exception(
            question=body.question or "",
            sql=sql,
            data=data_sample,
            pii_detection_result=pii_response_text_result,
        )

    if pii_response_data_result and pii_response_data_result.should_block:
        # Usar dados originais (não filtrados) para verificação
        allow_pii_in_data = should_allow_pii_exception(
            question=body.question or "",
            sql=sql,
            data=data_for_pii_scan,  # Dados originais antes de filtrar
            pii_detection_result=pii_response_data_result,
        )

    # ✅ SOLUÇÃO: Detectar queries agregadas ou com LIMIT baixo para permitir PII em contexto seguro
    # 1. Queries com GROUP BY ou funções de agregação (SUM, AVG, COUNT, etc.) retornam
    #    dados já anonimizados/agregados, portanto são seguros mesmo com PII detectado
    # 2. Queries com LIMIT <= 150 são consideradas "amostras" e não dumps completos de dados
    is_aggregated_query = False
    is_sample_query = False

    # Scan mode: full_context_agent produces an analytical narrative, not a raw
    # data dump — exempt from the PII block that targets personal data exposure.
    if getattr(body, "agent_mode", None) == "scan":
        is_aggregated_query = True

    if sql:
        sql_upper = sql.upper()

        # Detectar agregação
        has_group_by = "GROUP BY" in sql_upper
        has_aggregation = any(
            func in sql_upper for func in ["SUM(", "AVG(", "COUNT(", "MAX(", "MIN("]
        )
        is_aggregated_query = has_group_by or has_aggregation

        # Detectar LIMIT baixo (amostra)
        import re

        limit_match = re.search(r"LIMIT\s+(\d+)", sql_upper)
        if limit_match:
            limit_value = int(limit_match.group(1))
            is_sample_query = limit_value <= 150

    # Se detectar PII crítico na resposta E não for contexto agregado permitido, bloquear
    # Também permitimos se for uma query agregada (pois o texto descreve dados agregados)
    if pii_response_text_result and pii_response_text_result.should_block:
        # Se for query agregada ou amostra, consideramos seguro liberar a explicação
        if is_aggregated_query or is_sample_query:
            allow_pii_in_text = True
            log_event(
                "pii_text_allowed_aggregated",
                {
                    "connection_id": connection_id,
                    "reason": "Aggregated/Sample query analysis is safe",
                    "is_aggregated": is_aggregated_query,
                    "is_sample": is_sample_query,
                },
            )

        if not allow_pii_in_text:
            # Substituir resposta por mensagem genérica
            answer = "I cannot display sensitive personal information in the results."
            pii_blocked = True

    if (
        pii_response_data_result
        and pii_response_data_result.should_block
        and not allow_pii_in_data
    ):
        # Permitir dados se for query agregada OU amostra (LIMIT baixo)
        if is_aggregated_query:
            log_event(
                "pii_allowed_aggregated_context",
                {
                    "connection_id": connection_id,
                    "has_group_by": has_group_by,
                    "has_aggregation": has_aggregation,
                    "pii_types": (
                        [t.value for t in pii_response_data_result.pii_types]
                        if pii_response_data_result.pii_types
                        else []
                    ),
                    "sql_preview": sql[:200] if sql else None,
                },
            )
            pii_blocked = False  # Não bloquear dados agregados
        elif is_sample_query:
            log_event(
                "pii_allowed_sample_query",
                {
                    "connection_id": connection_id,
                    "limit_value": limit_value if "limit_value" in locals() else None,
                    "pii_types": (
                        [t.value for t in pii_response_data_result.pii_types]
                        if pii_response_data_result.pii_types
                        else []
                    ),
                    "sql_preview": sql[:200] if sql else None,
                },
            )
            pii_blocked = False  # Não bloquear amostras (LIMIT baixo)
        else:
            # Bloquear apenas queries sem agregação E sem LIMIT (ou LIMIT muito alto)
            log_event(
                "pii_blocked_non_aggregated",
                {
                    "connection_id": connection_id,
                    "pii_types": (
                        [t.value for t in pii_response_data_result.pii_types]
                        if pii_response_data_result.pii_types
                        else []
                    ),
                    "sql_preview": sql[:200] if sql else None,
                },
            )
            data_sample = []
            pii_blocked = True
    # ✅ CAMADA 4: Detecção de PII na resposta
    all_pii_types = []
    all_pii_patterns = []

    # Combinar tipos PII detectados
    pii_prompt_info = security_report.scan_details.get("pii", {})
    if pii_prompt_info and pii_prompt_info.get("detected_types"):
        all_pii_types.extend(pii_prompt_info.get("detected_types"))
    if pii_response_text_result and pii_response_text_result.pii_types:
        all_pii_types.extend([t.value for t in pii_response_text_result.pii_types])
    if pii_response_data_result and pii_response_data_result.pii_types:
        all_pii_types.extend([t.value for t in pii_response_data_result.pii_types])
    all_pii_types = list(set(all_pii_types))  # Remover duplicatas

    # Determinar severidade máxima
    severities = []
    if pii_prompt_info and pii_prompt_info.get("severity"):
        severities.append(pii_prompt_info.get("severity").lower())
    if pii_response_text_result and pii_response_text_result.severity:
        severities.append(pii_response_text_result.severity.value)
    if pii_response_data_result and pii_response_data_result.severity:
        severities.append(pii_response_data_result.severity.value)

    max_pii_severity = None
    if "block" in severities:
        max_pii_severity = "block"
    elif "warn" in severities:
        max_pii_severity = "warn"
    elif "info" in severities:
        max_pii_severity = "info"

    # Combinar padrões
    if pii_prompt_info and pii_prompt_info.get("patterns_matched"):
        all_pii_patterns.extend(pii_prompt_info.get("patterns_matched"))
    if pii_response_text_result and pii_response_text_result.patterns_matched:
        all_pii_patterns.extend(pii_response_text_result.patterns_matched)
    if pii_response_data_result and pii_response_data_result.patterns_matched:
        all_pii_patterns.extend(pii_response_data_result.patterns_matched)
    all_pii_patterns = list(set(all_pii_patterns))[:10]  # Remover duplicatas e limitar

    meta = QueryResultMeta(
        detected_language=detected_language,
        chosen_table=chosen_table,
        chosen_datasets=chosen_datasets if chosen_datasets else None,
        sql=sql,
        title=final_state.get("generated_title"),  # Populate title from agent state
        num_rows=len(data),
        error=error,
        plan=final_state.get("plan"),
        citations=knowledge_citations if knowledge_citations else None,
    )

    log_event(
        "api_query_connection",
        {
            "connection_id": connection_id,
            "user_id": body.user_id,
            "space_id": body.space_id,
            "question": body.question[:200],
            "answer_preview": answer[:200],
            "num_rows": len(data),
            "error": error[:200] if error else None,
        },
    )

    # ✅ AUDITORIA: Log completo da query (assíncrono, não bloqueia)
    execution_time_ms = int((time.time() - start_time) * 1000)

    log_query_audit(
        connection_id=connection_id,
        user_id=body.user_id,
        space_id=body.space_id,
        crew_ids=crew_ids,
        thread_id=thread_id,
        platform_role=getattr(body, "platform_role", None) or "user",
        crew_role=getattr(body, "crew_role", None) or "guest",
        question=body.question,
        sql_generated=sql,
        sql_executed=sql,  # Por enquanto igual ao gerado
        sql_validated=True if sql else None,
        validation_error=None,  # Se chegou aqui, passou validação
        num_rows=len(data),
        execution_time_ms=execution_time_ms,
        has_error=bool(error),
        error_message=error,
        was_rate_limited=was_rate_limited,
        prompt_injection_detected=prompt_injection_detected,
        prompt_injection_pattern=prompt_injection_pattern,
        progressive_escalation_score=escalation_score,
        progressive_escalation_detected=escalation_detected,
        detected_language=detected_language,
        chosen_tables=chosen_datasets,
        answer_preview=answer[:500],
        # Campos PII
        pii_detected_in_prompt=pii_detected_in_prompt,
        pii_detected_in_response=pii_detected_in_response,
        pii_types=all_pii_types if all_pii_types else None,
        pii_severity=max_pii_severity,
        pii_patterns_matched=all_pii_patterns if all_pii_patterns else None,
        pii_blocked=pii_blocked,
    )

    # Inject RAG context (debug)
    if retrieval_context:
        meta.rag_context = retrieval_context[:5]

    return QueryResponse(
        answer=answer,
        data_sample=data_sample,
        meta=meta,
        evidence=final_state.get("evidence") or [],
        reasoning_steps=final_state.get("reasoning_steps") or [],
        scan_silent=(
            _scan_silent if getattr(body, "agent_mode", None) == "scan" else None
        ),
        scan_insight_title=_scan_insight_title,
        # Echo the thread_id so the client can send it back on the next turn
        # to continue the conversation.  When the request had no thread_id the
        # server generated a UUID (run_agent_once) — returning it here lets the
        # frontend seed the follow-up chain without breaking backward-compat
        # (field is Optional, old clients safely ignore it).
        thread_id=query_thread_id,
    )


def _build_streaming_agent_state(body, crew_ids, retrieval_context) -> dict:
    """Build the LangGraph state dict for the STREAMING path.

    Extracted from the inline construction so the locale-passing contract is
    unit-testable in isolation (see tests/test_bilingual_cache_locale_regression).

    A2 regression guard: this path used to build the dict by hand and dropped
    ``locale``, so downstream consumers (orchestrator/builder) fell back to
    statistical detection and answered short PT messages in EN. ``locale`` MUST
    come from the same source the non-streaming path uses (``body.locale``).
    """
    return {
        "question": body.question,
        "user_id": body.user_id,
        "space_id": body.space_id,
        "crew_ids": crew_ids,
        # A2 fix — do not remove. The streaming path must carry the user's
        # target locale; without it, short PT messages get answered in EN.
        "locale": getattr(body, "locale", None),
        "retrieval_context": retrieval_context,
        # Configurações dinâmicas da IA
        "instructions": body.instructions,
        "creativity": body.creativity,
        "length": body.length,
        "response_format": body.response_format,
        "ai_tone": body.ai_tone,
        "ai_style": body.ai_style,
        "sql_instructions": body.sql_instructions,
        "selected_datasets": body.selected_datasets,
        # ✅ Configuração de segurança dinâmica (RLS, colunas, etc.)
        "security_config": body.security_config,
        # Agent mode hint: forces data-path routing for scan/sql/context
        "agent_mode": body.agent_mode,
    }


async def _stream_connection_query(
    connection_id: str,
    body: QueryRequest,
    db: Session,
) -> AsyncGenerator[str, None]:
    """
    Generator function that yields SSE events for streaming query responses.
    """
    try:
        # Medir tempo para auditoria
        start_time = time.time()

        # Detectar idioma para mensagens de erro/resposta
        try:
            lang = detect_language(body.question or "")
        except:
            lang = "en"

        # ✅ CAMADA 1: Rate limiting (mesma regra do endpoint normal)
        user_key = body.user_id or f"conn_{connection_id}"
        allowed, error = _rate_limiter.check_rate_limit(user_key, "query")
        if not allowed:
            log_query_audit(
                connection_id=connection_id,
                user_id=body.user_id,
                space_id=body.space_id,
                crew_ids=body.crew_ids,
                thread_id=body.thread_id,
                question=body.question,
                was_rate_limited=True,
            )
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        # ✅ LANGUAGE GUARDRAIL (EN + PT) — locale-aware + mensagem bilíngue.
        # A estabilidade por thread é aplicada no orchestrator; aqui só bloqueamos
        # o caso claro (sem locale + detecção confiante de idioma não suportado).
        _blocked, _ = language_decision(
            body.question or "", locale=getattr(body, "locale", None)
        )
        if _blocked:
            try:
                log_event(
                    "stream_blocked_language",
                    {
                        "connection_id": connection_id,
                        "user_id": body.user_id,
                        "detected_language": lang,
                        "question": body.question[:200],
                    },
                )
            except Exception:
                pass

            error_msg = unsupported_language_message()

            yield f"data: {json.dumps({'type': 'answer', 'text': error_msg})}\n\n"
            yield f"data: {json.dumps({'type': 'meta', 'meta': {'detected_language': lang, 'error': 'language_not_supported'}, 'data_sample': []})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        # ✅ CAMADA 2: CAMADA DE SEGURANÇA UNIFICADA (Audit Manager)
        from core.security.audit_manager import AuditManager
        from core.llm.factory import create_llm_orchestrator

        thread_id = body.thread_id or f"conn_{connection_id}_{int(time.time())}"

        # Criar provider LLM para avaliação de segurança
        llm_provider = create_llm_orchestrator()

        # Avaliação consolidada: PII + Injection + Escalation + Auditoria
        security_report = await AuditManager.evaluate_prompt(
            question=body.question,
            user_id=body.user_id,
            connection_id=connection_id,
            thread_id=thread_id,
            llm_provider=llm_provider,
        )

        if security_report.is_blocked:
            # Mensagens amigáveis por tipo de bloqueio
            if security_report.blocked_by == "PII_SCANNER":
                message = get_message("PII_BLOCKED", lang)
                error_code = "pii_prompt_blocked"
            else:
                message = get_message("SECURITY_BLOCKED", lang)
                error_code = "security_blocked"

            # Auditoria legada para streaming
            esc_info = security_report.scan_details.get("escalation", {})
            escalation_score = int(esc_info.get("score", 0))
            escalation_detected = security_report.blocked_by == "PROGRESSIVE_ESCALATION"

            log_query_audit(
                connection_id=connection_id,
                user_id=body.user_id,
                space_id=body.space_id,
                crew_ids=body.crew_ids,
                thread_id=thread_id,
                question=security_report.redacted_prompt,
                pii_detected_in_prompt=(security_report.blocked_by == "PII_SCANNER"),
                pii_blocked=(security_report.blocked_by == "PII_SCANNER"),
                prompt_injection_detected=(
                    security_report.blocked_by == "SECURITY_GUARD"
                ),
                progressive_escalation_detected=escalation_detected,
                progressive_escalation_score=escalation_score,
            )

            # Enviar como resposta normal para o frontend exibir corretamente
            yield f"data: {json.dumps({'type': 'chunk', 'content': message})}\n\n"
            yield f"data: {json.dumps({'type': 'meta', 'meta': {'detected_language': lang, 'error': error_code}, 'data_sample': []})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        # Extract escalation values for later use if not blocked
        esc_info_later = security_report.scan_details.get("escalation", {})
        escalation_score = int(esc_info_later.get("score", 0))
        escalation_detected = security_report.blocked_by == "PROGRESSIVE_ESCALATION"

        # Verificar se conexão existe
        result = await db.execute(
            text(
                "SELECT id, name, connector_id AS type, config FROM data_connections WHERE id = :id"
            ),
            {"id": connection_id},
        )
        conn_result = result.first()

        if not conn_result:
            yield f"data: {json.dumps({'type': 'error', 'message': f'Conexão {connection_id} não encontrada'})}\n\n"
            return

        # Resolver crew_ids
        crew_ids = body.crew_ids or []
        if body.user_id:
            try:
                resolved_crew_ids = await resolve_crew_ids_for_context(
                    db=db,
                    user_id=UUID(body.user_id),
                    space_id=UUID(body.space_id) if body.space_id else None,
                    request_crew_ids=body.crew_ids,
                    is_personal=getattr(body, "is_personal", False),
                )
                crew_ids = [str(crew_id) for crew_id in resolved_crew_ids]
            except Exception as e:
                log_event(
                    "api_query_connection_stream_resolve_crew_ids_error",
                    {
                        "connection_id": connection_id,
                        "error": str(e),
                    },
                )
                crew_ids = []

        # Carregar AgentConfig (multi-connection when body.connection_ids provided)
        try:
            agent_config = await load_agent_config_from_connection(
                db=db,
                space_id=body.space_id,
                connection_id=connection_id,
                crew_ids=crew_ids if crew_ids else None,
                authorized_tables=body.authorized_tables,
                connection_ids=body.connection_ids or None,
                space_ids=getattr(body, "space_ids", None) or None,
            )
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return

        # Criar DataSource
        conn_config = conn_result[3]
        if isinstance(conn_config, str):
            try:
                conn_config = json.loads(conn_config)
            except json.JSONDecodeError:
                conn_config = {}
        elif conn_config is None:
            conn_config = {}
        elif not isinstance(conn_config, dict):
            conn_config = {}

        from core.security.config_decryption import decrypt_config

        conn_config = decrypt_config(conn_config)

        class TempDataConnection:
            def __init__(self, id, name, type, config):
                self.id = id
                self.name = name
                self.type = type
                self.config = config

        data_conn = TempDataConnection(
            id=str(conn_result[0]),
            name=conn_result[1],
            type=conn_result[2] or "bigquery",
            config=conn_config,
        )

        try:
            data_source = DataSourceFactory.build_from_dataconnection(data_conn)
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': f'Erro ao criar DataSource: {str(e)}'})}\n\n"
            return

        # LLMs
        llm_orchestrator = create_llm_orchestrator()
        llm_specialist = create_llm_specialist()
        llm_formatter = create_llm_formatter()
        embedding_provider = create_embedding_provider()

        # Buscar contexto RAG com Personal isolation — ver comentário
        # análogo no caller principal para detalhes do contrato.
        retrieval_context: list[str] = []
        try:
            retrieval_context, _ = await build_retrieval_context_for_question(
                db=db,
                embedding_provider=embedding_provider,
                space_id=body.space_id,
                crew_ids=crew_ids if crew_ids else None,
                question=body.question,
                top_k=10,
                connection_id=connection_id,
                is_personal=bool(getattr(body, "is_personal", False)),
                user_id=getattr(body, "user_id", None),
                mentioned_file_ids=getattr(body, "mentioned_file_ids", None),
                authorized_tables=body.authorized_tables,
            )
        except Exception:
            retrieval_context = []

        # Executar agente até o specialist (sem formatter ainda)
        try:
            from core.agents.generic_sql_agent import build_generic_sql_graph
            from core.llm.formatter import (
                _ensure_language,
                _serialize_for_json,
                _compute_basic_stats,
                _stream_llm,
                _extract_topic,
            )

            state = _build_streaming_agent_state(body, crew_ids, retrieval_context)

            def db_session_factory():
                # Tenant-aware (Model B); falls back to the global sync
                # session for the default context.
                return tenant_connection_manager.sync_session_for()

            app = build_generic_sql_graph(
                agent_config=agent_config,
                data_source=data_source,
                db_session_factory=db_session_factory,
                embedding_provider=embedding_provider,
                llm_orchestrator=llm_orchestrator,
                llm_specialist=llm_specialist,
                llm_formatter=llm_formatter,
            )
            # Derive thread_id for LangGraph config
            thread_id = (
                body.thread_id or f"{body.user_id or 'anon'}-{connection_id}-stream"
            )

            # Load chat history so follow-up questions have context
            try:
                _hist_result = await db.execute(
                    select(ChatHistory)
                    .where(ChatHistory.thread_id == thread_id)
                    .order_by(desc(ChatHistory.created_at))
                    .limit(10)
                )
                _recent = _hist_result.scalars().all()[::-1]
                state["chat_history"] = [
                    {"role": m.role, "content": m.content} for m in _recent
                ]
            except Exception as _e:
                logger.error(f"Error loading stream chat history: {_e}")
                state["chat_history"] = []

            # Executar até o specialist (orchestrator -> specialist)
            # Não executamos o formatter ainda, vamos fazer streaming dela
            final_state = None
            for chunk in app.stream(
                state, config={"configurable": {"thread_id": thread_id}}
            ):
                for node_name, node_state in chunk.items():
                    if node_name in [
                        "orchestrator",
                        "specialist",
                        "parallel_specialist",
                        "merger",
                        "mixed_planner",
                        "mixed_merger",
                        "people_specialist",
                        "knowledge_specialist",
                        "events_specialist",
                        "relationships_specialist",
                        "widgets_specialist",
                        # Scan mode routes to the full_context node, which is a
                        # terminal node (edge -> END) that produces the final
                        # `answer` directly. It was missing from this capture
                        # list, so its state was discarded and final_state stayed
                        # None — surfacing as a false "Erro ao executar agente"
                        # and a "Run produced no output" finding. The downstream
                        # answer/no-sql branch already streams its answer.
                        "full_context",
                    ]:
                        final_state = node_state
                        # Enviar progresso e eventos específicos
                        if node_name == "orchestrator":
                            yield f"data: {json.dumps({'type': 'progress', 'stage': 'orchestrator', 'message': 'Analisando pergunta...'})}\n\n"

                            # Enviar evento quando datasets são escolhidos
                            chosen_table = node_state.get("chosen_table")
                            chosen_tables = node_state.get("chosen_tables")
                            if chosen_table or chosen_tables:
                                chosen_datasets = (
                                    chosen_tables
                                    if chosen_tables
                                    else ([chosen_table] if chosen_table else [])
                                )
                                yield f"data: {json.dumps({'type': 'datasets_selected', 'datasets': chosen_datasets})}\n\n"

                        elif node_name == "specialist":
                            yield f"data: {json.dumps({'type': 'progress', 'stage': 'specialist', 'message': 'Executando query...'})}\n\n"

                            # Enviar evento quando SQL é gerado
                            sql = node_state.get("sql")
                            if sql:
                                # ✅ CAMADA 3: Validar SQL gerado antes de expor ao cliente
                                allowed_tables = [
                                    t.physical_name for t in agent_config.tables
                                ]
                                allowed_tables.extend(
                                    [t.logical_name for t in agent_config.tables]
                                )
                                connection_type = conn_result[2] or "bigquery"
                                validator = AdvancedSQLValidator(
                                    allowed_tables=allowed_tables,
                                    allowed_columns=None,
                                    max_limit=5000,
                                    max_columns=50,
                                    max_group_by=50,
                                )
                                ok, validation_error = validator.validate(
                                    sql, connection_type
                                )
                                if not ok:
                                    log_event(
                                        "ai_generated_invalid_sql_stream",
                                        {
                                            "connection_id": connection_id,
                                            "user_id": body.user_id,
                                            "sql": sql[:500],
                                            "error": validation_error,
                                        },
                                    )
                                    log_query_audit(
                                        connection_id=connection_id,
                                        user_id=body.user_id,
                                        space_id=body.space_id,
                                        crew_ids=crew_ids,
                                        thread_id=thread_id,
                                        question=body.question,
                                        sql_generated=sql,
                                        sql_executed=None,
                                        sql_validated=False,
                                        validation_error=validation_error,
                                        execution_time_ms=int(
                                            (time.time() - start_time) * 1000
                                        ),
                                        has_error=True,
                                        error_message=validation_error,
                                        progressive_escalation_score=escalation_score,
                                        progressive_escalation_detected=escalation_detected,
                                    )

                                    # Mensagem amigável para erro técnico no streaming
                                    msg = _erro_para_quem_pergunta(lang, final_state.get("error"))
                                    yield f"data: {json.dumps({'type': 'error', 'message': msg})}\n\n"
                                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                                    return

                                yield f"data: {json.dumps({'type': 'sql_generated', 'sql': sql})}\n\n"

            if not final_state:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Erro ao executar agente'})}\n\n"
                return

            # Se houve erro no agente, enviar amigável e terminar
            if final_state.get("error"):
                lang = _ensure_language(
                    body.question,
                    final_state.get("detected_language"),
                    locale=getattr(body, "locale", None),
                )
                msg = _erro_para_quem_pergunta(lang, final_state.get("error"))
                # The DEBUG suffix is the only channel reaching an operator
                # while the observability stack is down. A bare TypeError with
                # no stack is unactionable, so carry the traceback the failing
                # node recorded. Remove once Grafana/Loki are back.
                _tb = final_state.get("error_traceback")
                if _tb:
                    msg = f"{msg}\nTRACEBACK: {_tb}"
                yield f"data: {json.dumps({'type': 'chunk', 'content': msg})}\n\n"
                meta = {
                    "detected_language": lang,
                    "chosen_table": final_state.get("chosen_table"),
                    "chosen_datasets": final_state.get("chosen_tables"),
                    "sql": final_state.get("sql"),
                    "title": final_state.get("generated_title"),
                    "num_rows": 0,
                    "error": str(final_state.get("error")),
                }
                yield f"data: {json.dumps({'type': 'meta', 'meta': meta, 'data_sample': []})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                return

            # Se o specialist marcou a pergunta como impossível, tratar como no-data
            # mas preservar o motivo para debug.
            if final_state.get("impossible_reason"):
                lang = _ensure_language(
                    body.question,
                    final_state.get("detected_language"),
                    locale=getattr(body, "locale", None),
                )
                topic = _extract_topic(body.question)
                msg = get_message("NO_DATA_FOUND", lang, topic=topic)
                yield f"data: {json.dumps({'type': 'chunk', 'content': msg})}\n\n"
                meta = {
                    "detected_language": lang,
                    "chosen_table": final_state.get("chosen_table"),
                    "chosen_datasets": final_state.get("chosen_tables"),
                    "sql": None,
                    "title": final_state.get("generated_title"),
                    "num_rows": 0,
                    "error": final_state.get("impossible_reason"),
                }
                yield f"data: {json.dumps({'type': 'meta', 'meta': meta, 'data_sample': []})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                return

            # Non-SQL specialists (mixed_dispatch, people_specialist, etc.) already set
            # state["answer"] without SQL data. Check this BEFORE the no-data guard
            # because these nodes intentionally produce data=[] with answer set.
            if final_state.get("answer") and not final_state.get("sql"):
                pre_answer = final_state["answer"]
                pre_title = final_state.get("generated_title") or body.question[:50]
                pre_lang = final_state.get("detected_language") or "en"
                yield f"data: {json.dumps({'type': 'progress', 'stage': 'formatter', 'message': 'Gerando resposta...'})}\n\n"
                yield f"data: {json.dumps({'type': 'chunk', 'content': pre_answer})}\n\n"
                pre_meta = {
                    "detected_language": pre_lang,
                    "chosen_table": final_state.get("chosen_table"),
                    "chosen_datasets": final_state.get("chosen_tables") or [],
                    "sql": None,
                    "title": pre_title,
                    "num_rows": 0,
                    "error": None,
                }
                yield f"data: {json.dumps({'type': 'meta', 'meta': pre_meta, 'data_sample': []})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                # Persist conversation turn for future follow-ups
                try:
                    await db.rollback()
                    db.add(
                        ChatHistory(
                            thread_id=thread_id, role="user", content=body.question
                        )
                    )
                    db.add(
                        ChatHistory(
                            thread_id=thread_id,
                            role="assistant",
                            content=pre_answer,
                            extra={"generated_title": pre_title},
                        )
                    )
                    await db.commit()
                except Exception as _e:
                    logger.error(f"Error saving stream chat history (pre_answer): {_e}")
                    try:
                        await db.rollback()
                    except Exception:
                        pass
                return

            # Se não há dados mas há SQL executado, passar para o formatter — ele
            # produz uma resposta significativa (ex. "Nenhuma anomalia encontrada").
            # Se não há SQL, usar mensagem genérica de no-data.
            if not final_state.get("data") and not final_state.get("sql"):
                lang = _ensure_language(
                    body.question,
                    final_state.get("detected_language"),
                    locale=getattr(body, "locale", None),
                )
                topic = _extract_topic(body.question)
                msg = get_message("NO_DATA_FOUND", lang, topic=topic)
                yield f"data: {json.dumps({'type': 'chunk', 'content': msg})}\n\n"
                meta = {
                    "detected_language": lang,
                    "chosen_table": final_state.get("chosen_table"),
                    "sql": None,
                    "num_rows": 0,
                    "error": None,
                }
                yield f"data: {json.dumps({'type': 'meta', 'meta': meta, 'data_sample': []})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                return

            # Agora fazer streaming da resposta do formatter
            yield f"data: {json.dumps({'type': 'progress', 'stage': 'formatter', 'message': 'Gerando resposta...'})}\n\n"

            question = final_state.get("question") or ""
            data = final_state.get("data") or []
            detected_language = final_state.get("detected_language")

            # Emit structured rows so the frontend Insight Cockpit can render
            # Bar/Line/Pie/Table charts without a second round-trip to the AI.
            # Wire format: compact columns + array-of-arrays + truncated flag.
            # R6 caps row count at 200; R11 caps each cell at 2 kB.
            try:
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    col_order = list(data[0].keys())
                    ROW_CAP = 200
                    CELL_CAP = 2048
                    truncated_rows = len(data) > ROW_CAP
                    serialized_rows = []
                    for row in data[:ROW_CAP]:
                        packed = []
                        for c in col_order:
                            v = row.get(c)
                            if isinstance(v, str) and len(v) > CELL_CAP:
                                v = v[:CELL_CAP] + "…"
                            packed.append(v)
                        serialized_rows.append(packed)
                    # _serialize_for_json handles datetime / Decimal / bytes.
                    safe_rows = _serialize_for_json(serialized_rows)
                    yield (
                        f"data: {json.dumps({'type': 'rows', 'columns': col_order, 'rows': safe_rows, 'truncated': truncated_rows})}\n\n"
                    )
            except Exception as _e:
                # Never break the stream on row emission; logs give us the
                # evidence we need and the finding still saves with rows=null.
                log_event("stream_rows_emit_error", {"error": str(_e)})
            # lang = _ensure_language(question, detected_language) # Removed redundant call

            # Raw sample for stats (formatter LLM needs original rows, not chart/kpi wrappers)
            raw_sample = data[:15]
            serialized_sample = _serialize_for_json(raw_sample)
            sample_json = json.dumps(serialized_sample, ensure_ascii=False, indent=2)
            stats_text = _compute_basic_stats(raw_sample)

            _stream_lang = (
                lingua_da_resposta(detected_language)
            )
            _stream_lang_name = nome_da_lingua(_stream_lang)
            _insufficient_msg = (
                "Dados insuficientes para responder esta pergunta."
                if _stream_lang == "pt"
                else "Insufficient data to answer this question."
            )

            system_msg = {
                "role": "system",
                "content": (
                    "You are a data response narrator.\n"
                    "Your ONLY job: translate query results into natural language.\n\n"
                    "CRITICAL RULES:\n"
                    "YOU MUST NOT:\n"
                    "- Mention SQL, tables, columns, or technical database terms\n"
                    "- Infer data beyond what was provided in the results\n"
                    "- Create new queries or suggest queries\n"
                    "- Explain how data was retrieved\n"
                    "- Answer questions not answered by the results\n"
                    "- Mention table names, column names, or database structure\n"
                    "- Claim values are 'constant', 'uniform', 'do not vary', 'are all equal',\n"
                    "  or that 'min, max and average are the same'. The result may be an\n"
                    "  AGGREGATE (COUNT/SUM/AVG) — a single aggregated value says NOTHING\n"
                    "  about how the underlying rows are spread.\n"
                    "- Infer ABSENCE from a limited/aggregated result ('there are no other X',\n"
                    "  'no variation', 'nothing else exists') just because few rows came back —\n"
                    "  more may exist beyond what was returned.\n"
                    "- Invent statistics (min/max/average/trends/variation) not literally\n"
                    "  present in the provided results.\n"
                    "- Rescale, multiply, divide or convert any numeric value. Report every\n"
                    "  number EXACTLY as it appears (0.75 is 0.75, NOT 75%). If a value is\n"
                    "  already a percentage, append '%' without changing the digits.\n\n"
                    "YOU MUST:\n"
                    "- Only use the data provided in the results\n"
                    f"- Answer ONLY in {_stream_lang_name} - THIS IS A STRICT REQUIREMENT\n"
                    f"- If data is insufficient, say '{_insufficient_msg}'\n"
                    "- Keep the answer concise and objective (maximum 4 sentences)\n\n"
                    f"CRITICAL LANGUAGE REQUIREMENT:\n"
                    f"- You MUST answer in {_stream_lang_name}, matching the user's language.\n"
                ),
            }

            user_msg = {
                "role": "user",
                "content": (
                    f"User question:\n{question}\n\n"
                    f"Total rows returned (not all shown): {len(data)}\n"
                    f"{stats_text}\n\n"
                    "Sample of the data (up to 15 rows, JSON):\n"
                    f"{sample_json}\n\n"
                    "Explain the main insight(s) from this data in a concise way. The "
                    "result may be aggregated or limited to a few rows — describe ONLY "
                    "what these rows show; do not infer the full distribution, the "
                    "variation of the underlying rows, or the absence of other values. "
                    f"Answer in {_stream_lang_name}."
                ),
            }

            # Stream do LLM formatter
            accumulated_answer = ""
            try:
                for chunk in _stream_llm(llm_formatter, system_msg, user_msg):
                    accumulated_answer += chunk
                    yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
            except Exception as e:
                # Fallback se streaming falhar
                fallback = "Error formatting the response with the AI. Data was queried successfully, but I could not generate a summary."
                yield f"data: {json.dumps({'type': 'chunk', 'content': fallback})}\n\n"
                accumulated_answer = fallback

            # Enviar metadados finais
            chosen_table = final_state.get("chosen_table")
            chosen_tables = final_state.get("chosen_tables")
            sql = final_state.get("sql")

            chosen_datasets = (
                chosen_tables
                if chosen_tables
                else ([chosen_table] if chosen_table else [])
            )

            # Last-mile: transform raw sample and infer widget type
            formatted_sample = _serialize_for_json(
                _transform_data_for_format(raw_sample, body.response_format)
            )
            recommended_widget_type = _infer_widget_type(
                formatted_sample, body.response_format
            )

            meta = {
                "detected_language": lang,
                "chosen_table": chosen_table,
                "chosen_datasets": chosen_datasets if chosen_datasets else None,
                "sql": sql,
                "title": final_state.get("generated_title"),
                "num_rows": len(data),
                "error": None,
            }

            yield f"data: {json.dumps({'type': 'meta', 'meta': meta, 'data_sample': formatted_sample, 'recommended_widget_type': recommended_widget_type})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

            # Persist conversation turn for future follow-ups
            if accumulated_answer:
                try:
                    await db.rollback()
                    db.add(
                        ChatHistory(
                            thread_id=thread_id, role="user", content=body.question
                        )
                    )
                    db.add(
                        ChatHistory(
                            thread_id=thread_id,
                            role="assistant",
                            content=accumulated_answer,
                            extra={
                                "sql": sql,
                                "generated_title": final_state.get("generated_title"),
                            },
                        )
                    )
                    await db.commit()
                except Exception as _e:
                    logger.error(f"Error saving stream chat history: {_e}")
                    try:
                        await db.rollback()
                    except Exception:
                        pass

            # ✅ AUDITORIA (stream): registrar ao final
            try:
                execution_time_ms = int((time.time() - start_time) * 1000)
                log_query_audit(
                    connection_id=connection_id,
                    user_id=body.user_id,
                    space_id=body.space_id,
                    crew_ids=crew_ids,
                    thread_id=thread_id,
                    question=body.question,
                    sql_generated=sql,
                    sql_executed=sql,
                    sql_validated=True if sql else None,
                    validation_error=None,
                    num_rows=len(data) if isinstance(data, list) else None,
                    execution_time_ms=execution_time_ms,
                    has_error=False,
                    error_message=None,
                    prompt_injection_detected=False,
                    prompt_injection_pattern=None,
                    progressive_escalation_score=escalation_score,
                    progressive_escalation_detected=escalation_detected,
                    detected_language=lang,
                    chosen_tables=chosen_datasets,
                    answer_preview=(accumulated_answer or "")[:500],
                )
            except Exception:
                pass

        except Exception as e:
            import traceback

            error_detail = str(e)
            tb = traceback.format_exc()
            msg = _erro_para_quem_pergunta(lang, error_detail, tb)
            yield f"data: {json.dumps({'type': 'error', 'message': msg})}\n\n"
            log_event(
                "api_query_connection_stream_error",
                {
                    "connection_id": connection_id,
                    "error": error_detail,
                    "error_type": type(e).__name__,
                    "traceback": tb[-3000:],
                },
            )

    except Exception as e:
        import traceback as _traceback

        _tb = _traceback.format_exc()
        msg = _erro_para_quem_pergunta(lang, str(e), _tb)
        yield f"data: {json.dumps({'type': 'error', 'message': msg})}\n\n"
        log_event(
            "api_query_connection_stream_outer_error",
            {
                "error": str(e)[:500],
                "error_type": type(e).__name__,
                "traceback": _tb[-3000:],
            },
        )


@router.post("/{connection_id}/query/stream")
async def query_connection_stream(
    connection_id: str,
    body: QueryRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Faz uma pergunta usando uma DataConnection com streaming de resposta.
    Retorna Server-Sent Events (SSE) com chunks de texto conforme são gerados.

    Formato dos eventos:
    - {"type": "chunk", "content": "texto..."} - pedaços da resposta
    - {"type": "meta", "meta": {...}, "data_sample": [...]} - metadados finais
    - {"type": "done"} - fim do stream
    - {"type": "error", "message": "..."} - erro ocorrido
    """
    if not body.space_id:

        async def error_stream():
            yield f"data: {json.dumps({'type': 'error', 'message': 'space_id é obrigatório no body da requisição'})}\n\n"

        return StreamingResponse(error_stream(), media_type="text/event-stream")

    return StreamingResponse(
        _stream_connection_query(connection_id, body, db),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Desabilita buffering no nginx
        },
    )


from decimal import Decimal
from datetime import date


def _serialize_for_json(obj: Any) -> Any:
    """Helper to serialize datetime/decimal for JSON."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, list):
        return [_serialize_for_json(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _serialize_for_json(v) for k, v in obj.items()}
    return obj


def _infer_widget_type(
    data: List[Dict[str, Any]], response_format: Optional[str]
) -> Optional[str]:
    """
    Infers the best widget type from data shape.
    If response_format is explicitly set (and not 'text'), returns it as-is.
    Otherwise auto-detects from the structure of the rows.
    Returns None when there's no data or widget context.
    """
    if not data:
        return None
    if response_format and response_format != "text":
        return response_format
    first_row = data[0]
    keys = list(first_row.keys())
    numeric_cols = [k for k, v in first_row.items() if isinstance(v, (int, float))]
    string_cols = [k for k, v in first_row.items() if isinstance(v, str)]
    if len(data) == 1 and len(numeric_cols) == 1:
        return "kpi"
    if len(numeric_cols) >= 1 and len(string_cols) >= 1:
        return "chart"
    if len(keys) > 1:
        return "table"
    return "text"


def _transform_data_for_format(
    data: List[Dict[str, Any]], response_format: Optional[str]
) -> List[Dict[str, Any]]:
    """
    Transforms raw SQL rows into a structure appropriate for the widget type.

    - "kpi"   → [{ "value": <num>, "label": "<col>" }]
    - "chart" → [{ "labels": [...], "datasets": [{ "label": "...", "data": [...] }] }]
    - "table" → [{ "columns": [...], "rows": [...] }]
    - anything else → raw rows (unchanged)
    """
    if not data or not response_format or response_format == "text":
        return data

    if response_format == "kpi":
        first_row = data[0]
        numeric_col = next(
            (k for k, v in first_row.items() if isinstance(v, (int, float))), None
        )
        if numeric_col is None:
            return data
        return [
            {
                "value": first_row[numeric_col],
                "label": numeric_col.replace("_", " ").title(),
            }
        ]

    if response_format == "chart":
        keys = list(data[0].keys())
        label_col = next((k for k in keys if isinstance(data[0][k], str)), keys[0])
        value_col = next(
            (
                k
                for k in keys
                if k != label_col and isinstance(data[0][k], (int, float))
            ),
            keys[-1],
        )
        return [
            {
                "labels": [_serialize_for_json(row.get(label_col)) for row in data],
                "datasets": [
                    {
                        "label": value_col.replace("_", " ").title(),
                        "data": [
                            _serialize_for_json(row.get(value_col)) for row in data
                        ],
                    }
                ],
            }
        ]

    if response_format == "table":
        columns = list(data[0].keys())
        return [
            {
                "columns": columns,
                "rows": [list(row.values()) for row in data],
            }
        ]

    return data


def _compute_basic_stats(data: List[Dict[str, Any]]) -> str:
    """Compute basic stats for context.

    For a single-row result (almost always an AGGREGATE — COUNT/SUM/AVG), avg
    and max equal the value itself, which the formatter would otherwise narrate
    as "no variation / all values are the same". That is misleading: one
    aggregated row says nothing about the spread of the underlying rows. So we
    emit no distributional stats for <=1 row and flag it as a single aggregate.
    """
    if not data:
        return "No data."

    first_row = data[0]
    total_cols = len(first_row.keys())

    if len(data) <= 1:
        return (
            f"Columns: {total_cols}. Single aggregated row — the values are the "
            "result itself, not a distribution. Do NOT describe variation, "
            "uniformity, min/max or whether values differ."
        )

    # Identify numeric columns
    numeric_cols = []
    for k, v in first_row.items():
        if isinstance(v, (int, float, Decimal)):
            numeric_cols.append(k)

    stats = []
    for col in numeric_cols[:3]:  # Limit to top 3 numeric
        try:
            values = [float(row[col]) for row in data if row.get(col) is not None]
            if values:
                avg = sum(values) / len(values)
                stats.append(f"{col}: avg={avg:.2f}, max={max(values):.2f}")
        except:
            pass

    return f"Columns: {total_cols}. " + "; ".join(stats)


@router.post("/{connection_id}/validate-sql", response_model=ValidateSQLResponse)
async def validate_sql(
    connection_id: str,
    body: ValidateSQLRequest,
    db: AsyncSession = Depends(get_db),
) -> ValidateSQLResponse:
    """
    Valida SQL editado pelo usuário com validação AST e permissões.
    """

    # ✅ CAMADA 1: Rate limiting (mais permissivo para validate)
    user_key = body.user_id or f"conn_{connection_id}"
    allowed, error = _rate_limiter.check_rate_limit(user_key, "validate")
    if not allowed:
        return ValidateSQLResponse(is_valid=False, error=error)

    # ✅ CAMADA 2: Validação regex (rápida)
    from core.sql.validator import validate_sql_strict

    is_valid, error = validate_sql_strict(body.sql)
    if not is_valid:
        return ValidateSQLResponse(is_valid=False, error=error)

    try:
        # Verificar se conexão existe
        result = await db.execute(
            text(
                "SELECT id, name, connector_id AS type, config FROM data_connections WHERE id = :id"
            ),
            {"id": connection_id},
        )
        conn_result = result.first()

        if not conn_result:
            return ValidateSQLResponse(is_valid=False, error="Conexão não encontrada")

        # ✅ CAMADA 3: Resolver permissões
        crew_ids = body.crew_ids or []
        if body.user_id and body.space_id:
            try:
                resolved_crew_ids = await resolve_crew_ids_for_context(
                    db=db,
                    user_id=UUID(body.user_id),
                    space_id=UUID(body.space_id),
                    request_crew_ids=body.crew_ids,
                    is_personal=bool(getattr(body, "is_personal", False)),
                )
                crew_ids = [str(cid) for cid in resolved_crew_ids]
            except Exception as e:
                log_event(
                    "validate_sql_resolve_crew_ids_error",
                    {
                        "connection_id": connection_id,
                        "user_id": body.user_id,
                        "error": str(e)[:200],
                    },
                )
                crew_ids = []

        # Obter tabelas permitidas
        allowed_tables = await _get_allowed_tables_for_validation(
            db=db,
            connection_id=connection_id,
            space_id=body.space_id or "",
            crew_ids=crew_ids,
        )

        if not allowed_tables:
            return ValidateSQLResponse(
                is_valid=False, error="No tables available for this connection"
            )

        # ✅ CAMADA 4: Validação AST + Permissões
        connection_type = (conn_result[2] if conn_result else "bigquery") or "bigquery"

        validator = AdvancedSQLValidator(
            allowed_tables=allowed_tables,
            allowed_columns=None,  # Opcional: filtrar colunas também
            max_limit=100,
            max_columns=10,
            max_group_by=3,
        )

        is_valid, error = validator.validate(body.sql, connection_type)
        if not is_valid:
            return ValidateSQLResponse(is_valid=False, error=error)

        # Criar DataSource
        conn_config = conn_result[3]
        if isinstance(conn_config, str):
            try:
                conn_config = json.loads(conn_config)
            except json.JSONDecodeError:
                conn_config = {}
        elif conn_config is None:
            conn_config = {}
        elif not isinstance(conn_config, dict):
            conn_config = {}

        class TempDataConnection:
            def __init__(self, id, name, type, config):
                self.id = id
                self.name = name
                self.type = type
                self.config = config

        data_conn = TempDataConnection(
            id=str(conn_result[0]),
            name=conn_result[1],
            type=conn_result[2] or "bigquery",
            config=conn_config,
        )

        try:
            data_source = DataSourceFactory.build_from_dataconnection(data_conn)
        except Exception as e:
            return ValidateSQLResponse(
                is_valid=False, error=f"Erro ao criar DataSource: {str(e)}"
            )

        # Executar SQL com LIMIT 5 para preview
        sql = body.sql.strip().rstrip(";")

        # Validar que SQL não está vazio após strip
        if not sql:
            return ValidateSQLResponse(is_valid=False, error="SQL não pode ser vazio")

        # ✅ NOVO: Validar SQL contra regras de segurança (se security_config foi enviado)
        if body.security_config:
            from core.security.security_config import (
                validate_sql_against_security,
                inject_row_filters_in_sql,
                get_default_security_config,
            )

            # Injetar row filters (RLS) se configurado
            sql = inject_row_filters_in_sql(sql, body.security_config)

            # Validar SQL contra regras de segurança
            is_valid, security_error = validate_sql_against_security(
                sql=sql,
                security_config=body.security_config,
            )
            if not is_valid:
                return ValidateSQLResponse(
                    is_valid=False, error=f"Violação de segurança: {security_error}"
                )

        # Adicionar LIMIT se não existir (para evitar queries muito grandes)
        sql_upper = sql.upper()
        if "LIMIT" not in sql_upper:
            sql_with_limit = f"{sql} LIMIT 5"
        else:
            # Se já tem LIMIT, usar como está (mas pode ser limitado pelo DataSource)
            sql_with_limit = sql

        # Executar query
        start_time = time.time()
        try:
            data = data_source.run_query(sql_with_limit)
            execution_time_ms = (time.time() - start_time) * 1000

            # Extrair colunas se houver dados
            columns = None
            if data and len(data) > 0 and isinstance(data[0], dict):
                columns = list(data[0].keys())

            log_event(
                "validate_sql_success",
                {
                    "connection_id": connection_id,
                    "sql_preview": sql[:200],
                    "num_rows": len(data),
                    "execution_time_ms": execution_time_ms,
                },
            )

            explanation = None
            if body.include_explanation and data:
                try:
                    # 1. Preparar dados para o formatter similar ao streaming
                    data_sample = data[:15]
                    serialized_sample = _serialize_for_json(data_sample)
                    sample_json = json.dumps(
                        serialized_sample, ensure_ascii=False, indent=2
                    )
                    stats_text = _compute_basic_stats(data_sample)

                    # 2. Criar contexto do sistema
                    _expl_lang = (
                        detect_language(body.question or "")
                        if (body.question or "")
                        else "en"
                    )
                    if _expl_lang not in NOME_DA_LINGUA:
                        _expl_lang = "en"
                    _expl_lang_name = nome_da_lingua(_expl_lang)
                    system_msg = {
                        "role": "system",
                        "content": (
                            "You are a data analyst helper.\n"
                            "Your job is to explain the query results clearly and concisely.\n\n"
                            "RULES:\n"
                            f"- Answer in {_expl_lang_name} (always).\n"
                            "- Use the provided data sample to derive insights.\n"
                            "- Keep it short (max 3 sentences).\n"
                            "- Start directly with the insight (e.g. 'The data shows that...').\n"
                            "- Do not mention 'JSON', 'query', or technical details."
                        ),
                    }

                    # 3. Criar mensagem do usuário
                    user_msg = {
                        "role": "user",
                        "content": (
                            f"Context Question: {body.question or 'No specific question'}\n"
                            f"Total rows: {len(data)}\n"
                            f"{stats_text}\n\n"
                            "Data Sample:\n"
                            f"{sample_json}\n\n"
                            "Explain the results."
                        ),
                    }

                    # 4. Chamar LLM
                    llm_formatter = create_llm_formatter()
                    response = llm_formatter.invoke([system_msg, user_msg])
                    explanation = getattr(response, "content", "") or ""
                except Exception as e:
                    log_event(
                        "validate_sql_explanation_error",
                        {"connection_id": connection_id, "error": str(e)},
                    )
                    explanation = None

            return ValidateSQLResponse(
                is_valid=True,
                preview_data=data[:5],  # Máximo 5 linhas
                num_rows=len(data),
                execution_time_ms=execution_time_ms,
                columns=columns,
                explanation=explanation,
            )
        except Exception as e:
            error_msg = str(e)[:500]
            log_event(
                "validate_sql_error",
                {
                    "connection_id": connection_id,
                    "sql_preview": sql[:200],
                    "error": error_msg,
                },
            )
            return ValidateSQLResponse(is_valid=False, error=error_msg)

    except Exception as e:
        error_msg = str(e)[:500]
        log_event(
            "validate_sql_unexpected_error",
            {
                "connection_id": connection_id,
                "error": error_msg,
            },
        )
        return ValidateSQLResponse(
            is_valid=False, error=f"Erro inesperado: {error_msg}"
        )
