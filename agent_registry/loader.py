# agent_registry/loader.py
from __future__ import annotations

from pathlib import Path
from typing import Dict

import yaml

from core.agents.generic_sql_agent import AgentConfig, TableSchema, TableColumn
from core.data_sources.base import DataSourceConfig
from core.data_sources.bigquery_source import BigQueryDataSource
from core.logging_utils import log_event

BASE_DIR = Path(__file__).resolve().parent
EXAMPLES_DIR = BASE_DIR / "examples"


class AgentNotFoundError(Exception):
    pass


def _build_data_source(ds_conf: dict):
    ds_type = ds_conf.get("type")
    config = DataSourceConfig(
        id=ds_conf["id"],
        type=ds_type,
        display_name=ds_conf.get("display_name", ds_conf["id"]),
        default_schema=ds_conf.get("default_schema"),
        extra=ds_conf.get("extra") or {},
    )

    if ds_type == "bigquery":
        return BigQueryDataSource(config=config)

    # Futuro: postgres, mysql, sqlserver, etc.
    raise ValueError(f"Unsupported data source type: {ds_type}")


def _build_tables(tables_conf: list) -> list[TableSchema]:
    tables: list[TableSchema] = []
    for t in tables_conf:
        cols_conf = t.get("columns") or []
        cols = [
            {
                "name": c["name"],
                "type": c.get("data_type", "STRING"),
                "nullable": c.get("nullable", True),
                "description": c.get("description"),
                "is_primary_key": c.get("is_primary_key", False),
                "is_foreign_key": c.get("is_foreign_key", False),
            }
            for c in cols_conf
        ]
        tables.append(
            TableSchema(
                logical_name=t["logical_name"],
                physical_name=t["physical_name"],
                description=t.get("description"),
                columns=cols,
            )
        )
    return tables


def load_agent_from_yaml(path: Path) -> AgentConfig:
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    ds = _build_data_source(raw["data_source"])
    tables = _build_tables(raw.get("tables") or [])

    agent = AgentConfig(
        id=raw["id"],
        name=raw.get("name", raw["id"]),
        description=raw.get("description", ""),
        data_source=ds,
        tables=tables,
    )

    log_event(
        "agent_loaded_from_yaml",
        {
            "agent_id": agent.id,
            "path": str(path),
            "num_tables": len(agent.tables),
            "data_source_type": agent.data_source.config.type,
        },
    )
    return agent


def get_agent_config(agent_id: str) -> AgentConfig:
    """
    Versão simples: procura um YAML em agent_registry/examples com o nome {agent_id}.yaml.
    Ex: agent_id="billing_default" -> billing_default.yaml
    Depois podemos trocar isso por busca em banco/registry mais sofisticado.
    """
    yaml_path = EXAMPLES_DIR / f"{agent_id}.yaml"
    if not yaml_path.exists():
        raise AgentNotFoundError(
            f"Agent YAML not found for id={agent_id} at {yaml_path}"
        )

    return load_agent_from_yaml(yaml_path)
