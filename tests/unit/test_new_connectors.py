"""
Unit tests for items 28-31 — new data source connectors.

Item 28: MongoDBSource
Item 29: DynamoDBSource
Item 30: ElasticsearchSource
Item 31: Redshift + Databricks DSN auto-build in factory
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch, PropertyMock

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_conn(ds_type: str, config: dict) -> MagicMock:
    conn = MagicMock()
    conn.id = "test-conn-001"
    conn.type = ds_type
    conn.connector_id = ds_type
    conn.config = config
    return conn


# ─── Item 28: MongoDBSource ────────────────────────────────────────────────


class TestMongoDBSource:
    def _source(self):
        from core.data_sources.mongodb_source import MongoDBSource

        return MongoDBSource(
            uri="mongodb://localhost:27017",
            database="testdb",
            collection="orders",
            label="test-mongo",
        )

    def test_dialect_is_mongodb(self):
        from core.dialects import Dialect

        assert self._source().dialect == Dialect.MONGODB

    def test_run_query_with_list_pipeline(self):
        src = self._source()
        pipeline = [{"$match": {"status": "active"}}, {"$limit": 5}]
        mock_cursor = [{"_id": "1", "status": "active", "amount": 100}]

        mock_collection = MagicMock()
        mock_collection.aggregate.return_value = mock_cursor

        with patch.object(src, "_get_collection", return_value=mock_collection):
            rows = src.run_query(pipeline)

        mock_collection.aggregate.assert_called_once_with(pipeline)
        assert len(rows) == 1
        assert rows[0]["status"] == "active"

    def test_run_query_accepts_json_string(self):
        src = self._source()
        pipeline_str = json.dumps([{"$match": {"active": True}}])
        mock_collection = MagicMock()
        mock_collection.aggregate.return_value = [{"active": True}]

        with patch.object(src, "_get_collection", return_value=mock_collection):
            rows = src.run_query(pipeline_str)

        assert rows == [{"active": True}]

    def test_run_query_wraps_single_dict_stage(self):
        src = self._source()
        stage = {"$match": {"status": "active"}}
        mock_collection = MagicMock()
        mock_collection.aggregate.return_value = []

        with patch.object(src, "_get_collection", return_value=mock_collection):
            src.run_query(stage)

        # Single dict should be wrapped in a list
        mock_collection.aggregate.assert_called_once_with([stage])

    def test_run_query_raises_on_invalid_json(self):
        import pytest

        src = self._source()
        with pytest.raises(ValueError, match="invalid JSON"):
            src.run_query("not-valid-json{{")

    def test_normalize_doc_converts_objectid(self):
        from core.data_sources.mongodb_source import MongoDBSource

        class FakeObjectId:
            __class__ = type("ObjectId", (), {"__name__": "ObjectId"})()

            def __str__(self):
                return "abc123"

        doc = {"_id": FakeObjectId(), "name": "test"}
        normalized = MongoDBSource._normalize_doc(doc)
        assert normalized["_id"] == "abc123"
        assert normalized["name"] == "test"

    def test_run_query_arrow_returns_pyarrow_table(self):
        import pyarrow as pa

        src = self._source()
        mock_collection = MagicMock()
        mock_collection.aggregate.return_value = [{"a": 1}, {"a": 2}]

        with patch.object(src, "_get_collection", return_value=mock_collection):
            table = src.run_query_arrow([])

        assert isinstance(table, pa.Table)
        assert table.num_rows == 2

    def test_run_query_arrow_empty_returns_empty_table(self):
        import pyarrow as pa

        src = self._source()
        mock_collection = MagicMock()
        mock_collection.aggregate.return_value = []

        with patch.object(src, "_get_collection", return_value=mock_collection):
            table = src.run_query_arrow([])

        assert isinstance(table, pa.Table)
        assert table.num_rows == 0


# ─── Item 29: DynamoDBSource ──────────────────────────────────────────────


class TestDynamoDBSource:
    def _source(self):
        from core.data_sources.dynamodb_source import DynamoDBSource

        return DynamoDBSource(
            region="us-east-1",
            table_name="Orders",
            access_key="AKIATEST",
            secret_key="secret",
            label="test-dynamo",
        )

    def test_dialect_is_dynamodb(self):
        from core.dialects import Dialect

        assert self._source().dialect == Dialect.DYNAMODB

    def test_deserialize_string(self):
        from core.data_sources.dynamodb_source import DynamoDBSource

        assert DynamoDBSource._deserialize_item({"S": "hello"}) == "hello"

    def test_deserialize_number_int(self):
        from core.data_sources.dynamodb_source import DynamoDBSource

        assert DynamoDBSource._deserialize_item({"N": "42"}) == 42

    def test_deserialize_number_float(self):
        from core.data_sources.dynamodb_source import DynamoDBSource

        assert DynamoDBSource._deserialize_item({"N": "3.14"}) == 3.14

    def test_deserialize_bool(self):
        from core.data_sources.dynamodb_source import DynamoDBSource

        assert DynamoDBSource._deserialize_item({"BOOL": True}) is True

    def test_deserialize_null(self):
        from core.data_sources.dynamodb_source import DynamoDBSource

        assert DynamoDBSource._deserialize_item({"NULL": True}) is None

    def test_deserialize_list(self):
        from core.data_sources.dynamodb_source import DynamoDBSource

        val = DynamoDBSource._deserialize_item({"L": [{"S": "a"}, {"N": "1"}]})
        assert val == ["a", 1]

    def test_deserialize_map(self):
        from core.data_sources.dynamodb_source import DynamoDBSource

        val = DynamoDBSource._deserialize_item(
            {"M": {"name": {"S": "Alice"}, "age": {"N": "30"}}}
        )
        assert val == {"name": "Alice", "age": 30}

    def test_deserialize_full_item(self):
        from core.data_sources.dynamodb_source import DynamoDBSource

        raw = {
            "order_id": {"S": "O-001"},
            "amount": {"N": "250"},
            "active": {"BOOL": True},
            "tags": {"SS": ["vip", "urgent"]},
        }
        result = DynamoDBSource._deserialize_item(raw)
        assert result["order_id"] == "O-001"
        assert result["amount"] == 250
        assert result["active"] is True
        assert result["tags"] == ["vip", "urgent"]

    def test_run_query_partiql(self):
        src = self._source()
        raw_items = [
            {"order_id": {"S": "O-001"}, "amount": {"N": "100"}},
            {"order_id": {"S": "O-002"}, "amount": {"N": "200"}},
        ]
        mock_response = {"Items": raw_items}
        mock_client = MagicMock()
        mock_client.execute_statement.return_value = mock_response

        with patch.object(src, "_get_client", return_value=mock_client):
            rows = src.run_query("SELECT * FROM Orders")

        assert len(rows) == 2
        assert rows[0]["order_id"] == "O-001"
        assert rows[1]["amount"] == 200

    def test_run_query_paginates(self):
        src = self._source()
        page1 = {"Items": [{"id": {"S": "1"}}], "NextToken": "tok"}
        page2 = {"Items": [{"id": {"S": "2"}}]}
        mock_client = MagicMock()
        mock_client.execute_statement.side_effect = [page1, page2]

        with patch.object(src, "_get_client", return_value=mock_client):
            rows = src.run_query("SELECT * FROM T")

        assert len(rows) == 2
        assert mock_client.execute_statement.call_count == 2

    def test_run_query_arrow_returns_table(self):
        import pyarrow as pa

        src = self._source()
        mock_client = MagicMock()
        mock_client.execute_statement.return_value = {
            "Items": [{"x": {"N": "1"}}, {"x": {"N": "2"}}]
        }

        with patch.object(src, "_get_client", return_value=mock_client):
            table = src.run_query_arrow("SELECT * FROM T")

        assert isinstance(table, pa.Table)
        assert table.num_rows == 2


# ─── Item 30: ElasticsearchSource ─────────────────────────────────────────


class TestElasticsearchSource:
    def _source(self):
        from core.data_sources.elasticsearch_source import ElasticsearchSource

        return ElasticsearchSource(
            hosts=["http://localhost:9200"],
            index="logs",
            api_key="test-key",
            label="test-es",
        )

    def test_dialect_is_elasticsearch(self):
        from core.dialects import Dialect

        assert self._source().dialect == Dialect.ELASTICSEARCH

    def test_run_query_with_dict(self):
        src = self._source()
        query = {"query": {"match_all": {}}}
        mock_response = {
            "hits": {
                "hits": [
                    {
                        "_id": "1",
                        "_score": 1.0,
                        "_source": {"level": "ERROR", "msg": "oops"},
                    },
                    {
                        "_id": "2",
                        "_score": 0.8,
                        "_source": {"level": "WARN", "msg": "hmm"},
                    },
                ]
            }
        }
        mock_es = MagicMock()
        mock_es.search.return_value = mock_response

        with patch.object(src, "_get_client", return_value=mock_es):
            rows = src.run_query(query)

        assert len(rows) == 2
        assert rows[0]["level"] == "ERROR"
        assert rows[0]["_id"] == "1"
        assert rows[0]["_score"] == 1.0

    def test_run_query_accepts_json_string(self):
        src = self._source()
        query_str = json.dumps({"query": {"match_all": {}}})
        mock_es = MagicMock()
        mock_es.search.return_value = {"hits": {"hits": []}}

        with patch.object(src, "_get_client", return_value=mock_es):
            rows = src.run_query(query_str)

        assert rows == []

    def test_run_query_raises_on_invalid_json(self):
        import pytest

        src = self._source()
        with pytest.raises(ValueError, match="invalid JSON"):
            src.run_query("not{json}")

    def test_run_query_raises_on_wrong_type(self):
        import pytest

        src = self._source()
        with pytest.raises(TypeError):
            src.run_query([1, 2, 3])  # list not accepted

    def test_run_query_arrow_returns_table(self):
        import pyarrow as pa

        src = self._source()
        mock_es = MagicMock()
        mock_es.search.return_value = {
            "hits": {"hits": [{"_id": "a", "_score": 1.0, "_source": {"x": 1}}]}
        }

        with patch.object(src, "_get_client", return_value=mock_es):
            table = src.run_query_arrow({"query": {"match_all": {}}})

        assert isinstance(table, pa.Table)
        assert table.num_rows == 1


# ─── Item 31: Factory DSN auto-build ──────────────────────────────────────


class TestFactoryDSNAutoBuild:
    def test_redshift_with_explicit_dsn(self):
        conn = _make_conn(
            "redshift", {"dsn": "redshift+redshift_connector://u:p@host:5439/db"}
        )
        with patch("core.data_sources.factory.create_engine") as mock_engine, patch(
            "core.security.config_decryption.decrypt_config", side_effect=lambda x: x
        ):
            mock_engine.return_value = MagicMock()
            from core.data_sources.factory import DataSourceFactory

            src = DataSourceFactory.build_from_dataconnection(conn)
        mock_engine.assert_called_once()
        assert "redshift+redshift_connector" in mock_engine.call_args[0][0]

    def test_redshift_auto_builds_dsn_from_parts(self):
        conn = _make_conn(
            "redshift",
            {
                "host": "myredshift.us-east-1.redshift.amazonaws.com",
                "username": "admin",
                "password": "s3cr3t",
                "database": "analytics",
                "port": 5439,
            },
        )
        with patch("core.data_sources.factory.create_engine") as mock_engine, patch(
            "core.security.config_decryption.decrypt_config", side_effect=lambda x: x
        ):
            mock_engine.return_value = MagicMock()
            from core.data_sources.factory import DataSourceFactory

            src = DataSourceFactory.build_from_dataconnection(conn)
        dsn = mock_engine.call_args[0][0]
        assert "redshift+redshift_connector" in dsn
        assert "myredshift.us-east-1.redshift.amazonaws.com" in dsn
        assert "5439" in dsn
        assert "analytics" in dsn

    def test_redshift_raises_without_dsn_or_parts(self):
        import pytest

        conn = _make_conn("redshift", {})
        with patch(
            "core.security.config_decryption.decrypt_config", side_effect=lambda x: x
        ):
            from core.data_sources.factory import DataSourceFactory

            with pytest.raises(ValueError, match="needs"):
                DataSourceFactory.build_from_dataconnection(conn)

    def test_databricks_auto_builds_dsn_from_parts(self):
        conn = _make_conn(
            "databricks",
            {
                "server_hostname": "adb-123.azuredatabricks.net",
                "http_path": "/sql/1.0/warehouses/abc",
                "access_token": "dapiTOKEN",
                "catalog": "main",
            },
        )
        with patch("core.data_sources.factory.create_engine") as mock_engine, patch(
            "core.security.config_decryption.decrypt_config", side_effect=lambda x: x
        ):
            mock_engine.return_value = MagicMock()
            from core.data_sources.factory import DataSourceFactory

            src = DataSourceFactory.build_from_dataconnection(conn)
        dsn = mock_engine.call_args[0][0]
        assert "databricks+connector" in dsn
        assert "adb-123.azuredatabricks.net" in dsn
        assert "443" in dsn

    def test_mongodb_factory_build(self):
        conn = _make_conn(
            "mongodb",
            {
                "uri": "mongodb://localhost:27017",
                "database": "testdb",
                "collection": "events",
            },
        )
        with patch(
            "core.security.config_decryption.decrypt_config", side_effect=lambda x: x
        ):
            from core.data_sources.factory import DataSourceFactory

            src = DataSourceFactory.build_from_dataconnection(conn)
        from core.data_sources.mongodb_source import MongoDBSource

        assert isinstance(src, MongoDBSource)
        assert src._database == "testdb"
        assert src._collection == "events"

    def test_mongodb_raises_without_uri(self):
        import pytest

        conn = _make_conn("mongodb", {"database": "testdb"})
        with patch(
            "core.security.config_decryption.decrypt_config", side_effect=lambda x: x
        ):
            from core.data_sources.factory import DataSourceFactory

            with pytest.raises(ValueError, match="needs uri"):
                DataSourceFactory.build_from_dataconnection(conn)

    def test_dynamodb_factory_build(self):
        conn = _make_conn(
            "dynamodb",
            {
                "region": "eu-west-1",
                "table_name": "Users",
                "access_key_id": "KEY",
                "secret_access_key": "SECRET",
            },
        )
        with patch(
            "core.security.config_decryption.decrypt_config", side_effect=lambda x: x
        ):
            from core.data_sources.factory import DataSourceFactory

            src = DataSourceFactory.build_from_dataconnection(conn)
        from core.data_sources.dynamodb_source import DynamoDBSource

        assert isinstance(src, DynamoDBSource)
        assert src._region == "eu-west-1"
        assert src._table_name == "Users"

    def test_elasticsearch_factory_build(self):
        conn = _make_conn(
            "elasticsearch",
            {
                "hosts": ["https://myelastic:9200"],
                "index": "metrics",
                "api_key": "ESKEY",
            },
        )
        with patch(
            "core.security.config_decryption.decrypt_config", side_effect=lambda x: x
        ):
            from core.data_sources.factory import DataSourceFactory

            src = DataSourceFactory.build_from_dataconnection(conn)
        from core.data_sources.elasticsearch_source import ElasticsearchSource

        assert isinstance(src, ElasticsearchSource)
        assert src._index == "metrics"
        assert src._api_key == "ESKEY"
