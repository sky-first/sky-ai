# core/data_sources/dynamodb_source.py
from __future__ import annotations

from typing import List, Dict, Any

from core.dialects import Dialect
from core.logging_utils import log_event


class DynamoDBSource:
    """
    Data source for Amazon DynamoDB via PartiQL.
    Accepts a PartiQL statement string and returns plain Python dicts
    (DynamoDB type descriptors are deserialised automatically).
    All deps (boto3) are imported lazily.
    """

    dialect = Dialect.DYNAMODB

    def __init__(
        self,
        region: str,
        table_name: str,
        access_key: str = "",
        secret_key: str = "",
        label: str = "dynamodb",
    ) -> None:
        self._region = region
        self._table_name = table_name
        self._access_key = access_key
        self._secret_key = secret_key
        self.label = label
        self._client = None  # lazy connect

    def _get_client(self):
        """Return a boto3 DynamoDB client, connecting on first call."""
        import boto3  # lazy import

        if self._client is None:
            kwargs: Dict[str, Any] = {"region_name": self._region}
            if self._access_key and self._secret_key:
                kwargs["aws_access_key_id"] = self._access_key
                kwargs["aws_secret_access_key"] = self._secret_key
            self._client = boto3.client("dynamodb", **kwargs)
        return self._client

    @staticmethod
    def _deserialize_item(item: Any) -> Any:
        """
        Recursively deserialise DynamoDB typed values into plain Python types.

        DynamoDB returns items like:
          {"name": {"S": "Alice"}, "age": {"N": "30"}, "active": {"BOOL": True}}
        We convert them to:
          {"name": "Alice", "age": 30, "active": True}
        """
        if isinstance(item, dict):
            # DynamoDB type descriptor — exactly one key that is an uppercase type tag
            type_keys = {"S", "N", "BOOL", "NULL", "B", "SS", "NS", "BS", "L", "M"}
            keys = set(item.keys())
            if len(keys) == 1 and keys <= type_keys:
                tag, value = next(iter(item.items()))
                if tag == "S":
                    return str(value)
                if tag == "N":
                    # Return int if possible, else float
                    try:
                        return int(value)
                    except (ValueError, TypeError):
                        return float(value)
                if tag == "BOOL":
                    return bool(value)
                if tag == "NULL":
                    return None
                if tag == "B":
                    return bytes(value) if not isinstance(value, bytes) else value
                if tag == "SS":
                    return list(value)
                if tag == "NS":
                    return [
                        int(v) if "." not in str(v) else float(v) for v in value
                    ]
                if tag == "BS":
                    return [bytes(v) if not isinstance(v, bytes) else v for v in value]
                if tag == "L":
                    return [DynamoDBSource._deserialize_item(v) for v in value]
                if tag == "M":
                    return {k: DynamoDBSource._deserialize_item(v) for k, v in value.items()}
            # Plain dict (already deserialised or mixed)
            return {k: DynamoDBSource._deserialize_item(v) for k, v in item.items()}
        if isinstance(item, list):
            return [DynamoDBSource._deserialize_item(v) for v in item]
        return item

    def run_query(self, partiql: str) -> List[Dict[str, Any]]:
        """
        Execute a PartiQL statement against DynamoDB.
        Returns a list of plain Python dicts.
        """
        log_event(
            "datasource_query_start",
            {"datasource": self.label, "partiql_preview": partiql[:300]},
        )

        try:
            client = self._get_client()
            response = client.execute_statement(Statement=partiql)
            raw_items = response.get("Items", [])
            rows = [self._deserialize_item(item) for item in raw_items]

            # Handle pagination
            next_token = response.get("NextToken")
            while next_token:
                response = client.execute_statement(
                    Statement=partiql, NextToken=next_token
                )
                raw_items = response.get("Items", [])
                rows.extend(self._deserialize_item(item) for item in raw_items)
                next_token = response.get("NextToken")

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

    def run_query_arrow(self, partiql: str) -> Any:
        """Run PartiQL query and return a pyarrow.Table."""
        import pyarrow as pa  # lazy import

        rows = self.run_query(partiql)
        if not rows:
            return pa.Table.from_pylist([])
        return pa.Table.from_pylist(rows)
