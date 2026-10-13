# -*- coding: utf-8 -*-
"""Voltar a correr o SQL de uma resposta, de um widget ou de um achado.

── Porque é que isto existe ────────────────────────────────────────

> «Nunca guardamos as linhas do cliente. O ver a fonte, os widgets e os
>  achados voltam a correr o SQL contra a fonte do cliente quando se
>  abrem.» — decisão do Lucas, 13/10/2026

Até aqui a plataforma guardava as linhas: até 200 por resposta em
``ai_queries.data_sample``, um retrato em cada widget, 15 linhas em cada
achado e 100 em cada corrida de agente. Era a frase comercial («não
copiamos os seus dados») a ser falsa por desenho.

O backend passa a guardar só a DEFINIÇÃO (o SQL, a ligação, o contexto) e
pede aqui as linhas quando alguém abre a fonte. Esta rota é essa porta.

── A mesma porta, as mesmas regras ─────────────────────────────────

O argumento contra reexecutar era bom: «correr SQL guardado é abrir uma
segunda porta para os dados, que teria de repetir TODAS as verificações
da primeira». Por isso esta rota não inventa regra nenhuma:

* **só SELECT** — `validate_sql_strict`, o mesmo do `/query`;
* **só as tabelas que QUEM ABRE pode ver** — o backend calcula-as com o
  mesmo `get_authorized_tables` que o `/ai/query` usa, para a pessoa que
  está a abrir (não para quem perguntou), e manda-as por ligação. Aqui
  valida-se com o mesmo `AdvancedSQLValidator`. Sem lista, nada passa:
  **fail-closed**;
* **o mesmo RLS** — `inject_row_filters_in_sql` +
  `validate_sql_against_security` quando há `security_config`;
* **a base do cliente** — a sessão vem do `get_db`, que segue o
  `X-Tenant-Slug` como todas as outras rotas.

Uma tabela que existe no catálogo mas que a pessoa não pode ver dá
**403**. Um SQL que não se consegue voltar a correr (a junção em memória
de várias fontes, uma tabela que saiu do catálogo, uma fonte que não é
SQL) dá **422** com o código `nao_reexecutavel` — e o cliente mostra a
resposta sem tabela, em vez de inventar uma.

── Nunca grava nada ────────────────────────────────────────────────

Nem linhas, nem amostras, nem o resultado em cache. Lê, devolve, esquece.
A cache curta (≤ 5 min, por pessoa) é do backend e vive no Redis com
prazo — não aqui.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging_utils import log_event
from core.security.security_config import SecurityConfig
from db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connections", tags=["dados-ao-vivo"])

#: O tecto de linhas por pedido. O «ver a fonte» pede 200; o CSV pede mais.
#: Acima disto já não é «confirmar a resposta», é exportar a base.
MAX_LINHAS = 10_000
#: O mesmo tecto por célula do stream: um texto de 2 MB numa célula não
#: ajuda ninguém a confirmar um número.
TECTO_CELULA = 2048
#: Uma consulta de confirmação não pode prender um worker para sempre.
PRAZO_SEGUNDOS = 60

#: Fontes onde «o SQL» não existe: não há nada para voltar a correr.
DIALECTOS_SEM_SQL = {"nosql", "api", "mongodb", "dynamodb", "elasticsearch"}


class PedidoDeReexecucao(BaseModel):
    sql: str = Field(..., min_length=1, max_length=10_000)
    user_id: str
    space_id: Optional[str] = None
    #: As tabelas que QUEM ABRE pode ver, por ligação, calculadas pelo
    #: backend. Obrigatório: sem ele não há como decidir, e decide-se não.
    tabelas_autorizadas: Dict[str, List[str]] = Field(default_factory=dict)
    #: As outras ligações do âmbito da pergunta original (multi-fonte).
    connection_ids: Optional[List[str]] = None
    #: A mesma regra da pergunta original (RLS, colunas). Tipada como no
    #: `/query`: chegava como dict e o `inject_row_filters_in_sql` lê
    #: `.tables` — todas as reexecuções com regra davam 500 (13/10/2026).
    security_config: Optional[SecurityConfig] = None
    max_rows: int = Field(200, ge=1, le=MAX_LINHAS)


class ResultadoDaReexecucao(BaseModel):
    columns: List[str]
    rows: List[List[Any]]
    row_count: int
    truncated: bool
    connection_id: str
    executed_at: str


# ─── Peças puras (testáveis sem base) ────────────────────────────────


def _nome_fisico(tabela: Dict[str, Any], project_id: Optional[str]) -> Optional[str]:
    """O nome com que o SQL se refere à tabela — a mesma regra do
    `load_agent_config_from_connection`."""
    nome = str(tabela.get("name") or "").strip()
    if not nome:
        return None
    esquema = str(tabela.get("schema") or "").strip()
    if esquema and project_id:
        return f"{project_id}.{esquema}.{nome}"
    if esquema:
        return f"{esquema}.{nome}"
    return nome


def catalogo_permitido(
    catalogo: Dict[str, List[Dict[str, Any]]],
    projectos: Dict[str, Optional[str]],
    autorizadas: Dict[str, List[str]],
) -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]]]:
    """(todas, permitidas): nomes físicos por ligação.

    `todas` é o catálogo inteiro do âmbito (para distinguir «não pode ver»
    de «não existe»); `permitidas` é só o que a lista do backend autoriza
    — por NOME da tabela, que é como o `get_authorized_tables` a devolve.
    Uma ligação sem entrada na lista não tem nada permitido.
    """
    todas: Dict[str, Set[str]] = {}
    permitidas: Dict[str, Set[str]] = {}
    for cid, tabelas in catalogo.items():
        nomes_ok = {str(n).strip() for n in (autorizadas.get(cid) or []) if n}
        todas[cid] = set()
        permitidas[cid] = set()
        for t in tabelas or []:
            if not isinstance(t, dict):
                continue
            fisico = _nome_fisico(t, projectos.get(cid))
            if not fisico:
                continue
            todas[cid].add(fisico)
            if str(t.get("name") or "").strip() in nomes_ok:
                permitidas[cid].add(fisico)
    return todas, permitidas


def tabelas_do_sql(sql: str) -> Set[str]:
    """As tabelas que o SQL lê (sem as CTEs), pelo mesmo parser do validador."""
    import sqlparse

    from core.sql.validator_advanced import AdvancedSQLValidator

    v = AdvancedSQLValidator(allowed_tables=[])
    try:
        stmt = sqlparse.parse(sql)[0]
    except Exception:
        return set()
    ctes = v._extract_ctes(stmt)
    return {t for t in v._extract_tables(stmt) if t not in ctes}


def ligacao_das_tabelas(sql: str, por_ligacao: Dict[str, Set[str]]) -> Set[str]:
    """Em que ligações vivem as tabelas que o SQL lê."""
    from core.sql.validator_advanced import AdvancedSQLValidator

    v = AdvancedSQLValidator(allowed_tables=[])
    ligacoes: Set[str] = set()
    for tabela in tabelas_do_sql(sql):
        variantes = v._table_variants(tabela)
        for cid, nomes in por_ligacao.items():
            if variantes & v._expand_allowed_tables(list(nomes)):
                ligacoes.add(cid)
    return ligacoes


def validar(
    sql: str, permitidas: List[str], dialecto: str
) -> Tuple[bool, Optional[str]]:
    """O MESMO validador do `/query` (AST + tabelas), com as tabelas dadas."""
    from core.sql.validator_advanced import AdvancedSQLValidator

    return AdvancedSQLValidator(
        allowed_tables=permitidas, allowed_columns=None, max_limit=5000
    ).validate(sql, dialecto)


def com_tecto(sql: str, n: int, dialecto: str) -> str:
    """Envolve o SQL num tecto de `n` linhas, no dialecto da fonte.

    Pede-se `n + 1` por fora para saber se cortou sem contar a tabela toda.
    O SQL de dentro já foi validado; o envelope é nosso e não lê nada novo.
    """
    corpo = sql.strip().rstrip(";").strip()
    d = (dialecto or "").lower()
    if d == "sqlserver":
        return f"SELECT TOP {n} * FROM ({corpo}) AS sky_fonte"
    if d == "oracle":
        return f"SELECT * FROM ({corpo}) sky_fonte WHERE ROWNUM <= {n}"
    return f"SELECT * FROM ({corpo}) AS sky_fonte LIMIT {n}"


def _valor(v: Any) -> Any:
    if v is None or isinstance(v, (bool, int, float, str)):
        if isinstance(v, str) and len(v) > TECTO_CELULA:
            return v[:TECTO_CELULA] + "…"
        return v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(v)).decode("ascii")
    try:
        json.dumps(v)
        return v
    except Exception:
        return str(v)


def compactar(
    dados: List[Dict[str, Any]], n: int
) -> Tuple[List[str], List[List[Any]], bool]:
    """Colunas à parte, linhas como listas — a forma do evento `rows`."""
    if not dados:
        return [], [], False
    colunas = list(dados[0].keys())
    cortou = len(dados) > n
    linhas = [[_valor(linha.get(c)) for c in colunas] for linha in dados[:n]]
    return colunas, linhas, cortou


# ─── A rota ──────────────────────────────────────────────────────────


def _erro(status: int, codigo: str, mensagem: str) -> HTTPException:
    return HTTPException(
        status_code=status, detail={"code": codigo, "message": mensagem}
    )


async def _ler_catalogo(
    db: AsyncSession, ids: List[str]
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, Optional[str]], Dict[str, Any]]:
    """Catálogo, project_id e linha da ligação, para cada id do âmbito."""
    from core.security.config_decryption import decrypt_config

    catalogo: Dict[str, List[Dict[str, Any]]] = {}
    projectos: Dict[str, Optional[str]] = {}
    ligacoes: Dict[str, Any] = {}
    for cid in ids:
        linha = (
            await db.execute(
                text(
                    "SELECT id, name, connector_id, config FROM data_connections WHERE id = :id"
                ),
                {"id": cid},
            )
        ).first()
        if linha is None:
            continue
        cfg = linha[3]
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except json.JSONDecodeError:
                cfg = {}
        cfg = decrypt_config(cfg or {}) if isinstance(cfg, dict) else {}
        ligacoes[cid] = (str(linha[0]), linha[1], linha[2], cfg)
        projectos[cid] = cfg.get("project_id") or cfg.get("gcp_project_id")
        tabelas = (
            await db.execute(
                text(
                    "SELECT tables FROM connection_metadata "
                    "WHERE connection_id = CAST(:cid AS uuid) LIMIT 1"
                ),
                {"cid": cid},
            )
        ).scalar_one_or_none()
        if isinstance(tabelas, str):
            try:
                tabelas = json.loads(tabelas)
            except json.JSONDecodeError:
                tabelas = []
        catalogo[cid] = tabelas if isinstance(tabelas, list) else []
    return catalogo, projectos, ligacoes


def _fonte_de_dados(linha: Tuple[str, str, str, Dict[str, Any]]):
    from core.data_sources.factory import DataSourceFactory

    class _Ligacao:
        def __init__(self, id, name, type, config):
            self.id = id
            self.name = name
            self.type = type
            self.config = config

    cid, nome, tipo, cfg = linha
    return DataSourceFactory.build_from_dataconnection(
        _Ligacao(cid, nome, (tipo or "postgres"), cfg)
    )


@router.post("/{connection_id}/rerun", response_model=ResultadoDaReexecucao)
async def reexecutar(
    connection_id: str,
    corpo: PedidoDeReexecucao,
    db: AsyncSession = Depends(get_db),
) -> ResultadoDaReexecucao:
    """Corre outra vez o SQL guardado, só de leitura, com as tabelas de quem abre."""
    from core.sql.validator import validate_sql_strict

    ok, erro = validate_sql_strict(corpo.sql)
    if not ok:
        raise _erro(422, "sql_invalido", erro or "SQL inválido")

    ambito = [connection_id] + [
        c for c in (corpo.connection_ids or []) if c and c != connection_id
    ]
    catalogo, projectos, ligacoes = await _ler_catalogo(db, ambito)
    if connection_id not in ligacoes:
        raise _erro(404, "ligacao_inexistente", "Ligação não encontrada")

    todas, permitidas = catalogo_permitido(
        catalogo, projectos, corpo.tabelas_autorizadas
    )
    tipo_primario = (ligacoes[connection_id][2] or "postgres").lower()

    lista_permitida = sorted({n for nomes in permitidas.values() for n in nomes})
    valido, motivo = (
        validar(corpo.sql, lista_permitida, tipo_primario)
        if lista_permitida
        else (False, "Table not allowed")
    )
    if not valido:
        # Distinguir «não pode ver» de «não se consegue voltar a correr»:
        # contra o catálogo INTEIRO do âmbito, o mesmo SQL passaria?
        lista_toda = sorted({n for nomes in todas.values() for n in nomes})
        passaria = bool(lista_toda) and validar(corpo.sql, lista_toda, tipo_primario)[0]
        log_event(
            "rerun_sql_recusado",
            {
                "connection_id": connection_id,
                "user_id": corpo.user_id,
                "sem_acesso": passaria,
                "motivo": (motivo or "")[:200],
            },
        )
        if passaria:
            raise _erro(
                403, "sem_acesso", "Sem acesso a uma das tabelas desta consulta"
            )
        raise _erro(
            422,
            "nao_reexecutavel",
            motivo or "Esta consulta não se pode voltar a correr",
        )

    # Em que ligação corre. Uma só: um SQL que lê de duas bases era a
    # junção em memória (DuckDB) e não existe em nenhuma delas.
    onde = ligacao_das_tabelas(corpo.sql, permitidas)
    if len(onde) > 1:
        raise _erro(422, "nao_reexecutavel", "A consulta junta várias fontes")
    alvo = next(iter(onde)) if onde else connection_id

    try:
        fonte = _fonte_de_dados(ligacoes[alvo])
    except Exception as exc:  # noqa: BLE001
        from core.privacidade.registo import sem_credenciais

        logger.warning(
            "rerun_sql: fonte %s não montou: %s", alvo, sem_credenciais(str(exc))[:300]
        )
        raise _erro(502, "fonte_indisponivel", "A fonte de dados não respondeu")

    dialecto = getattr(getattr(fonte, "dialect", None), "value", None) or (
        ligacoes[alvo][2] or ""
    )
    if str(dialecto).lower() in DIALECTOS_SEM_SQL:
        raise _erro(422, "nao_reexecutavel", "Esta fonte não é SQL")

    sql = corpo.sql
    if corpo.security_config:
        from core.security.security_config import (
            inject_row_filters_in_sql,
            validate_sql_against_security,
        )

        sql = inject_row_filters_in_sql(sql, corpo.security_config)
        seguro, motivo_seg = validate_sql_against_security(
            sql, corpo.security_config, lista_permitida
        )
        if not seguro:
            raise _erro(403, "sem_acesso", motivo_seg or "Regra de segurança")

    envelope = com_tecto(sql, corpo.max_rows + 1, str(dialecto))
    try:
        dados = await asyncio.wait_for(
            asyncio.to_thread(fonte.run_query, envelope), timeout=PRAZO_SEGUNDOS
        )
    except asyncio.TimeoutError:
        raise _erro(504, "prazo", "A fonte de dados demorou demasiado")
    except Exception as exc:  # noqa: BLE001
        # O texto da excepção pode trazer literais do cliente: fica no
        # registo do servidor, não na resposta.
        from core.privacidade.registo import sem_credenciais, sem_literais

        logger.warning(
            "rerun_sql: a fonte recusou: %s",
            sem_literais(sem_credenciais(str(exc)))[:300],
        )
        raise _erro(502, "fonte_recusou", "A fonte de dados recusou a consulta")

    colunas, linhas, cortou = compactar(list(dados or []), corpo.max_rows)
    log_event(
        "rerun_sql_ok",
        {
            "connection_id": alvo,
            "user_id": corpo.user_id,
            "num_rows": len(linhas),
            "truncated": cortou,
        },
    )
    return ResultadoDaReexecucao(
        columns=colunas,
        rows=linhas,
        row_count=len(linhas),
        truncated=cortou,
        connection_id=alvo,
        executed_at=datetime.now(timezone.utc).isoformat(),
    )
