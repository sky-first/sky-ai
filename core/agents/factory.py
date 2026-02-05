# core/agents/factory.py
from __future__ import annotations

from typing import List, Dict, Any, Optional, Tuple, DefaultDict
from collections import defaultdict

from sqlalchemy.orm import Session

from core.agents.generic_sql_agent import (
    AgentConfig,
    TableSchema,
    TableColumn,
)
from core.auth.models import UserContext  # ajuste se o caminho for diferente
from core.logging_utils import log_event

from db.models import TableMetadata  # seu modelo de metadados de tabela


# ==================== HELPERS ====================

def _normalize_logical_name(table_name: str) -> str:
    """
    Converte um nome físico em um nome lógico amigável.
    Exemplo:
      'project.dataset.transactions_enriched' -> 'transactions'
      'silver_entities_enriched'             -> 'entities'
    Ajuste a lógica conforme seu padrão real de nomes.
    """
    if not table_name:
        return table_name

    name = table_name

    # remove schema se existir (ex: schema.table -> table)
    if "." in name:
        name = name.split(".")[-1]

    # remove prefixos comuns
    for prefix in ("silver_", "gold_", "bronze_", "dim_", "fact_"):
        if name.startswith(prefix):
            name = name[len(prefix):]

    # remove sufixos comuns
    for suffix in ("_enriquecido", "_enriched", "_tbl", "_table"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]

    return name


def _metadata_row_to_column(row: TableMetadata) -> TableColumn:
    """
    Converte uma linha de TableMetadata em um TableColumn.
    Pressupõe que TableMetadata tenha pelo menos:
      - column_name
      - data_type
      - is_nullable
      - description (opcional)
      - extra (JSON/dict com metadados extras)
    """
    extra: Dict[str, Any] = getattr(row, "extra", {}) or {}

    col: TableColumn = {
        "name": row.column_name,
        "type": row.data_type,
        "is_nullable": bool(getattr(row, "is_nullable", True)),
        "description": getattr(row, "description", None),
        "is_primary_key": bool(extra.get("is_primary_key") or extra.get("pk") or False),
        "is_foreign_key": bool(extra.get("is_foreign_key") or extra.get("fk") or False),
    }
    
    # Propagate temporal ranges if they exist
    if "min_date" in extra:
        col["min_date"] = extra["min_date"]
    if "max_date" in extra:
        col["max_date"] = extra["max_date"]
        
    return col


# ==================== FUNÇÃO PRINCIPAL ====================

from core.dialects import Dialect

def build_agent_config_for_user_space(
    db: Session,
    user_ctx: UserContext,
    space_id: str,
    data_connection_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    dialect: Dialect = Dialect.POSTGRES,
) -> AgentConfig:
    """
    Constrói um AgentConfig a partir de TableMetadata, respeitando:
      - space_id
      - crew_ids do usuário (permissões)
      - opcionalmente data_connection_id (se houver mais de uma conexão por Space)

    Fluxo:
      1. Busca TableMetadata do space_id (+ connection opcional)
      2. Filtra por permissão: crew_id IN user_ctx.crew_ids OR crew_id IS NULL
      3. Agrupa por (table_name, data_connection_id)
      4. Monta TableSchema para cada grupo
      5. Retorna AgentConfig com lista de tables
    """
    user_crew_ids: List[str] = getattr(user_ctx, "crew_ids", []) or []

    q = db.query(TableMetadata).filter(TableMetadata.space_id == space_id)

    if data_connection_id:
        q = q.filter(TableMetadata.data_connection_id == data_connection_id)

    # Permissões por crew:
    # - se uma linha tem crew_id = NULL -> é "global" daquele space (todos que têm acesso ao space)
    # - se tem crew_id != NULL -> só quem tem esse crew_id pode ver
    if user_crew_ids:
        q = q.filter(
            (TableMetadata.crew_id == None)  # noqa: E711
            | (TableMetadata.crew_id.in_(user_crew_ids))
        )
    else:
        # usuário sem crews específicos: vê apenas metadados "globais" (crew_id IS NULL)
        q = q.filter(TableMetadata.crew_id == None)  # noqa: E711

    rows: List[TableMetadata] = q.all()

    if not rows:
        log_event(
            "factory_no_metadata_for_user",
            {
                "user_id": getattr(user_ctx, "user_id", None),
                "space_id": space_id,
                "crew_ids": user_crew_ids,
                "data_connection_id": data_connection_id,
            },
        )
        # Mesmo sem tabelas, retornamos um AgentConfig vazio (o orchestrator vai reclamar “No tables configured”)
        return AgentConfig(
            id=agent_id or f"agent_space_{space_id}",
            name=agent_name or f"Agent for space {space_id}",
            tables=[],
            dialect=dialect,
        )

    # Agrupa por (table_name, data_connection_id)
    grouped: DefaultDict[Tuple[str, Optional[str]], List[TableMetadata]] = defaultdict(list)
    for row in rows:
        key = (row.table_name, getattr(row, "data_connection_id", None))
        grouped[key].append(row)

    tables: List[TableSchema] = []

    for (table_name, conn_id), group_rows in grouped.items():
        # nome lógico amigável
        logical_name = _normalize_logical_name(table_name)

        # nome físico (se modelo tiver um campo dedicado, usa; caso contrário, usa table_name)
        physical_name = getattr(group_rows[0], "physical_name", table_name)

        # descrição da tabela (se houver no metadata)
        table_desc = getattr(group_rows[0], "table_description", None) or \
                     getattr(group_rows[0], "table_comment", None) or None

        columns: List[TableColumn] = []
        for r in group_rows:
            col = _metadata_row_to_column(r)
            columns.append(col)

        schema = TableSchema(
            logical_name=logical_name,
            physical_name=physical_name,
            description=table_desc,
            columns=columns,
            data_connection_id=conn_id,
            extra={
                "space_id": space_id,
                "source_table_name": table_name,
            },
        )
        
        # Propagate table-level temporal context (based on any of its columns)
        table_min = None
        table_max = None
        for col in columns:
            if "min_date" in col:
                # Simple logic: pick the oldest and newest dates from all cols
                val = col["min_date"]
                if not table_min or val < table_min:
                    table_min = val
            if "max_date" in col:
                val = col["max_date"]
                if not table_max or val > table_max:
                    table_max = val
                    
        if table_min:
            schema.extra["data_min_date"] = table_min
        if table_max:
            schema.extra["data_max_date"] = table_max

        tables.append(schema)

    cfg = AgentConfig(
        id=agent_id or f"agent_space_{space_id}",
        name=agent_name or f"Agent for space {space_id}",
        tables=tables,
        dialect=dialect,
        extra={
            "space_id": space_id,
            "data_connection_id": data_connection_id,
            "user_id": getattr(user_ctx, "user_id", None),
            "crew_ids": user_crew_ids,
        },
    )

    log_event(
        "factory_agent_config_built",
        {
            "agent_id": cfg.id,
            "agent_name": cfg.name,
            "space_id": space_id,
            "data_connection_id": data_connection_id,
            "num_tables": len(tables),
            "user_id": getattr(user_ctx, "user_id", None),
            "crew_ids": user_crew_ids,
        },
    )

    return cfg
