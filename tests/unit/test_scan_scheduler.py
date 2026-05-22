"""
Unit tests for items 23-26 (Scan Scheduler + Silent run + Notification).

Coverage:
  - scan_schedule.py: get/set/update/due logic (items 23-24)
  - Silent run threshold check (item 26)
  - notify_scan_insight integration (item 25)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _meta(
    space_id: str,
    interval_hours: int = 24,
    enabled: bool = True,
    last_scan_at: Optional[str] = None,
    connection_id: str = "conn-1",
) -> dict:
    return {
        "kind": "scan_schedule",
        "space_id": space_id,
        "interval_hours": interval_hours,
        "enabled": enabled,
        "connection_id": connection_id,
        "last_scan_at": last_scan_at,
    }


def _fetchone_result(value) -> MagicMock:
    """Mock for db.execute() where result.fetchone() returns value."""
    mock_result = MagicMock()
    mock_result.fetchone.return_value = value
    return mock_result


def _fetchall_result(rows: list) -> MagicMock:
    """Mock for db.execute() where result.fetchall() returns rows."""
    mock_result = MagicMock()
    mock_result.fetchall.return_value = rows
    return mock_result


# ─── scan_schedule.get_scan_schedule ──────────────────────────────────────────


class TestGetScanSchedule:
    @pytest.mark.asyncio
    async def test_returns_none_when_not_configured(self):
        from core.agents.scan_schedule import get_scan_schedule

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_fetchone_result(None))

        result = await get_scan_schedule(db, "space-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_metadata_when_found(self):
        from core.agents.scan_schedule import get_scan_schedule

        metadata = _meta("space-1", interval_hours=6, enabled=True)
        # get_scan_schedule does row = result.fetchone(); return row[0]
        row = (metadata,)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_fetchone_result(row))

        result = await get_scan_schedule(db, "space-1")
        assert result is not None
        assert result["interval_hours"] == 6
        assert result["enabled"] is True


# ─── scan_schedule.set_scan_schedule ──────────────────────────────────────────


class TestSetScanSchedule:
    @pytest.mark.asyncio
    async def test_raises_on_invalid_interval(self):
        from core.agents.scan_schedule import set_scan_schedule

        db = AsyncMock()
        with pytest.raises(ValueError, match="interval_hours"):
            await set_scan_schedule(db, "space-1", interval_hours=5)

    @pytest.mark.asyncio
    async def test_valid_intervals_accepted(self):
        from core.agents.scan_schedule import set_scan_schedule

        for hours in (1, 6, 12, 24):
            db = AsyncMock()
            # set_scan_schedule calls get_scan_schedule (fetchone) then DELETE then add+flush
            db.execute = AsyncMock(return_value=_fetchone_result(None))
            db.add = MagicMock()
            db.flush = AsyncMock()
            # Should not raise
            await set_scan_schedule(db, "space-1", interval_hours=hours)

    @pytest.mark.asyncio
    async def test_preserves_last_scan_at_on_upsert(self):
        from core.agents.scan_schedule import set_scan_schedule

        # First execute call is get_scan_schedule (returns existing config with a timestamp)
        existing_ts = "2026-05-01T10:00:00+00:00"
        existing_meta = _meta(
            "space-1", interval_hours=24, enabled=True, last_scan_at=existing_ts
        )
        existing_row = (existing_meta,)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_fetchone_result(existing_row))
        added_records: list = []
        db.add = MagicMock(side_effect=lambda r: added_records.append(r))
        db.flush = AsyncMock()

        await set_scan_schedule(db, "space-1", interval_hours=12, enabled=False)

        # The new EmbeddingRecord should preserve last_scan_at
        assert len(added_records) == 1
        saved_meta = added_records[0].extra_metadata
        assert saved_meta["last_scan_at"] == existing_ts
        assert saved_meta["interval_hours"] == 12
        assert saved_meta["enabled"] is False


# ─── scan_schedule.update_last_scan_at ────────────────────────────────────────


class TestUpdateLastScanAt:
    @pytest.mark.asyncio
    async def test_calls_execute_and_flush(self):
        from core.agents.scan_schedule import update_last_scan_at

        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock())
        db.flush = AsyncMock()

        await update_last_scan_at(db, "space-1")

        db.execute.assert_called_once()
        db.flush.assert_called_once()
        # Verify the SQL mentions last_scan_at
        sql_text = str(db.execute.call_args[0][0])
        assert "last_scan_at" in sql_text

    @pytest.mark.asyncio
    async def test_noop_on_db_error(self):
        from core.agents.scan_schedule import update_last_scan_at

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=Exception("DB down"))
        db.flush = AsyncMock()

        # Should not raise — errors are caught and logged
        await update_last_scan_at(db, "space-unknown")


# ─── scan_schedule.get_spaces_due_for_scan ────────────────────────────────────


class TestGetSpacesDueForScan:
    """get_spaces_due_for_scan uses result.fetchall() returning plain tuples
    (space_id, interval_hours, last_scan_at_str, connection_id).
    Disabled spaces are filtered by SQL (enabled='true'), so the mock
    only needs to simulate the DB-side filter where relevant.
    """

    @pytest.mark.asyncio
    async def test_returns_empty_when_none_due(self):
        from core.agents.scan_schedule import get_spaces_due_for_scan

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_fetchall_result([]))

        due = await get_spaces_due_for_scan(db)
        assert due == []

    @pytest.mark.asyncio
    async def test_returns_space_when_overdue(self):
        from core.agents.scan_schedule import get_spaces_due_for_scan

        overdue_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        rows = [("space-2", 24, overdue_time, "conn-42")]

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_fetchall_result(rows))

        due = await get_spaces_due_for_scan(db)
        assert len(due) == 1
        assert due[0]["space_id"] == "space-2"
        assert due[0]["connection_id"] == "conn-42"

    @pytest.mark.asyncio
    async def test_returns_space_when_never_scanned(self):
        from core.agents.scan_schedule import get_spaces_due_for_scan

        # last_scan_at = None means never scanned → always due
        rows = [("space-3", 1, None, "conn-99")]

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_fetchall_result(rows))

        due = await get_spaces_due_for_scan(db)
        assert len(due) == 1
        assert due[0]["space_id"] == "space-3"

    @pytest.mark.asyncio
    async def test_skips_space_not_yet_due(self):
        from core.agents.scan_schedule import get_spaces_due_for_scan

        recent_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        rows = [("space-4", 24, recent_time, "conn-7")]

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_fetchall_result(rows))

        due = await get_spaces_due_for_scan(db)
        assert due == []

    @pytest.mark.asyncio
    async def test_deduplicates_multiple_connections_for_same_space(self):
        from core.agents.scan_schedule import get_spaces_due_for_scan

        overdue = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        rows = [
            ("space-5", 24, overdue, "conn-A"),
            ("space-5", 24, overdue, "conn-B"),  # same space, different conn
        ]

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_fetchall_result(rows))

        due = await get_spaces_due_for_scan(db)
        # Should pick only one entry per space
        assert len(due) == 1
        assert due[0]["space_id"] == "space-5"
        assert due[0]["connection_id"] == "conn-A"  # first wins


# ─── Item 26: Silent run threshold ────────────────────────────────────────────


class TestSilentRunThreshold:
    """Tests the logic that skips save+notify for short scan answers."""

    def _call_silent_check(self, text: str, threshold: int = 120) -> bool:
        """Reproduces the inline silent-check logic from connection_query.py."""
        return len(text.strip()) < threshold

    def test_short_answer_is_silent(self):
        assert self._call_silent_check("OK") is True

    def test_long_answer_is_not_silent(self):
        long_text = "A" * 150
        assert self._call_silent_check(long_text) is False

    def test_exactly_at_threshold_is_not_silent(self):
        text = "A" * 120
        assert self._call_silent_check(text) is False

    def test_one_below_threshold_is_silent(self):
        text = "A" * 119
        assert self._call_silent_check(text) is True

    def test_whitespace_only_is_silent(self):
        assert self._call_silent_check("   \n  ") is True

    def test_custom_threshold(self):
        assert self._call_silent_check("A" * 50, threshold=60) is True
        assert self._call_silent_check("A" * 60, threshold=60) is False


# ─── Item 25: notify_scan_insight ─────────────────────────────────────────────


class TestNotifyScanInsight:
    def test_returns_true_on_success(self):
        from core.clients.backend_client import BackendClient

        with patch.object(
            BackendClient, "__init__", lambda self, base_url, timeout=30.0: None
        ):
            client = BackendClient.__new__(BackendClient)
            mock_http = MagicMock()
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_http.post.return_value = mock_response
            client._http = mock_http

            result = client.notify_scan_insight(
                "space-1", "Big finding", "Details here"
            )

        assert result is True
        mock_http.post.assert_called_once()
        call_kwargs = mock_http.post.call_args
        assert "/ai/scan-insights/notify" in call_kwargs[0][0]

    def test_returns_false_on_http_error(self):
        from core.clients.backend_client import BackendClient

        with patch.object(
            BackendClient, "__init__", lambda self, base_url, timeout=30.0: None
        ):
            client = BackendClient.__new__(BackendClient)
            mock_http = MagicMock()
            mock_http.post.side_effect = Exception("connection refused")
            client._http = mock_http

            result = client.notify_scan_insight("space-1", "title")

        assert result is False

    def test_summary_truncated_to_500_chars(self):
        from core.clients.backend_client import BackendClient

        with patch.object(
            BackendClient, "__init__", lambda self, base_url, timeout=30.0: None
        ):
            client = BackendClient.__new__(BackendClient)
            mock_http = MagicMock()
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_http.post.return_value = mock_response
            client._http = mock_http

            long_summary = "X" * 1000
            client.notify_scan_insight("space-1", "title", long_summary)

        payload = mock_http.post.call_args[1]["json"]
        assert len(payload["summary"]) == 500

    def test_payload_contains_space_id_and_title(self):
        from core.clients.backend_client import BackendClient

        with patch.object(
            BackendClient, "__init__", lambda self, base_url, timeout=30.0: None
        ):
            client = BackendClient.__new__(BackendClient)
            mock_http = MagicMock()
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_http.post.return_value = mock_response
            client._http = mock_http

            client.notify_scan_insight("space-xyz", "My Title", "summary text")

        payload = mock_http.post.call_args[1]["json"]
        assert payload["space_id"] == "space-xyz"
        assert payload["title"] == "My Title"


# ─── QueryResponse schema fields ──────────────────────────────────────────────


class TestQueryResponseScanFields:
    def test_scan_fields_default_to_none(self):
        from api.schemas import QueryResponse, QueryResultMeta

        meta = QueryResultMeta()
        resp = QueryResponse(answer="ok", meta=meta)
        assert resp.scan_silent is None
        assert resp.scan_insight_title is None

    def test_scan_fields_accept_values(self):
        from api.schemas import QueryResponse, QueryResultMeta

        meta = QueryResultMeta()
        resp = QueryResponse(
            answer="ok",
            meta=meta,
            scan_silent=False,
            scan_insight_title="Revenue dropped 12% last week",
        )
        assert resp.scan_silent is False
        assert resp.scan_insight_title == "Revenue dropped 12% last week"
