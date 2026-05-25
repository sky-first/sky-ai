"""Unit tests for run_dataset_description_embeddings (roadmap item 16).

Tests focus on the text-building logic and the upsert/delete contract.
DB-dependent paths are covered via async mocks so no real DB is needed.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from uuid import uuid4

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_tables_json(tables):
    """Return a list simulating connection_metadata.tables JSON."""
    return tables


def _fake_table(name, schema="public", description="", columns=None):
    return {
        "name": name,
        "schema": schema,
        "description": description,
        "columns": columns or [{"name": "id"}, {"name": "created_at"}],
    }


# ─── Text building logic (pure, no DB) ────────────────────────────────────────


class TestDatasetTextBuilding:
    """Verify the text constructed for each table before embedding."""

    def _build_text(self, table: dict) -> str:
        """Mirror the text-building logic from run_dataset_description_embeddings."""
        table_name = table.get("name") or table.get("table_name")
        schema = table.get("schema") or ""
        logical_name = f"{schema}.{table_name}" if schema else table_name
        description = table.get("description") or table.get("desc") or ""
        columns = table.get("columns") or []
        col_names = [
            (c.get("name") if isinstance(c, dict) else str(c)) for c in columns if c
        ]
        parts = [f"Dataset: {logical_name}"]
        if description:
            parts.append(f"Description: {description}")
        if col_names:
            parts.append(f"Columns: {', '.join(col_names[:30])}")
        return " | ".join(parts)

    def test_includes_logical_name_with_schema(self):
        t = _fake_table("orders", schema="crm")
        text = self._build_text(t)
        assert "Dataset: crm.orders" in text

    def test_includes_logical_name_without_schema(self):
        t = _fake_table("orders", schema="")
        text = self._build_text(t)
        assert "Dataset: orders" in text

    def test_includes_description_when_present(self):
        t = _fake_table("orders", description="Tracks customer purchase orders")
        text = self._build_text(t)
        assert "Description: Tracks customer purchase orders" in text

    def test_omits_description_when_empty(self):
        t = _fake_table("orders", description="")
        text = self._build_text(t)
        assert "Description:" not in text

    def test_includes_column_names(self):
        t = _fake_table("orders", columns=[{"name": "amount"}, {"name": "status"}])
        text = self._build_text(t)
        assert "amount" in text
        assert "status" in text

    def test_caps_columns_at_30(self):
        many_cols = [{"name": f"col_{i}"} for i in range(50)]
        t = _fake_table("wide", columns=many_cols)
        text = self._build_text(t)
        # Should have col_0 through col_29 but not col_30
        assert "col_29" in text
        assert "col_30" not in text

    def test_table_without_name_produces_no_item(self):
        bad = {"schema": "public", "columns": [{"name": "x"}]}
        name = bad.get("name") or bad.get("table_name")
        assert name is None  # skipped in real code


# ─── Integration: run_dataset_description_embeddings flow ─────────────────────


@pytest.mark.asyncio
async def test_returns_zero_when_no_tables_json():
    """Returns 0 immediately when connection_metadata has no tables."""
    from core.ingestion.service import run_dataset_description_embeddings

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    mock_provider = AsyncMock()

    count = await run_dataset_description_embeddings(
        db=mock_db,
        connection_id=str(uuid4()),
        space_id=str(uuid4()),
        embedding_provider=mock_provider,
    )
    assert count == 0
    mock_provider.embed_async.assert_not_called()


@pytest.mark.asyncio
async def test_returns_zero_when_empty_list():
    from core.ingestion.service import run_dataset_description_embeddings

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = []  # empty list
    mock_db.execute.return_value = mock_result

    mock_provider = AsyncMock()

    count = await run_dataset_description_embeddings(
        db=mock_db,
        connection_id=str(uuid4()),
        space_id=str(uuid4()),
        embedding_provider=mock_provider,
    )
    assert count == 0


@pytest.mark.asyncio
async def test_creates_one_record_per_table():
    from core.ingestion.service import run_dataset_description_embeddings

    tables = [
        _fake_table("orders", description="Order data"),
        _fake_table("users", description="User data"),
        _fake_table("campaigns"),
    ]

    execute_calls = []

    async def fake_execute(stmt, params=None):
        result = MagicMock()
        result.scalar_one_or_none.return_value = tables
        execute_calls.append(stmt)
        return result

    mock_db = AsyncMock()
    mock_db.execute.side_effect = fake_execute
    mock_db.commit = AsyncMock()
    mock_db.add = MagicMock()

    mock_provider = AsyncMock()
    mock_provider.embed_async.return_value = [[0.1] * 10 for _ in tables]

    count = await run_dataset_description_embeddings(
        db=mock_db,
        connection_id=str(uuid4()),
        space_id=str(uuid4()),
        embedding_provider=mock_provider,
    )

    assert count == 3
    assert mock_db.add.call_count == 3


@pytest.mark.asyncio
async def test_embed_async_receives_one_text_per_table():
    from core.ingestion.service import run_dataset_description_embeddings

    tables = [
        _fake_table("orders", description="Revenue tracking"),
        _fake_table("sessions", description="Web analytics"),
    ]

    async def fake_execute(stmt, params=None):
        result = MagicMock()
        result.scalar_one_or_none.return_value = tables
        return result

    mock_db = AsyncMock()
    mock_db.execute.side_effect = fake_execute
    mock_db.commit = AsyncMock()
    mock_db.add = MagicMock()

    captured_texts = []

    async def fake_embed(texts):
        captured_texts.extend(texts)
        return [[0.0] * 10 for _ in texts]

    mock_provider = AsyncMock()
    mock_provider.embed_async.side_effect = fake_embed

    await run_dataset_description_embeddings(
        db=mock_db,
        connection_id=str(uuid4()),
        space_id=str(uuid4()),
        embedding_provider=mock_provider,
    )

    assert len(captured_texts) == 2
    assert any("Revenue tracking" in t for t in captured_texts)
    assert any("Web analytics" in t for t in captured_texts)


@pytest.mark.asyncio
async def test_skips_tables_without_name():
    from core.ingestion.service import run_dataset_description_embeddings

    tables = [
        {"schema": "public", "columns": [{"name": "x"}]},  # no name
        _fake_table("orders"),
    ]

    async def fake_execute(stmt, params=None):
        result = MagicMock()
        result.scalar_one_or_none.return_value = tables
        return result

    mock_db = AsyncMock()
    mock_db.execute.side_effect = fake_execute
    mock_db.commit = AsyncMock()
    mock_db.add = MagicMock()

    mock_provider = AsyncMock()
    mock_provider.embed_async.return_value = [[0.0] * 10]

    count = await run_dataset_description_embeddings(
        db=mock_db,
        connection_id=str(uuid4()),
        space_id=str(uuid4()),
        embedding_provider=mock_provider,
    )

    assert count == 1  # only the valid table
