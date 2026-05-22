from __future__ import annotations

from typing import List, Dict, Any, Optional
import httpx
from core.data_sources.base import BaseDataSource, DataSourceConfig
from core.dialects import Dialect
from core.logging_utils import log_event


class APISource:
    """
    Fonte de dados para APIs REST/GraphQL.
    Trata APIs como fontes NoSQL (geração de JSON/Payload), não SQL.
    """

    def __init__(self, config: DataSourceConfig, label: str = "api_source") -> None:
        self.config = config
        self.dialect = Dialect.NOSQL
        self.label = label

        # Extrair configurações extras
        extra = config.extra or {}
        self.base_url = extra.get("base_url")
        self.api_key = extra.get("api_key")
        self.headers = extra.get("headers", {})

        # Injetar API Key se existir
        if self.api_key:
            self.headers["Authorization"] = f"Bearer {self.api_key}"

    def run_query(self, query: str | Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Executa uma consulta na API.
        Aqui 'query' NÃO é SQL. Espera-se um JSON string ou Dict com:
        {
            "method": "GET" | "POST",
            "endpoint": "/users",
            "params": {...},
            "body": {...}
        }
        """
        import json

        # Parse se for string
        if isinstance(query, str):
            try:
                request_spec = json.loads(query)
            except json.JSONDecodeError:
                # Se falhar o parse, pode ser que o LLM mandou algo errado
                # Log e re-raise
                log_event("datasource_api_json_error", {"query": query[:500]})
                raise ValueError(
                    f"Invalid JSON query format for API Source: {query[:100]}..."
                )
        else:
            request_spec = query

        log_event(
            "datasource_api_query_start",
            {
                "datasource": self.label,
                "request_spec": request_spec,
            },
        )

        try:
            method = request_spec.get("method", "GET").upper()
            endpoint = request_spec.get("endpoint", "")
            params = request_spec.get("params")
            body = request_spec.get("body")

            # Construir URL final
            if self.base_url:
                url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
            else:
                url = endpoint

            with httpx.Client(timeout=30.0) as client:
                response = client.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    params=params,
                    json=body,
                )
                response.raise_for_status()

                # Se não tiver conteúdo, retorna lista vazia
                if response.status_code == 204:
                    return []

                data = response.json()

                # === NORMALIZAÇÃO DE RESULTADO ===
                # Contrato: Deve retornar List[Dict]

                normalized_data: List[Dict[str, Any]] = []

                if isinstance(data, list):
                    normalized_data = data
                elif isinstance(data, dict):
                    # Heurística para APIs paginadas ou envelopadas
                    # Procura chaves comuns de listas
                    candidates = [
                        "data",
                        "items",
                        "results",
                        "records",
                        "users",
                        "orders",
                    ]
                    found_list = False

                    for key in candidates:
                        if key in data and isinstance(data[key], list):
                            normalized_data = data[key]
                            found_list = True
                            break

                    if not found_list:
                        # Se não achou lista, retorna o próprio dict como único item
                        normalized_data = [data]
                else:
                    # Primitivo ou null
                    normalized_data = [{"value": data}]

                log_event(
                    "datasource_api_query_success",
                    {
                        "datasource": self.label,
                        "num_rows": len(normalized_data),
                    },
                )
                return normalized_data

        except Exception as e:
            log_event(
                "datasource_api_query_error",
                {
                    "datasource": self.label,
                    "error": str(e)[:500],
                },
            )
            raise

    def run_query_arrow(self, query: str) -> Any:
        import pyarrow as pa

        data = self.run_query(query)
        if not data:
            return pa.Table.from_pylist([])
        return pa.Table.from_pylist(data)

    def sample_table_rows(
        self, table_name: str, limit: int = 3
    ) -> List[Dict[str, Any]]:
        # APIs geralmente não suportam amostragem de tabela por nome SQL
        return []
