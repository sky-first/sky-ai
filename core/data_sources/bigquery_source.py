# core/data_sources/bigquery_source.py
from __future__ import annotations

from typing import List, Dict, Any, Optional, Union
import time
import os
import json

import google.auth
from google.cloud import bigquery
from google.oauth2 import service_account

from core.data_sources.base import BaseDataSource
from core.dialects import Dialect
from core.logging_utils import log_event
from datetime import datetime
import threading
from uuid import UUID


class BigQueryDataSource:
    """
    Implementação de BaseDataSource usando BigQuery.

    Esta classe NÃO depende mais de DataSourceConfig.
    Ela é inicializada com parâmetros simples e implementa run_query(sql),
    compatível com o protocolo BaseDataSource.

    Parâmetros:
      - project_id: ID do projeto GCP
      - dataset: dataset default (ex: "meu-projeto.billing_silver" ou só "billing_silver")
      - location: região (ex: "US") [opcional]
      - credentials_path: caminho para service account JSON [opcional]
      - label: nome para logging
    """

    def __init__(
        self,
        project_id: str,
        dataset: Optional[str] = None,
        location: Optional[str] = None,
        credentials_path: Optional[str] = None,
        credentials_json: Optional[Union[str, Dict[str, Any]]] = None,
        label: str = "bigquery",
    ) -> None:
        if not project_id:
            raise ValueError("BigQueryDataSource requires a project_id")

        self.project_id = project_id
        self.dataset = dataset  # ex: "billing_silver" (sem project) ou "meu-projeto.billing_silver"
        self.location = location
        self.credentials_path = credentials_path
        self.credentials_json = credentials_json
        self.label = label
        self.dialect = Dialect.BIGQUERY

        self._client: Optional[bigquery.Client] = None
        self._client_lock = threading.Lock() # Added by user

    # ---------- Cliente interno ----------

    def _get_client(self) -> bigquery.Client:
        """
        Retorna o cliente do BigQuery, criando se necessário (Singleton per instance).
        Thread-safe.
        """
        # First check outside lock (fast path)
        if self._client is not None:
            return self._client

        with self._client_lock:
            # Second check inside lock (safe path)
            if self._client is not None:
                return self._client

            # Permite configurar o caminho via env var se credentials_path não for passado
            credentials_path = self.credentials_path or os.getenv(
                "GCP_CREDENTIALS_PATH", os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            )

            client = None
            mode = "default"

            if credentials_path:
                creds = service_account.Credentials.from_service_account_file(
                    credentials_path,
                    scopes=["https://www.googleapis.com/auth/bigquery"],
                )
                client = bigquery.Client(
                    project=self.project_id,
                    credentials=creds,
                    location=self.location,
                )
                mode = "service_account_file"
            elif self.credentials_json:
                try:
                    info = (
                        json.loads(self.credentials_json)
                        if isinstance(self.credentials_json, str)
                        else self.credentials_json
                    )
                except Exception as e:
                    raise ValueError(f"Invalid credentials_json: {e}")

                creds = service_account.Credentials.from_service_account_info(
                    info,
                    scopes=["https://www.googleapis.com/auth/bigquery"],
                )
                client = bigquery.Client(
                    project=self.project_id,
                    credentials=creds,
                    location=self.location,
                )
                mode = "service_account_info"
            else:
                creds, _ = google.auth.default(
                    scopes=["https://www.googleapis.com/auth/bigquery"]
                )
                client = bigquery.Client(
                    project=self.project_id,
                    credentials=creds,
                    location=self.location,
                )
                mode = "default_auth"

            self._client = client
            return client
            client = bigquery.Client(
                project=self.project_id,
                credentials=creds,
                location=self.location,
            )
            mode = "default_credentials"

        self._client = client

        log_event(
            "bq_client_created",
            {
                "mode": mode,
                "project_id": self.project_id,
                "location": self.location,
                "label": self.label,
            },
        )
        return client

    # ---------- Métodos auxiliares (úteis para ingestão de metadados) ----------

    def _get_full_dataset_id(self) -> str:
        """
        Retorna o dataset no formato correto:
        - se self.dataset já tiver 'projeto.dataset', usa direto
        - senão, monta como 'project_id.dataset'
        """
        if not self.dataset:
            raise ValueError(
                "BigQueryDataSource requires 'dataset' to fetch metadata or sample rows"
            )

        if "." in self.dataset:
            return self.dataset  # já está no formato completo
        return f"{self.project_id}.{self.dataset}"

    def fetch_table_metadata(self) -> List[Dict[str, Any]]:
        """
        Lê INFORMATION_SCHEMA.COLUMNS do dataset configurado
        e retorna lista de dicts com:
          - table_name
          - column_name
          - data_type
          - is_nullable
        """
        client = self._get_client()
        dataset_id = self._get_full_dataset_id()

        query = f"""
        SELECT table_name, column_name, data_type, is_nullable
        FROM `{dataset_id}.INFORMATION_SCHEMA.COLUMNS`
        ORDER BY table_name, ordinal_position
        """

        start = time.perf_counter()
        job = client.query(query)
        rows = list(job.result())
        elapsed = time.perf_counter() - start

        meta: List[Dict[str, Any]] = []
        for r in rows:
            meta.append(
                {
                    "table_name": r.table_name,
                    "column_name": r.column_name,
                    "data_type": r.data_type,
                    "is_nullable": r.is_nullable,
                }
            )

        log_event(
            "bq_fetch_table_metadata",
            {
                "dataset": dataset_id,
                "num_rows": len(meta),
                "elapsed_sec": round(elapsed, 3),
                "label": self.label,
            },
        )
        return meta

    def sample_table_rows(self, table_name: str, limit: int = 3) -> List[Dict[str, Any]]:
        """
        Retorna até N linhas de uma tabela para exemplo de dados.
        Útil para enriquecer o prompt do especialista.
        """
        client = self._get_client()
        
        # Se o table_name já tiver 2 pontos (proj.dataset.table) ou 1 ponto (dataset.table),
        # usamos ele direto sem prefixar com dataset_id.
        if table_name.count(".") >= 1:
            full_table_path = table_name
            # Tenta extrair dataset_id do path para o log, ou usa o default
            parts = table_name.split(".")
            if len(parts) == 3:
                dataset_id = f"{parts[0]}.{parts[1]}"
            else:
                dataset_id = parts[0]
        else:
            dataset_id = self._get_full_dataset_id()
            full_table_path = f"{dataset_id}.{table_name}"

        query = f"SELECT * FROM `{full_table_path}` LIMIT {int(limit)}"
        job = client.query(query)
        rows = job.result()

        out: List[Dict[str, Any]] = []
        for row in rows:
            try:
                out.append(dict(row))
            except Exception:
                continue

        log_event(
            "bq_sample_table_rows",
            {
                "dataset": dataset_id,
                "table_name": table_name,
                "limit": limit,
                "returned": len(out),
                "label": self.label,
            },
        )
        return out

    # ---------- Interface BaseDataSource ----------

    def run_query(
        self,
        sql: str,
        max_rows: int = 10_000,
        timeout_seconds: int = 90,
    ) -> List[Dict[str, Any]]:
        """
        Executa uma query SQL no BigQuery e retorna lista de dicts.
        Compatível com BaseDataSource: o Specialist chama apenas run_query(sql).
        """
        client = self._get_client()

        log_event(
            "datasource_query_start",
            {
                "datasource": self.label,
                "sql_preview": sql[:500],
            },
        )

        out: List[Dict[str, Any]] = []
        try:
            job = client.query(sql)
            rows_iter = job.result(timeout=timeout_seconds)

            count = 0
            for row in rows_iter:
                count += 1
                if count > max_rows:
                    log_event(
                        "bq_query_truncated",
                        {"max_rows": max_rows, "label": self.label},
                    )
                    break
                try:
                    out.append(dict(row))
                except Exception:
                    continue

            log_event(
                "datasource_query_success",
                {
                    "datasource": self.label,
                    "num_rows": len(out),
                    "max_rows": max_rows,
                    "timeout": timeout_seconds,
                },
            )
            return out
        except Exception as e:
            log_event(
                "datasource_query_error",
                {
                    "datasource": self.label,
                    "error": str(e)[:500],
                },
            )
            raise

    def run_query_arrow(self, sql: str) -> Any:
        """
        Executa query no BigQuery e retorna pyarrow.Table nativamente.
        Bypassa a conversão Python de linhas individuais.
        """
        client = self._get_client()

        log_event(
            "datasource_query_arrow_start",
            {
                "datasource": self.label,
                "sql_preview": sql[:500],
            },
        )

        try:
            job = client.query(sql)
            # BigQuery API otimizada: to_arrow() baixa blocos binários Arrow
            arrow_table = job.result().to_arrow()
            
            log_event(
                "datasource_query_arrow_success",
                {
                    "datasource": self.label,
                    "num_rows": arrow_table.num_rows,
                    "num_cols": arrow_table.num_columns,
                    "size_bytes": arrow_table.nbytes
                },
            )
            return arrow_table

        except Exception as e:
            log_event(
                "datasource_query_arrow_error",
                {
                    "datasource": self.label,
                    "error": str(e)[:500],
                },
            )
            raise
