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

from typing import Optional, List, Dict, Tuple
from uuid import UUID
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import os
import json
import asyncio
import time
import hashlib
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
from core.agents.context_retrieval import build_retrieval_context_for_question
from core.data_sources.factory import DataSourceFactory
from core.logging_utils import log_event
from core.auth.service import get_user_crew_ids_in_space, resolve_crew_ids_for_context
from core.i18n.i18n import detect_language, get_message
from core.security.rate_limiter_redis import _rate_limiter
from core.security.audit import log_query_audit
from core.security.progressive_escalation import detect_progressive_escalation
from core.sql.validator_advanced import AdvancedSQLValidator
from db.session import get_db
from db.base import SyncSessionLocal

router = APIRouter(prefix="/connections", tags=["connection_query"])

# ============================================================================
# Cache para bootstrap suggestions (em memória, pode migrar para Redis depois)
# ============================================================================
_bootstrap_cache: Dict[str, Tuple[ChatBootstrapResponse, datetime]] = {}
CACHE_TTL_MINUTES = 10  # Sugestões válidas por 10 minutos
MAX_CACHE_SIZE = 100  # Limitar tamanho do cache para evitar uso excessivo de memória

# ✅ Cache reativado para respostas rápidas (varia a cada 30 segundos)
DISABLE_BOOTSTRAP_CACHE = False  # Cache habilitado para melhor performance

# ============================================================================
# Cache para dashboard plans (Davinci) (em memória, pode migrar para Redis depois)
# ============================================================================
_dashboard_plan_cache: Dict[str, Tuple[DashboardPlanResponse, datetime]] = {}
DASHBOARD_PLAN_CACHE_TTL_MINUTES = 60  # Planos válidos por 60 minutos (mais longo que bootstrap)
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


def _get_table_stats_cache_key(connection_id: str, space_id: str, crew_ids: Optional[List[str]]) -> str:
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
    initial_resp_norm = str(len(initial_ai_response or "")) # Usar comprimento para evitar chave gigante, ou hash
    if initial_ai_response:
        # Usar os primeiros 50 chars + hash para a chave não ficar gigante mas ser única
        initial_resp_hash = hashlib.md5(initial_ai_response.encode()).hexdigest()[:8]
        initial_resp_norm = initial_resp_hash
        
    spaces_str = ",".join(sorted(context_spaces or []))
    crews_str = ",".join(sorted(context_crews or []))
    tables_str = str(len(context_tables or [])) # Apenas contagem para cache, pois tabelas mudam pouco
    
    # ✅ NOVO: Adicionar versão para invalidar cache antigo após melhorias
    # Incrementar versão quando houver mudanças significativas na lógica de geração
    # v2: validação menos restritiva + fallback melhorado
    # v3: cache key fix + table query improvements
    CACHE_VERSION = "v3"
    
    # ✅ FIX: Usar hash completo da resposta inicial para diferenciar contextos
    # Problema: dashboards idênticos para perguntas diferentes porque initial_ai_response
    # não estava sendo usado corretamente na chave de cache
    if initial_ai_response:
        # Usar hash completo (não apenas primeiros 8 chars) para garantir unicidade
        initial_resp_hash = hashlib.md5(initial_ai_response.encode()).hexdigest()
        initial_resp_norm = initial_resp_hash
    else:
        initial_resp_norm = "no_context"
    
    return f"dashboard_plan:{CACHE_VERSION}:{connection_id}:{space_id}:{crew_ids_str}:{is_personal}:{goal_normalized}:{max_widgets}:{language}:{original_q_normalized}:{initial_resp_norm}:{spaces_str}:{crews_str}:{tables_str}"


def _get_cached_dashboard_plan(cache_key: str) -> Optional[DashboardPlanResponse]:
    """
    Retorna plano de dashboard do cache se ainda válido.
    
    Args:
        cache_key: Chave do cache
        
    Returns:
        DashboardPlanResponse se encontrado e válido, None caso contrário
    """
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


async def _load_connection_metadata_tables(db: AsyncSession, connection_id: str) -> list[dict]:
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
            text("SELECT tables FROM connection_metadata WHERE connection_id = CAST(:cid AS uuid) LIMIT 1"),
            {"cid": connection_id},
        )
        tables = result.scalar_one_or_none()
        if isinstance(tables, list):
            return [t for t in tables if isinstance(t, dict)]
        return []
    except Exception as e:
        log_event("ai_connection_metadata_load_error", {"connection_id": connection_id, "error": str(e)})
        return []


async def _filter_tables_by_permissions(
    db: AsyncSession,
    connection_id: str,
    space_id: str,
    tables: list[dict],
    crew_ids: Optional[List[str]] = None,
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
                WHERE space_id = CAST(:space_id AS uuid)
                AND data_connection_id = CAST(:conn_id AS uuid)
                AND (
                    crew_id IS NULL
                    OR crew_id = ANY(CAST(:crew_ids AS uuid[]))
                )
            """)
            
            result = await db.execute(
                query,
                {
                    "space_id": space_id,
                    "conn_id": connection_id,
                    "crew_ids": crew_ids,
                }
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

            # IMPORTANTE: Se a tabela não existe, retornamos todas as tabelas (sem filtro)
            # Isso é o comportamento fallback seguro.
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
        
        # Se não encontramos correspondências em table_metadata, retornar todas
        # (pode ser que table_metadata não esteja populado ainda)
        if not filtered_tables and allowed_table_names:
            # Se há allowed_table_names mas não encontramos match, pode ser problema de normalização
            # Retornar todas por segurança
            log_event(
                "bootstrap_table_filter_no_matches",
                {
                    "connection_id": connection_id,
                    "space_id": space_id,
                    "crew_ids": crew_ids,
                    "total_tables": len(tables),
                    "allowed_table_names_count": len(allowed_table_names),
                },
            )
            return tables
        
        return filtered_tables if filtered_tables else tables
        
    except Exception as e:
        # Se der erro ao filtrar, retornar todas as tabelas (fail-safe)
        log_event(
            "bootstrap_table_filter_error",
            {
                "connection_id": connection_id,
                "space_id": space_id,
                "error": str(e)[:500],
            },
        )
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
            db=db,
            connection_id=connection_id
        )
        
        if not all_tables:
            return []
        
        # Filtrar por permissões
        filtered_tables = await _filter_tables_by_permissions(
            db=db,
            connection_id=connection_id,
            space_id=space_id,
            tables=all_tables,
            crew_ids=crew_ids
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
            }
        )
        return []


def _schema_summary_from_tables(tables: list[dict], max_tables: int = 12) -> tuple[list[str], str]:
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
            for c in cols[:10]:
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
    connection_type: str
) -> Optional[Dict[str, Any]]:
    """
    Obtém row_count via metadados do sistema (INFORMATION_SCHEMA).
    Muito mais rápido que COUNT(*) e sem custo de processamento.
    """
    try:
        full_name = f"{schema}.{table_name}" if schema else table_name
        
        if connection_type == "bigquery":
            # BigQuery: usar __TABLES__ para row_count (mais rápido que COUNT)
            table_only = table_name.split('.')[-1]
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
            table_only = table_name.split('.')[-1]
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
                timeout=3.0  # 3 segundos máximo
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
        log_event("table_metadata_stats_error", {
            "table": table_name,
            "error": str(e)[:200]
        })
    
    return None


async def _get_table_sample_stats(
    data_source: Any,  # BaseDataSource, mas usando Any para evitar import circular
    table_name: str,
    schema: str,
    columns: List[Dict[str, Any]],
    row_count: int,
    connection_type: str
) -> Optional[Dict[str, Any]]:
    """
    Coleta estatísticas básicas usando sampling para tabelas grandes.
    Sempre limita o número de linhas processadas.
    """
    try:
        full_name = f"{schema}.{table_name}" if schema else table_name
        
        # Identificar colunas numéricas (amount, total, value, etc.)
        amount_cols = [
            c.get("name") for c in columns
            if any(keyword in (c.get("name", "") or "").lower()
                   for keyword in ["amount", "total", "value", "revenue", "price", "cost"])
            and any(t in (c.get("type", "") or "").upper()
                   for t in ["INT", "FLOAT", "NUMERIC", "DECIMAL", "INT64", "FLOAT64"])
        ]
        
        # Identificar colunas de data
        date_cols = [
            c.get("name") for c in columns
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
                        timeout=5.0  # 5 segundos máximo
                    )
                
                if result and len(result) > 0:
                    row = result[0]
                    stats["amount_stats"] = {
                        "total": float(row.get("total", 0)) if row.get("total") else None,
                        "avg": float(row.get("avg", 0)) if row.get("avg") else None,
                        "min": float(row.get("min_val", 0)) if row.get("min_val") else None,
                        "max": float(row.get("max_val", 0)) if row.get("max_val") else None,
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
                        timeout=5.0
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
        log_event("table_sample_stats_error", {
            "table": table_name,
            "error": str(e)[:200]
        })
        return None


async def _collect_table_statistics_optimized(
    data_source: Any,  # BaseDataSource, mas usando Any para evitar import circular
    tables: List[Dict[str, Any]],
    connection_id: str,
    connection_type: str,
    max_tables: int = 3
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
    metadata_results = await asyncio.gather(*[task for _, task in metadata_tasks], return_exceptions=True)
    
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
            task = _get_table_sample_stats(data_source, name, schema, columns, row_count, connection_type)
            sample_tasks.append((full_name, task))
    
    # Executar queries de sample em paralelo (máximo 3)
    if sample_tasks:
        sample_results = await asyncio.gather(
            *[task for _, task in sample_tasks], 
            return_exceptions=True
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
    greeting = "How can I help you with your data?"
    suggestions: list[ChatBootstrapSuggestion] = [
        ChatBootstrapSuggestion(title="Monthly performance", kind="question", question="What is the monthly performance of key indicators?"),
        ChatBootstrapSuggestion(title="Top results", kind="question", question="What are the top results?"),
        ChatBootstrapSuggestion(title="Time-based analysis", kind="question", question="How do the data vary over time?"),
        ChatBootstrapSuggestion(title="Category breakdown", kind="question", question="What is the distribution by category?"),
    ]

    out = suggestions[:max_suggestions]
    while len(out) < max_suggestions:
        out.append(ChatBootstrapSuggestion(title="Example", kind="question", question="Show me something interesting from my data."))
    return ChatBootstrapResponse(greeting=greeting, suggestions=out, meta={"fallback": True})


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

    # Gatekeeper: Force English
    lang = "en"

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
            sug for sug in cached_response.suggestions 
            if not (sug.kind == "action" and sug.action_id == "create_dashboard")
        ]
        
        # Ajustar contagem se necessário após filtrar
        if len(cached_response.suggestions) > body.max_suggestions:
            cached_response.suggestions = cached_response.suggestions[: body.max_suggestions]
        while len(cached_response.suggestions) < body.max_suggestions:
            cached_response.suggestions.append(
                ChatBootstrapSuggestion(
                    title="Example", 
                    kind="question", 
                    question="Show me something interesting from my data."
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
    all_tables = await _load_connection_metadata_tables(db=db, connection_id=connection_id)
    if not all_tables:
        return _fallback_bootstrap(lang=lang, max_suggestions=body.max_suggestions)

    # ✅ NOVA: Filtrar tabelas por permissões (agnóstico, funciona para qualquer domínio)
    # Em modo personal (is_personal=True), resolved_crew_ids pode ser None ou vazio
    # Nesse caso, retornamos todas as tabelas (usuário tem acesso a tudo)
    # Em modo collaborative, filtramos baseado em resolved_crew_ids
    if body.is_personal:
        # Modo personal: usar todas as tabelas (usuário tem acesso a todos os crews)
        tables = all_tables
    else:
        # Modo collaborative: filtrar por permissões
        tables = await _filter_tables_by_permissions(
            db=db,
            connection_id=connection_id,
            space_id=body.space_id,
            tables=all_tables,
            crew_ids=resolved_crew_ids,
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
    max_tables_in_prompt = min(12, len(tables))
    _logical, schema_summary = _schema_summary_from_tables(tables, max_tables=max_tables_in_prompt)

    # ✅ NOVO: Coletar estatísticas dos dados reais (seguindo melhores práticas)
    table_statistics = {}
    stats_cache_key = _get_table_stats_cache_key(connection_id, body.space_id, resolved_crew_ids)
    
    # Verificar cache de estatísticas primeiro
    cached_stats = _get_cached_table_stats(stats_cache_key)
    if cached_stats:
        table_statistics = cached_stats
        log_event("bootstrap_table_stats_cache_hit", {
            "connection_id": connection_id,
            "num_tables_with_stats": len(table_statistics)
        })
    else:
        # Coletar estatísticas (com timeout total de 8 segundos)
        try:
            # Criar DataSource temporário
            result = await db.execute(
                text("SELECT id, name, connector_id AS type, config FROM data_connections WHERE id = :id"),
                {"id": connection_id}
            )
            conn_result = result.first()
            
            if conn_result:
                class TempDataConnection:
                    def __init__(self, id, name, type, config):
                        self.id = id
                        self.name = name
                        self.type = type
                        self.config = config if isinstance(config, dict) else json.loads(config) if isinstance(config, str) else {}
                
                conn_config = conn_result[3]
                if isinstance(conn_config, str):
                    try:
                        conn_config = json.loads(conn_config)
                    except:
                        conn_config = {}
                elif conn_config is None:
                    conn_config = {}
                
                data_conn = TempDataConnection(
                    id=str(conn_result[0]),
                    name=conn_result[1],
                    type=conn_result[2] or "bigquery",
                    config=conn_config
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
                        max_tables=3  # Máximo 3 tabelas principais
                    ),
                    timeout=8.0  # Timeout total de 8 segundos
                )
                
                # Armazenar no cache
                _set_cached_table_stats(stats_cache_key, table_statistics)
                
                log_event("bootstrap_table_stats_collected", {
                    "connection_id": connection_id,
                    "num_tables_with_stats": len(table_statistics),
                })
        except (asyncio.TimeoutError, FutureTimeoutError):
            log_event("bootstrap_table_stats_timeout", {
                "connection_id": connection_id
            })
            # Continuar sem stats se timeout
        except Exception as e:
            log_event("bootstrap_table_stats_error", {
                "connection_id": connection_id,
                "error": str(e)[:200]
            })
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
    
    system = (
        "You generate a greeting and suggestion cards for a data analytics chat.\n"
        "Rules:\n"
        "- Output STRICT JSON only.\n"
        "- JSON schema: {\"greeting\": string, \"suggestions\": [{\"title\": string, \"question\": string}]}\n"
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
        first_table_stats = list(table_statistics.values())[0] if table_statistics else {}
        if first_table_stats.get("row_count"):
            user += f"- If a table has {first_table_stats['row_count']:,} rows, suggest 'How many X do we have?'\n"
        if first_table_stats.get("amount_stats", {}).get("total"):
            user += f"- If there's a total amount, suggest 'What is the total revenue?' or 'What is the average value?'\n"
        if first_table_stats.get("date_range"):
            user += f"- If there's a date range, suggest questions about that time period\n"
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
                        suggestions.append(ChatBootstrapSuggestion(title=title, kind="question", question=question))

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
                    "columns": [c.get("name") if isinstance(c, dict) else str(c) 
                               for c in (t.get("columns") or [])]
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
            
            question_validator = QuestionValidator(available_tables_meta, available_columns)
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
                    should_filter = suggestion_validator.should_filter_suggestion(question_text)
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
            sug for sug in suggestions 
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
                    question=(suggestions[-1].question if suggestions else "Show me something interesting from my data.")
                )
            )

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
    logical_tables: list[str] = []
    schema_summary = ""
    max_tables_in_prompt = 0

    # ✅ SECURITY: Check for prompt injection in original_question
    original_question = getattr(body, "original_question", None)
    if original_question:
        try:
            from core.security.security_guard import evaluate_security
            from core.security.semantic_classifier import _create_openai_client
            
            llm_client_for_security = _create_openai_client()
            security_decision = await evaluate_security(
                question=original_question,
                llm_client=llm_client_for_security,
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
                    detail="I can't help with that request. Please rephrase your question about your data."
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
    )
    
    cached_response = _get_cached_dashboard_plan(cache_key)
    if cached_response:
        log_event(
            "dashboard_plan_cache_hit",
            {
                "connection_id": connection_id,
                "space_id": body.space_id,
                "cache_key": cache_key,
                "num_widgets": len(cached_response.widgets),
            },
        )
        # Atualizar meta para indicar que veio do cache
        if cached_response.meta:
            cached_response.meta["cached"] = True
        return cached_response
    
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
            logical_tables = [str(x) for x in body.logical_tables_override if str(x).strip()]
            schema_summary = str(body.schema_summary_override or "").strip()
            max_tables_in_prompt = min(12, len(logical_tables))
        else:
            tables = await _load_connection_metadata_tables(db=db, connection_id=connection_id)
            max_tables_in_prompt = min(12, len(tables))
            logical_tables, schema_summary = _schema_summary_from_tables(tables, max_tables=max_tables_in_prompt)
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
        
        plan = generate_dashboard_plan(
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
        )
        
        # ✅ NOVA: Armazenar no cache após gerar
        _set_cached_dashboard_plan(cache_key, response)
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
            }
        )
        
        # User-friendly message (NO stack trace or technical details)
        raise HTTPException(
            status_code=500,
            detail="Unable to generate dashboard. Please try selecting specific tables or simplifying your request."
        )


@router.get("/{connection_id}/tables")
async def list_available_tables(
    connection_id: str,
    space_id: str = Query(..., description="ID do space (obrigatório)"),
    user_id: Optional[str] = Query(None, description="ID do usuário (opcional)"),
    crew_ids: Optional[List[str]] = Query(None, description="Lista de crew_ids (opcional)"),
    is_personal: bool = Query(False, description="Modo personal (acesso a todos os crews)"),
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
                is_personal=is_personal
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
    
    # Backend-compatible: list tables from `connection_metadata.tables`.
    # Note: we currently do not enforce crew_id-level filtering here; that is handled by the product backend permissions.
    raw_tables = await _load_connection_metadata_tables(db=db, connection_id=connection_id)
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

        tables_info.append({"name": full_name, "columns": columns, "num_columns": len(columns)})
    
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


async def load_agent_config_from_connection(
    db: AsyncSession,
    space_id: str,
    connection_id: str,
    crew_ids: Optional[List[str]] = None,
) -> AgentConfig:
    """
    Carrega TableMetadata e monta AgentConfig automaticamente para uma conexão.
    Compatível com schema real do banco (usa SQL raw).
    
    Args:
        db: Sessão do banco de dados
        space_id: ID do espaço
        connection_id: ID da conexão
        crew_ids: Lista opcional de crew_ids para filtrar por permissões do usuário
    """
    log_event(
        "load_agent_config_start",
        {
            "space_id": space_id,
            "connection_id": connection_id,
            "crew_ids": crew_ids,
        },
    )

    # Prefer backend-native catalog (poc backend writes to connection_metadata.tables).
    # This avoids relying on the AI Engine's legacy `table_metadata` table, which may not exist in the same DB.
    try:
        result = await db.execute(
            text("SELECT tables FROM connection_metadata WHERE connection_id = CAST(:cid AS uuid) LIMIT 1"),
            {"cid": connection_id},
        )
        tables_json = result.scalar_one_or_none()

        if isinstance(tables_json, list) and len(tables_json) > 0:
            # Load connection config for project_id fallback
            conn_result = await db.execute(
                text("SELECT config FROM data_connections WHERE id = :id"),
                {"id": connection_id},
            )
            row = conn_result.first()
            config = row[0] if row else {}
            if isinstance(config, str):
                config = json.loads(config)
            elif config is None:
                config = {}

            project_id = None
            if isinstance(config, dict):
                project_id = config.get("project_id") or config.get("gcp_project_id")

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
                logical_name = (
                    t.get("logical_name") 
                    or _normalize_logical_name(name)
                )
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
                                "type": str(c.get("type") or c.get("data_type") or "STRING"),
                                "nullable": bool(c.get("nullable", True)),
                            }
                        )

                table_schemas.append(
                    TableSchema(
                        logical_name=logical_name,
                        physical_name=physical_name,
                        columns=columns,
                    )
                )

            if table_schemas:
                agent = AgentConfig(
                    id=f"agent-conn-{connection_id}",
                    name=f"Agent for connection {connection_id}",
                    tables=table_schemas,
                )
                log_event(
                    "load_agent_config_from_connection_metadata",
                    {
                        "space_id": space_id,
                        "connection_id": connection_id,
                        "num_tables": len(table_schemas),
                    },
                )
                return agent
    except Exception as e:
        log_event(
            "load_agent_config_connection_metadata_error",
            {"space_id": space_id, "connection_id": connection_id, "error": str(e)[:500]},
        )

    # Backend-compatible mode: do NOT fall back to the legacy `table_metadata` table.
    # In this repo, the backend is the source-of-truth and stores the catalog in
    # `connection_metadata.tables` (JSON). If it's missing/empty, treat it as "no catalog yet".
    raise HTTPException(
        status_code=404,
        detail="No catalog found in connection_metadata.tables for this connection. "
        "Please synchronize the connection in the backend and try again.",
    )
    
    # Construir query SQL com filtro de permissões
    query_sql = """
        SELECT table_name, column_name, data_type, is_nullable
        FROM table_metadata
        WHERE space_id = :space_id AND data_connection_id = :conn_id
    """
    query_params = {"space_id": space_id, "conn_id": connection_id}
    
    # Adicionar filtro de permissões se crew_ids fornecidos
    if crew_ids:
        query_sql += " AND (crew_id IS NULL OR crew_id = ANY(:crew_ids))"
        query_params["crew_ids"] = crew_ids
    else:
        # Se não há crew_ids, mostrar apenas dados públicos (crew_id IS NULL)
        query_sql += " AND crew_id IS NULL"
    
    query_sql += " ORDER BY table_name, column_name"
    
    # Buscar metadados via SQL direto (compatível com UUID)
    db_result = await db.execute(
        text(query_sql),
        query_params
    )
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
            detail=f"No metadata found for this connection. Please execute table discovery first."
        )
    
    # Agrupar por tabela
    tables: dict[str, list] = {}
    for row in result:
        table_name = row[0]
        if table_name not in tables:
            tables[table_name] = []
        tables[table_name].append({
            "column_name": row[1],
            "data_type": row[2] or "STRING",
            "is_nullable": row[3] or False
        })
    
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
            "silver_web_data_enriquecido"
        ]
        if table_name in web_tables:
            return "data-mesh-gcp.web_silver"
        
        # Usar dataset do config da conexão
        # Fallback genérico: usar o dataset configurado ou None (será tratado apropriadamente)
        dataset = conn_config.get("dataset")
        # Se já tem projeto, usar direto; senão, adicionar projeto
        if "." in dataset and not dataset.startswith("data-mesh-gcp."):
            return dataset
        return dataset
    
    # Buscar config da conexão
    conn_result = await db.execute(
        text("SELECT config FROM data_connections WHERE id = :id"),
        {"id": connection_id}
    )
    row = conn_result.first()
    config = row[0] if row else {}
    if isinstance(config, str):
        config = json.loads(config)
    elif config is None:
        config = {}
    
    log_event(
        "load_agent_config_connection_config",
        {
            "connection_id": connection_id,
            "config_dataset": config.get("dataset") if isinstance(config, dict) else None,
            "config_keys": list(config.keys()) if isinstance(config, dict) else [],
        },
    )
    
    # Criar TableSchemas
    table_schemas: list[TableSchema] = []
    for tname, cols in tables.items():
        dataset = detect_dataset(tname, config)
        physical_name = f"{dataset}.{tname}" if "." not in tname else tname
        
        # Normalizar logical_name para nome amigável (remove prefixos/sufixos)
        logical_name = _normalize_logical_name(tname)
        
        log_event(
            "load_agent_config_table_schema",
            {
                "connection_id": connection_id,
                "table_name": tname,
                "logical_name": logical_name,
                "physical_name": physical_name,
                "dataset": dataset,
                "num_columns": len(cols),
            },
        )
        
        schema = TableSchema(
            logical_name=logical_name,
            physical_name=physical_name,
            columns=[
                {
                    "name": c["column_name"],
                    "type": c["data_type"],
                    "nullable": c["is_nullable"]
                }
                for c in cols
            ],
        )
        table_schemas.append(schema)
    
    agent = AgentConfig(
        id=f"agent-conn-{connection_id}",
        name=f"Agent for connection {connection_id}",
        tables=table_schemas,
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


@router.post("/{connection_id}/query", response_model=QueryResponse)
async def query_connection(
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
            status_code=400,
            detail="space_id é obrigatório no body da requisição"
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
    from core.security.semantic_classifier import _create_openai_client
    from core.i18n.i18n import detect_language, get_message
    
    # Criar cliente OpenAI para avaliação de segurança
    llm_client_for_security = _create_openai_client()
    
    # Avaliação consolidada: PII + Injection + Escalation + Auditoria
    security_report = await AuditManager.evaluate_prompt(
        question=body.question,
        user_id=body.user_id,
        connection_id=connection_id,
        thread_id=body.thread_id,
        llm_client=llm_client_for_security
    )
    
    # Detectar idioma para validação
    try:
        lang = detect_language(body.question or "")
    except:
        lang = "en"
    
    # ✅ LANGUAGE VALIDATION: Only accept English questions
    if lang != "en":
        log_event(
            "non_english_question_rejected",
            {
                "connection_id": connection_id,
                "user_id": str(body.user_id) if body.user_id else None,
                "detected_language": lang,
                "question_preview": body.question[:100] if body.question else ""
            }
        )
        
        return QueryResponse(
            answer="I only understand questions in English. Please ask your question in English.",
            sql=None,
            data=[],
            meta=QueryResultMeta(num_rows=0),
            has_error=True,
            error_code="language_not_supported"
        )
    
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
            progressive_escalation_detected=(security_report.blocked_by == "PROGRESSIVE_ESCALATION"),
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
            )
        )

    # Variáveis para compatibilidade com o resto da função
    pii_detected_in_prompt = security_report.security_status == "FLAGGED" or "pii" in security_report.scan_details
    prompt_injection_detected = False
    prompt_injection_pattern = None
    
    # ✅ FIM DA CAMADA DE SEGURANÇA UNIFICADA
    pii_detected_in_response = False

    pii_blocked = False
    thread_id = body.thread_id or f"{body.user_id or 'anon'}-{connection_id}"
    esc_info = security_report.scan_details.get("escalation", {})
    escalation_score = esc_info.get("score", 0.0)
    escalation_detected = security_report.blocked_by == "PROGRESSIVE_ESCALATION" or security_report.security_status == "FLAGGED"
    escalation_reason = esc_info.get("reason")
    # Verificar se conexão existe
    result = await db.execute(
        # Usar connector_id como alias para type para ser compatível com schemas antigos
        text("SELECT id, name, connector_id AS type, config FROM data_connections WHERE id = :id"),
        {"id": connection_id}
    )
    conn_result = result.first()
    
    if not conn_result:
        raise HTTPException(status_code=404, detail=f"Conexão {connection_id} não encontrada")
    
    # Resolver crew_ids do usuário baseado no contexto (personal vs collaborative)
    crew_ids = body.crew_ids or []
    if body.user_id:
        try:
            from uuid import UUID
            u_id = UUID(body.user_id) if body.user_id and len(body.user_id) == 36 else None
            s_id = UUID(body.space_id) if body.space_id and len(body.space_id) == 36 else None
            
            resolved_crew_ids = await resolve_crew_ids_for_context(
                db=db,
                user_id=u_id,
                space_id=s_id,
                request_crew_ids=body.crew_ids,
                is_personal=getattr(body, 'is_personal', False)
            )
            crew_ids = [str(crew_id) for crew_id in resolved_crew_ids]
            log_event(
                "api_query_connection_resolved_crew_ids",
                {
                    "connection_id": connection_id,
                    "user_id": body.user_id,
                    "space_id": body.space_id,
                    "is_personal": getattr(body, 'is_personal', False),
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
            status_code=500,
            detail=f"Erro ao carregar configuração do agente: {str(e)}"
        )

    # Fast-path answers for catalog questions (avoid LLM/SQL for simple metadata requests).
    # This makes the UX consistent in both Portuguese and English.
    try:
        import re

        q_raw = (body.question or "").strip()
        q = q_raw.lower()
        tables = agent_config.tables or []
        logical_tables = [t.logical_name for t in tables if getattr(t, "logical_name", None)]

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
        
        # Log available tables for debug
        print(f"DEBUG: Available Logical Tables: {logical_tables}")

    except Exception:
        # Never fail the main query path due to these heuristics.
        pass
    
    # Criar DataSource da conexão
    class TempDataConnection:
        def __init__(self, id, name, type, config):
            self.id = id
            self.name = name
            self.type = type
            self.config = config if isinstance(config, dict) else json.loads(config) if isinstance(config, str) else {}
    
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
    
    data_conn = TempDataConnection(
        id=str(conn_result[0]),
        name=conn_result[1],
        type=conn_result[2] or "bigquery",
        config=conn_config
    )
    
    try:
        data_source = DataSourceFactory.build_from_dataconnection(data_conn)
    except Exception as e:
        import traceback
        error_detail = f"Erro ao criar DataSource: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(
            status_code=500,
            detail=error_detail
        )
    
    # LLMs usando factory centralizado
    llm_orchestrator = create_llm_orchestrator()
    llm_specialist = create_llm_specialist()
    llm_formatter = create_llm_formatter()
    
    # Provider de embeddings (RAG) usando factory centralizado
    embedding_provider = create_embedding_provider()
    
    # Buscar contexto RAG com crew_ids resolvidos
    retrieval_context: list[str] = []
    try:
        retrieval_context = await build_retrieval_context_for_question(
            db=db,
            embedding_provider=embedding_provider,
            space_id=body.space_id,
            crew_ids=crew_ids if crew_ids else None,
            question=body.question,
            top_k=10,
        )
    except Exception:
        # Se RAG falhar, continua sem contexto
        retrieval_context = []
    
    # Executar agente
    try:
        from core.agents.generic_sql_agent import build_generic_sql_graph
        
        state = {
            "question": body.question,
            "user_id": body.user_id,
            "space_id": body.space_id,
            "crew_ids": crew_ids,
            # User context fields (from UserContext schema)
            # NOTE: Backend should send these values; using defaults until backend integration is complete
            "platform_role": getattr(body, "platform_role", None) or "user",  # admin | user | viewer
            "crew_role": getattr(body, "crew_role", None) or "guest",         # commander | navigator | explorer | guest
            "locale": getattr(body, "locale", None) or "en",
            "permissions": getattr(body, "permissions", None) or [],
            "retrieval_context": retrieval_context,
            # Configurações dinâmicas da IA
            "instructions": body.instructions,
            "creativity": body.creativity,
            "length": body.length,
            "response_format": body.response_format,
            "sql_instructions": body.sql_instructions,
            "selected_datasets": body.selected_datasets,
            # ✅ NOVO: Configuração de segurança dinâmica (RLS, colunas, etc.)
            # Enviada pelo backend para cada usuário/space/crew
            "security_config": body.security_config,
        }
        
        # Criar factory que retorna uma nova sessão (não reutilizar a sessão do FastAPI)
        def db_session_factory():
            return SyncSessionLocal()
        
        app = build_generic_sql_graph(
            agent_config=agent_config,
            data_source=data_source,
            db_session_factory=db_session_factory,
            embedding_provider=embedding_provider,
            llm_orchestrator=llm_orchestrator,
            llm_specialist=llm_specialist,
            llm_formatter=llm_formatter,
        )
        
        # thread_id já definido acima (progressive escalation)
        final_state = app.invoke(
            state,
            config={"configurable": {"thread_id": thread_id}},
        )
        
    except Exception as e:
        import traceback
        error_detail = str(e)
        logger.error(f"Erro ao executar agente: {error_detail}\n{traceback.format_exc()}")
        
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
                detected_language=lang,
                error="technical_error",
                num_rows=0
            )
        )
    
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
    if sql:
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
            max_columns=10,
            max_group_by=3
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
                }
            )
            
            # User-friendly message (NO technical/SQL details exposed)
            raise HTTPException(
                status_code=500,
                detail="I couldn't process your request. Please try rephrasing your question."
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
        from_match = re.search(r'FROM\s+([^\s,\(\)]+)', sql, re.IGNORECASE)
        if from_match:
            table_from_sql = from_match.group(1).strip()
            # Remove schema prefix if present (e.g., "dataset.table" -> "table")
            if '.' in table_from_sql:
                table_from_sql = table_from_sql.split('.')[-1]
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
    chosen_datasets = chosen_tables if chosen_tables else ([chosen_table] if chosen_table else [])
    
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
    
    data_sample = data[:15] if isinstance(data, list) else []
    
    # ✅ CAMADA 4: Detecção de PII na resposta
    from core.security.pii_scanner import (
        scan_text_for_pii,
        scan_data_for_pii,
        should_allow_pii_in_aggregate_context,
        _is_aggregated_sql,
    )
    
    pii_response_text_result = scan_text_for_pii(answer) if answer else None
    # IMPORTANTE: Escanear dados originais ANTES de filtrar para verificação de contexto agregado
    # Usar dados completos (até 100 linhas) para detecção PII, mas apenas primeiras 15 para resposta
    data_for_pii_scan = data[:100] if isinstance(data, list) else []
    pii_response_data_result = scan_data_for_pii(data_for_pii_scan) if data_for_pii_scan else None
    
    pii_detected_in_response = (
        (pii_response_text_result and pii_response_text_result.detected) or
        (pii_response_data_result and pii_response_data_result.detected)
    )
    
    # Verificar se PII deve ser permitido em contexto agregado (análise de negócio genérica)
    allow_pii_in_text = False
    allow_pii_in_data = False
    
    if pii_response_text_result and pii_response_text_result.should_block:
        allow_pii_in_text = should_allow_pii_in_aggregate_context(
            question=body.question or "",
            sql=sql,
            data=data_sample,
            pii_detection_result=pii_response_text_result,
        )
    
    if pii_response_data_result and pii_response_data_result.should_block:
        # Usar dados originais (não filtrados) para verificação de contexto agregado
        allow_pii_in_data = should_allow_pii_in_aggregate_context(
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
    
    if sql:
        sql_upper = sql.upper()
        
        # Detectar agregação
        has_group_by = 'GROUP BY' in sql_upper
        has_aggregation = any(func in sql_upper for func in ['SUM(', 'AVG(', 'COUNT(', 'MAX(', 'MIN('])
        is_aggregated_query = has_group_by or has_aggregation
        
        # Detectar LIMIT baixo (amostra)
        import re
        limit_match = re.search(r'LIMIT\s+(\d+)', sql_upper)
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
                   "is_sample": is_sample_query
                }
            )
        
        if not allow_pii_in_text:
            # Substituir resposta por mensagem genérica
            answer = "I cannot display sensitive personal information in the results."
            pii_blocked = True
    
    if pii_response_data_result and pii_response_data_result.should_block and not allow_pii_in_data:
        # Permitir dados se for query agregada OU amostra (LIMIT baixo)
        if is_aggregated_query:
            log_event(
                "pii_allowed_aggregated_context",
                {
                    "connection_id": connection_id,
                    "has_group_by": has_group_by,
                    "has_aggregation": has_aggregation,
                    "pii_types": [t.value for t in pii_response_data_result.pii_types] if pii_response_data_result.pii_types else [],
                    "sql_preview": sql[:200] if sql else None,
                }
            )
            pii_blocked = False  # Não bloquear dados agregados
        elif is_sample_query:
            log_event(
                "pii_allowed_sample_query",
                {
                    "connection_id": connection_id,
                    "limit_value": limit_value if 'limit_value' in locals() else None,
                    "pii_types": [t.value for t in pii_response_data_result.pii_types] if pii_response_data_result.pii_types else [],
                    "sql_preview": sql[:200] if sql else None,
                }
            )
            pii_blocked = False  # Não bloquear amostras (LIMIT baixo)
        else:
            # Bloquear apenas queries sem agregação E sem LIMIT (ou LIMIT muito alto)
            log_event(
                "pii_blocked_non_aggregated",
                {
                    "connection_id": connection_id,
                    "pii_types": [t.value for t in pii_response_data_result.pii_types] if pii_response_data_result.pii_types else [],
                    "sql_preview": sql[:200] if sql else None,
                }
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
        num_rows=len(data),
        error=error,
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
    
    return QueryResponse(
        answer=answer,
        data_sample=data_sample,
        meta=meta,
    )


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
            yield f"data: {json.dumps({'type': 'error', 'message': error})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        # ✅ CAMADA 2: CAMADA DE SEGURANÇA UNIFICADA (Audit Manager)
        from core.security.audit_manager import AuditManager
        from core.security.semantic_classifier import _create_openai_client
        
        # Criar cliente OpenAI para avaliação de segurança
        llm_client_for_security = _create_openai_client()
        
        # Avaliação consolidada: PII + Injection + Escalation + Auditoria
        security_report = await AuditManager.evaluate_prompt(
            question=body.question,
            user_id=body.user_id,
            connection_id=connection_id,
            thread_id=body.thread_id,
            llm_client=llm_client_for_security
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
                progressive_escalation_detected=(security_report.blocked_by == "PROGRESSIVE_ESCALATION"),
                progressive_escalation_score=int(esc_info.get("score", 0)),
            )
            
            # Enviar como resposta normal para o frontend exibir corretamente
            yield f"data: {json.dumps({'type': 'chunk', 'content': message})}\n\n"
            yield f"data: {json.dumps({'type': 'meta', 'meta': {'detected_language': lang, 'error': error_code}, 'data_sample': []})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        # Verificar se conexão existe
        result = await db.execute(
            text("SELECT id, name, connector_id AS type, config FROM data_connections WHERE id = :id"),
            {"id": connection_id}
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
                    is_personal=getattr(body, 'is_personal', False)
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
        
        # Carregar AgentConfig
        try:
            agent_config = await load_agent_config_from_connection(
                db=db,
                space_id=body.space_id,
                connection_id=connection_id,
                crew_ids=crew_ids if crew_ids else None,
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
            config=conn_config
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
        
        # Buscar contexto RAG
        retrieval_context: list[str] = []
        try:
            retrieval_context = await build_retrieval_context_for_question(
                db=db,
                embedding_provider=embedding_provider,
                space_id=body.space_id,
                crew_ids=crew_ids if crew_ids else None,
                question=body.question,
                top_k=10,
            )
        except Exception:
            retrieval_context = []
        
        # Executar agente até o specialist (sem formatter ainda)
        try:
            from core.agents.generic_sql_agent import build_generic_sql_graph
            from core.llm.formatter import _ensure_language, _serialize_for_json, _compute_basic_stats, _stream_llm, _extract_topic
            
            state = {
                "question": body.question,
                "user_id": body.user_id,
                "space_id": body.space_id,
                "crew_ids": crew_ids,
                "retrieval_context": retrieval_context,
                # Configurações dinâmicas da IA
                "instructions": body.instructions,
                "creativity": body.creativity,
                "length": body.length,
                "response_format": body.response_format,
                "sql_instructions": body.sql_instructions,
                "selected_datasets": body.selected_datasets,
                # ✅ NOVO: Configuração de segurança dinâmica (RLS, colunas, etc.)
                "security_config": body.security_config,
            }
            
            def db_session_factory():
                return SyncSessionLocal()
            
            app = build_generic_sql_graph(
                agent_config=agent_config,
                data_source=data_source,
                db_session_factory=db_session_factory,
                embedding_provider=embedding_provider,
                llm_orchestrator=llm_orchestrator,
                llm_specialist=llm_specialist,
                llm_formatter=llm_formatter,
            )
            # thread_id já definido acima
            
            # Executar até o specialist (orchestrator -> specialist)
            # Não executamos o formatter ainda, vamos fazer streaming dela
            final_state = None
            for chunk in app.stream(state, config={"configurable": {"thread_id": thread_id}}):
                for node_name, node_state in chunk.items():
                    if node_name in ["orchestrator", "specialist"]:
                        final_state = node_state
                        # Enviar progresso e eventos específicos
                        if node_name == "orchestrator":
                            yield f"data: {json.dumps({'type': 'progress', 'stage': 'orchestrator', 'message': 'Analisando pergunta...'})}\n\n"
                            
                            # Enviar evento quando datasets são escolhidos
                            chosen_table = node_state.get("chosen_table")
                            chosen_tables = node_state.get("chosen_tables")
                            if chosen_table or chosen_tables:
                                chosen_datasets = chosen_tables if chosen_tables else ([chosen_table] if chosen_table else [])
                                yield f"data: {json.dumps({'type': 'datasets_selected', 'datasets': chosen_datasets})}\n\n"
                        
                        elif node_name == "specialist":
                            yield f"data: {json.dumps({'type': 'progress', 'stage': 'specialist', 'message': 'Executando query...'})}\n\n"
                            
                            # Enviar evento quando SQL é gerado
                            sql = node_state.get("sql")
                            if sql:
                                # ✅ CAMADA 3: Validar SQL gerado antes de expor ao cliente
                                allowed_tables = [t.physical_name for t in agent_config.tables]
                                allowed_tables.extend([t.logical_name for t in agent_config.tables])
                                connection_type = conn_result[2] or "bigquery"
                                validator = AdvancedSQLValidator(
                                    allowed_tables=allowed_tables,
                                    allowed_columns=None,
                                    max_limit=5000,
                                    max_columns=10,
                                    max_group_by=3,
                                )
                                ok, validation_error = validator.validate(sql, connection_type)
                                if not ok:
                                    log_event(
                                        "ai_generated_invalid_sql_stream",
                                        {
+                                           "connection_id": connection_id,
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
                                        execution_time_ms=int((time.time() - start_time) * 1000),
                                        has_error=True,
                                        error_message=validation_error,
                                        progressive_escalation_score=escalation_score,
                                        progressive_escalation_detected=escalation_detected,
                                    )
                                    
                                    # Mensagem amigável para erro técnico no streaming
                                    msg = f"{get_message('TECHNICAL_ERROR', lang)} | DEBUG: {final_state.get('error')}"
                                    yield f"data: {json.dumps({'type': 'error', 'message': msg})}\n\n"
                                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                                    return

                                yield f"data: {json.dumps({'type': 'sql_generated', 'sql': sql})}\n\n"
            
            if not final_state:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Erro ao executar agente'})}\n\n"
                return
            
            # Se houve erro no agente, enviar amigável e terminar
            if final_state.get("error"):
                lang = _ensure_language(body.question, final_state.get("detected_language"))
                msg = f"{get_message('TECHNICAL_ERROR', lang)} | DEBUG: {final_state.get('error')}"
                yield f"data: {json.dumps({'type': 'chunk', 'content': msg})}\n\n"
                meta = {
                    "detected_language": lang,
                    "chosen_table": final_state.get("chosen_table"),
                    "chosen_datasets": final_state.get("chosen_tables"),
                    "sql": final_state.get("sql"),
                    "title": final_state.get("generated_title"),  # ✅ NOVO: Título gerado dinamicamente
                    "num_rows": 0,
                    "error": str(final_state.get("error")),
                }
                yield f"data: {json.dumps({'type': 'meta', 'meta': meta, 'data_sample': []})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                return
            
            # Se não há dados, enviar amigável com tópico e terminar
            if not final_state.get("data"):
                lang = _ensure_language(body.question, final_state.get("detected_language"))
                topic = _extract_topic(body.question)
                msg = get_message("NO_DATA_FOUND", lang, topic=topic)
                yield f"data: {json.dumps({'type': 'chunk', 'content': msg})}\n\n"
                meta = {
                    "detected_language": lang,
                    "chosen_table": final_state.get("chosen_table"),
                    "sql": final_state.get("sql"),
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
            # lang = _ensure_language(question, detected_language) # Removed redundant call
            
            data_sample = data[:15]
            serialized_sample = _serialize_for_json(data_sample)
            sample_json = json.dumps(serialized_sample, ensure_ascii=False, indent=2)
            stats_text = _compute_basic_stats(data_sample)
            
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
                    "- Mention table names, column names, or database structure\n\n"
                    "YOU MUST:\n"
                    "- Only use the data provided in the results\n"
                    "- Answer ONLY in English - THIS IS A STRICT REQUIREMENT\n"
                    "- If data is insufficient, say 'Insufficient data to answer this question'\n"
                    "- Keep the answer concise and objective (maximum 4 sentences)\n\n"
                    "CRITICAL LANGUAGE REQUIREMENT:\n"
                    "- You MUST answer in English, even if the user question is in another language.\n"
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
                    "Explain the main insight(s) from this data in a concise way, "
                    "in English."
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
            
            chosen_datasets = chosen_tables if chosen_tables else ([chosen_table] if chosen_table else [])
            
            meta = {
                "detected_language": lang,
                "chosen_table": chosen_table,
                "chosen_datasets": chosen_datasets if chosen_datasets else None,
                "sql": sql,
                "num_rows": len(data),
                "error": None,
            }
            
            yield f"data: {json.dumps({'type': 'meta', 'meta': meta, 'data_sample': data_sample})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

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
            msg = f"{get_message('TECHNICAL_ERROR', lang)} | DEBUG: {error_detail}"
            yield f"data: {json.dumps({'type': 'error', 'message': msg})}\n\n"
            log_event(
                "api_query_connection_stream_error",
                {
                    "connection_id": connection_id,
                    "error": error_detail,
                },
            )
    
    except Exception as e:
        msg = f"{get_message('TECHNICAL_ERROR', lang)} | DEBUG: {str(e)}"
        yield f"data: {json.dumps({'type': 'error', 'message': msg})}\n\n"


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
        }
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

def _compute_basic_stats(data: List[Dict[str, Any]]) -> str:
    """Compute basic stats for context."""
    if not data:
        return "No data."
    
    first_row = data[0]
    total_cols = len(first_row.keys())
    
    # Identify numeric columns
    numeric_cols = []
    for k, v in first_row.items():
        if isinstance(v, (int, float, Decimal)):
            numeric_cols.append(k)
            
    stats = []
    for col in numeric_cols[:3]: # Limit to top 3 numeric
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
        return ValidateSQLResponse(
            is_valid=False,
            error=error
        )
    
    # ✅ CAMADA 2: Validação regex (rápida)
    from core.sql.validator import validate_sql_strict
    is_valid, error = validate_sql_strict(body.sql)
    if not is_valid:
        return ValidateSQLResponse(
            is_valid=False,
            error=error
        )
    
    try:
        # Verificar se conexão existe
        result = await db.execute(
            text("SELECT id, name, connector_id AS type, config FROM data_connections WHERE id = :id"),
            {"id": connection_id}
        )
        conn_result = result.first()
        
        if not conn_result:
            return ValidateSQLResponse(
                is_valid=False,
                error="Conexão não encontrada"
            )
        
        # ✅ CAMADA 3: Resolver permissões
        crew_ids = body.crew_ids or []
        if body.user_id and body.space_id:
            try:
                resolved_crew_ids = await resolve_crew_ids_for_context(
                    db=db,
                    user_id=UUID(body.user_id),
                    space_id=UUID(body.space_id),
                    request_crew_ids=body.crew_ids,
                    is_personal=bool(getattr(body, 'is_personal', False))
                )
                crew_ids = [str(cid) for cid in resolved_crew_ids]
            except Exception as e:
                log_event(
                    "validate_sql_resolve_crew_ids_error",
                    {
                        "connection_id": connection_id,
                        "user_id": body.user_id,
                        "error": str(e)[:200],
                    }
                )
                crew_ids = []
        
        # Obter tabelas permitidas
        allowed_tables = await _get_allowed_tables_for_validation(
            db=db,
            connection_id=connection_id,
            space_id=body.space_id or "",
            crew_ids=crew_ids
        )
        
        if not allowed_tables:
            return ValidateSQLResponse(
                is_valid=False,
                error="No tables available for this connection"
            )
        
        # ✅ CAMADA 4: Validação AST + Permissões
        connection_type = (conn_result[2] if conn_result else "bigquery") or "bigquery"
        
        validator = AdvancedSQLValidator(
            allowed_tables=allowed_tables,
            allowed_columns=None,  # Opcional: filtrar colunas também
            max_limit=100,
            max_columns=10,
            max_group_by=3
        )
        
        is_valid, error = validator.validate(body.sql, connection_type)
        if not is_valid:
            return ValidateSQLResponse(
                is_valid=False,
                error=error
            )
        
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
            config=conn_config
        )
        
        try:
            data_source = DataSourceFactory.build_from_dataconnection(data_conn)
        except Exception as e:
            return ValidateSQLResponse(
                is_valid=False,
                error=f"Erro ao criar DataSource: {str(e)}"
            )
        
        # Executar SQL com LIMIT 5 para preview
        sql = body.sql.strip().rstrip(';')
        
        # Validar que SQL não está vazio após strip
        if not sql:
            return ValidateSQLResponse(
                is_valid=False,
                error="SQL não pode ser vazio"
            )
        
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
                    is_valid=False,
                    error=f"Violação de segurança: {security_error}"
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
                    sample_json = json.dumps(serialized_sample, ensure_ascii=False, indent=2)
                    stats_text = _compute_basic_stats(data_sample)
                    
                    # 2. Criar contexto do sistema
                    system_msg = {
                        "role": "system",
                        "content": (
                            "You are a data analyst helper.\n"
                            "Your job is to explain the query results clearly and concisely.\n\n"
                            "RULES:\n"
                            "- Answer in English (always).\n"
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
                        {"connection_id": connection_id, "error": str(e)}
                    )
                    explanation = None

            return ValidateSQLResponse(
                is_valid=True,
                preview_data=data[:5],  # Máximo 5 linhas
                num_rows=len(data),
                execution_time_ms=execution_time_ms,
                columns=columns,
                explanation=explanation
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
            return ValidateSQLResponse(
                is_valid=False,
                error=error_msg
            )
        
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
            is_valid=False,
            error=f"Erro inesperado: {error_msg}"
        )
