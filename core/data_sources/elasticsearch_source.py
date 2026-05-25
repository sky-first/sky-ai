# core/data_sources/elasticsearch_source.py
from __future__ import annotations

import json
from typing import List, Dict, Any

from core.dialects import Dialect
from core.logging_utils import log_event


class ElasticsearchSource:
    """
    Data source for Elasticsearch indices.
    Accepts Elasticsearch DSL queries (dict or JSON string) and returns
    the hits as plain Python dicts enriched with _id and _score metadata.
    All deps (elasticsearch) are imported lazily.
    """

    dialect = Dialect.ELASTICSEARCH

    def __init__(
        self,
        hosts: List[str],
        index: str,
        api_key: str = "",
        label: str = "elasticsearch",
    ) -> None:
        self._hosts = hosts
        self._index = index
        self._api_key = api_key
        self.label = label
        self._es = None  # lazy connect

    def _get_client(self):
        """Return an Elasticsearch client, connecting on first call."""
        from elasticsearch import Elasticsearch  # lazy import

        if self._es is None:
            kwargs: Dict[str, Any] = {"hosts": self._hosts}
            if self._api_key:
                kwargs["api_key"] = self._api_key
            self._es = Elasticsearch(**kwargs)
        return self._es

    def run_query(self, query) -> List[Dict[str, Any]]:
        """
        Execute an Elasticsearch DSL query against the default index.

        query may be:
          - dict — ES DSL body, e.g. {"query": {"match_all": {}}}
          - str  — JSON-encoded dict
        Returns a list of dicts where each dict is the _source fields
        plus _id and _score from the hit metadata.
        """
        if isinstance(query, str):
            try:
                query = json.loads(query)
            except json.JSONDecodeError as exc:
                log_event(
                    "datasource_elasticsearch_json_error",
                    {"datasource": self.label, "error": str(exc), "query": query[:300]},
                )
                raise ValueError(
                    f"ElasticsearchSource received an invalid JSON string: {query[:100]!r}"
                ) from exc

        if not isinstance(query, dict):
            raise TypeError(
                f"ElasticsearchSource.run_query expects dict or str; got {type(query)}"
            )

        log_event(
            "datasource_query_start",
            {"datasource": self.label, "index": self._index},
        )

        try:
            es = self._get_client()
            response = es.search(index=self._index, body=query)
            hits = response.get("hits", {}).get("hits", [])

            rows: List[Dict[str, Any]] = []
            for hit in hits:
                row = dict(hit.get("_source") or {})
                row["_id"] = hit.get("_id")
                row["_score"] = hit.get("_score")
                rows.append(row)

            log_event(
                "datasource_query_success",
                {"datasource": self.label, "num_rows": len(rows)},
            )
            return rows

        except Exception as exc:
            log_event(
                "datasource_query_error",
                {"datasource": self.label, "error": str(exc)[:500]},
            )
            raise

    def run_query_arrow(self, query) -> Any:
        """Run ES query and return a pyarrow.Table."""
        import pyarrow as pa  # lazy import

        rows = self.run_query(query)
        if not rows:
            return pa.Table.from_pylist([])
        return pa.Table.from_pylist(rows)
