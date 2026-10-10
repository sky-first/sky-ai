from __future__ import annotations

from typing import List, Dict, Any, Optional
import httpx
from core.data_sources.api_payload import (
    parse_records,
    records_path_for,
    redact,
    resolve_auth,
)
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
        self.extra = extra
        self.base_url = extra.get("base_url")

        # Autenticação: `api_key`/`headers` (legado), `auth` (contrato do
        # backend) e os campos que a web grava (`auth_type`/`auth_header`/
        # `auth_value`). Antes só os dois primeiros eram lidos — a chave
        # escrita na web nunca chegava ao pedido (Anexo C, D1).
        # A chave entra aqui, no pedido; o LLM nunca a vê.
        self.headers, self.auth_params, self.basic_auth, self._secrets = resolve_auth(
            extra
        )

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
            # O especialista aceita `endpoint` ou `path`; aqui só se lia
            # `endpoint` e um `path` ia parar à raiz da API.
            endpoint = request_spec.get("endpoint") or request_spec.get("path") or ""
            params = request_spec.get("params")
            if self.auth_params:
                # A chave da ligação ganha a qualquer valor que o LLM ponha.
                params = {**(params or {}), **self.auth_params}
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
                    auth=self.basic_auth,
                    params=params,
                    json=body,
                )
                response.raise_for_status()

                # Se não tiver conteúdo, retorna lista vazia
                if response.status_code == 204:
                    return []

                # === NORMALIZAÇÃO DE RESULTADO ===
                # Contrato: Deve retornar List[Dict]
                # JSON, XML e CSV viram linhas; a lista principal é encontrada
                # sozinha ou indicada por `records_path` (Anexo C, D3).
                normalized_data: List[Dict[str, Any]] = parse_records(
                    response.content,
                    response.headers.get("content-type", ""),
                    records_path_for(self.extra, endpoint),
                )

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
                    "error": redact(e, self._secrets)[:500],
                },
            )
            if self._secrets and any(sec in str(e) for sec in self._secrets):
                # O httpx põe o URL (com a chave na query) na mensagem.
                raise RuntimeError(redact(e, self._secrets)) from None
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
