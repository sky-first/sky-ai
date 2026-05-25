# core/data_sources/mongodb_source.py
from __future__ import annotations

import json
from typing import List, Dict, Any

from core.dialects import Dialect
from core.logging_utils import log_event


class MongoDBSource:
    """
    Data source for MongoDB collections.
    Accepts aggregation pipelines (list of stages) or JSON strings.
    All deps (pymongo) are imported lazily to avoid breaking imports when
    the package is not installed.
    """

    dialect = Dialect.MONGODB

    def __init__(
        self,
        uri: str,
        database: str,
        collection: str,
        label: str = "mongodb",
    ) -> None:
        self._uri = uri
        self._database = database
        self._collection = collection
        self.label = label
        self._client = None  # lazy connect

    def _get_collection(self):
        """Return a pymongo Collection handle, connecting on first call."""
        import pymongo  # lazy import

        if self._client is None:
            self._client = pymongo.MongoClient(self._uri)
        return self._client[self._database][self._collection]

    @staticmethod
    def _normalize_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
        """Convert non-serialisable types (ObjectId, datetime, …) to str."""
        result: Dict[str, Any] = {}
        for k, v in doc.items():
            # ObjectId and similar types stringify cleanly via str()
            if hasattr(v, "__class__") and v.__class__.__name__ in (
                "ObjectId",
                "Decimal128",
                "Binary",
                "Code",
                "Regex",
                "Timestamp",
            ):
                result[k] = str(v)
            elif isinstance(v, dict):
                result[k] = MongoDBSource._normalize_doc(v)
            elif isinstance(v, list):
                result[k] = [
                    (
                        MongoDBSource._normalize_doc(item)
                        if isinstance(item, dict)
                        else (
                            str(item)
                            if hasattr(item, "__class__")
                            and item.__class__.__name__ == "ObjectId"
                            else item
                        )
                    )
                    for item in v
                ]
            else:
                result[k] = v
        return result

    def run_query(self, query) -> List[Dict[str, Any]]:
        """
        Execute an aggregation pipeline against the default collection.

        query may be:
          - list  — aggregation pipeline stages, e.g. [{"$match": {...}}]
          - dict  — single stage, wrapped into [stage]
          - str   — JSON-encoded list or dict, parsed before execution
        """
        # --- normalise query type ---
        if isinstance(query, str):
            try:
                query = json.loads(query)
            except json.JSONDecodeError as exc:
                log_event(
                    "datasource_mongodb_json_error",
                    {"datasource": self.label, "error": str(exc), "query": query[:300]},
                )
                raise ValueError(
                    f"MongoDBSource received an invalid JSON string: {query[:100]!r}"
                ) from exc

        if isinstance(query, dict):
            pipeline = [query]
        elif isinstance(query, list):
            pipeline = query
        else:
            raise TypeError(
                f"MongoDBSource.run_query expects list, dict, or str; got {type(query)}"
            )

        log_event(
            "datasource_query_start",
            {"datasource": self.label, "pipeline_stages": len(pipeline)},
        )

        try:
            collection = self._get_collection()
            cursor = collection.aggregate(pipeline)
            rows = [self._normalize_doc(doc) for doc in cursor]

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
        """Run query and return a pyarrow.Table."""
        import pyarrow as pa  # lazy import

        rows = self.run_query(query)
        if not rows:
            return pa.Table.from_pylist([])
        return pa.Table.from_pylist(rows)

    def test_connection(self) -> bool:
        """Ping the MongoDB server. Returns True on success."""
        try:
            import pymongo  # lazy import

            if self._client is None:
                self._client = pymongo.MongoClient(
                    self._uri, serverSelectionTimeoutMS=5000
                )
            self._client.admin.command("ping")
            return True
        except Exception as exc:
            log_event(
                "datasource_mongodb_ping_error",
                {"datasource": self.label, "error": str(exc)[:300]},
            )
            return False
