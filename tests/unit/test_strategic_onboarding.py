"""
Unit tests for item 32 — Strategic Onboarding (OKR suggestions from datasets).

Tests:
  is_brain_empty:
    - returns True when no brain docs exist (count=0)
    - returns False when brain docs exist (count > 0)
    - returns True (safe fallback) on DB error

  suggest_okrs_from_datasets:
    - without LLM returns generic suggestions (non-empty list)
    - with LLM that returns valid JSON returns parsed list
    - with LLM that returns invalid JSON falls back to generic
    - with empty table_names returns generic suggestions
    - parses OKR type and category from LLM response

  save_okr_suggestions:
    - persists each suggestion as EmbeddingRecord
    - no-op when suggestions list is empty
    - no-op when space_id is empty

  load_okr_suggestions:
    - returns list of suggestion dicts from DB rows
    - returns empty list when no rows
    - returns empty list on DB error
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

SPACE_ID = "00000000-0000-0000-0000-000000000001"


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _db_scalar(val):
    db = AsyncMock()
    result = MagicMock()
    result.scalar.return_value = val
    db.execute.return_value = result
    return db


def _db_fetch(rows):
    db = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = rows
    db.execute.return_value = result
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _llm_with_response(text: str):
    msg = MagicMock()
    msg.content = text
    llm = MagicMock()
    llm._chat = None  # prevent MagicMock auto-create from being truthy
    llm.invoke.return_value = msg
    return llm


# ─── is_brain_empty ───────────────────────────────────────────────────────────


class TestIsBrainEmpty:
    @pytest.mark.asyncio
    async def test_empty_when_count_is_zero(self):
        from core.agents.strategic_onboarding import is_brain_empty

        db = _db_scalar(0)
        assert await is_brain_empty(db, SPACE_ID) is True

    @pytest.mark.asyncio
    async def test_not_empty_when_count_positive(self):
        from core.agents.strategic_onboarding import is_brain_empty

        db = _db_scalar(3)
        assert await is_brain_empty(db, SPACE_ID) is False

    @pytest.mark.asyncio
    async def test_empty_when_db_error(self):
        from core.agents.strategic_onboarding import is_brain_empty

        db = AsyncMock()
        db.execute.side_effect = Exception("DB error")
        assert await is_brain_empty(db, SPACE_ID) is True

    @pytest.mark.asyncio
    async def test_empty_when_no_space_id(self):
        from core.agents.strategic_onboarding import is_brain_empty

        db = AsyncMock()
        assert await is_brain_empty(db, "") is True
        db.execute.assert_not_called()


# ─── suggest_okrs_from_datasets ──────────────────────────────────────────────


class TestSuggestOkrsFromDatasets:
    def test_no_llm_returns_generic_list(self):
        from core.agents.strategic_onboarding import suggest_okrs_from_datasets

        result = suggest_okrs_from_datasets(["orders", "users"], llm=None)
        assert isinstance(result, list)
        assert len(result) >= 1
        assert "title" in result[0]

    def test_empty_tables_returns_generic(self):
        from core.agents.strategic_onboarding import suggest_okrs_from_datasets

        result = suggest_okrs_from_datasets([], llm=None)
        assert len(result) >= 1

    def test_llm_valid_json_response(self):
        from core.agents.strategic_onboarding import suggest_okrs_from_datasets

        llm_response = json.dumps(
            [
                {"title": "Grow MRR by 20%", "type": "okr", "category": "revenue"},
                {
                    "title": "Reduce churn below 5%",
                    "type": "kpi",
                    "category": "retention",
                },
            ]
        )
        llm = _llm_with_response(llm_response)
        result = suggest_okrs_from_datasets(["orders", "payments"], llm=llm)
        assert len(result) == 2
        assert result[0]["title"] == "Grow MRR by 20%"
        assert result[0]["type"] == "okr"
        assert result[1]["category"] == "retention"

    def test_llm_invalid_json_falls_back_to_generic(self):
        from core.agents.strategic_onboarding import suggest_okrs_from_datasets

        llm = _llm_with_response("not valid json {{")
        result = suggest_okrs_from_datasets(["orders"], llm=llm)
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_llm_markdown_fence_stripped(self):
        from core.agents.strategic_onboarding import suggest_okrs_from_datasets

        llm_response = (
            "```json\n"
            '[{"title": "Scale enterprise revenue", "type": "okr", "category": "revenue"}]\n'
            "```"
        )
        llm = _llm_with_response(llm_response)
        result = suggest_okrs_from_datasets(["accounts"], llm=llm)
        assert result[0]["title"] == "Scale enterprise revenue"

    def test_suggestion_fields_present(self):
        from core.agents.strategic_onboarding import suggest_okrs_from_datasets

        result = suggest_okrs_from_datasets(["orders", "users"], llm=None)
        for s in result:
            assert "title" in s
            assert "type" in s
            assert "category" in s


# ─── save_okr_suggestions ────────────────────────────────────────────────────


class TestSaveOkrSuggestions:
    @pytest.mark.asyncio
    async def test_persists_each_suggestion(self):
        from core.agents.strategic_onboarding import save_okr_suggestions

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.execute = AsyncMock()  # for the DELETE

        suggestions = [
            {"title": "Grow revenue 20%", "type": "okr", "category": "revenue"},
            {"title": "Reduce churn", "type": "kpi", "category": "retention"},
        ]
        with patch("db.models.EmbeddingRecord") as MockRecord:
            MockRecord.return_value = MagicMock()
            await save_okr_suggestions(db, SPACE_ID, suggestions)

        assert db.add.call_count == 2

    @pytest.mark.asyncio
    async def test_noop_when_empty_suggestions(self):
        from core.agents.strategic_onboarding import save_okr_suggestions

        db = AsyncMock()
        db.add = MagicMock()
        await save_okr_suggestions(db, SPACE_ID, [])
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_noop_when_no_space_id(self):
        from core.agents.strategic_onboarding import save_okr_suggestions

        db = AsyncMock()
        db.add = MagicMock()
        await save_okr_suggestions(
            db, "", [{"title": "test", "type": "okr", "category": "x"}]
        )
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_metadata_kind_is_okr_suggestion(self):
        from core.agents.strategic_onboarding import save_okr_suggestions

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.execute = AsyncMock()

        with patch("db.models.EmbeddingRecord") as MockRecord:
            MockRecord.return_value = MagicMock()
            await save_okr_suggestions(
                db,
                SPACE_ID,
                [{"title": "Grow MRR", "type": "okr", "category": "revenue"}],
            )

        kwargs = MockRecord.call_args[1]
        assert kwargs["extra_metadata"]["kind"] == "okr_suggestion"
        assert kwargs["extra_metadata"]["type"] == "okr"


# ─── load_okr_suggestions ────────────────────────────────────────────────────


class TestLoadOkrSuggestions:
    @pytest.mark.asyncio
    async def test_returns_suggestions_from_rows(self):
        from core.agents.strategic_onboarding import load_okr_suggestions

        rows = [
            (
                "Grow MRR by 20%",
                {"kind": "okr_suggestion", "type": "okr", "category": "revenue"},
            ),
            (
                "Reduce churn below 5%",
                {"kind": "okr_suggestion", "type": "kpi", "category": "retention"},
            ),
        ]
        db = _db_fetch(rows)
        result = await load_okr_suggestions(db, SPACE_ID)
        assert len(result) == 2
        assert result[0]["title"] == "Grow MRR by 20%"
        assert result[1]["type"] == "kpi"

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_rows(self):
        from core.agents.strategic_onboarding import load_okr_suggestions

        db = _db_fetch([])
        result = await load_okr_suggestions(db, SPACE_ID)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_db_error(self):
        from core.agents.strategic_onboarding import load_okr_suggestions

        db = AsyncMock()
        db.execute.side_effect = Exception("DB unavailable")
        result = await load_okr_suggestions(db, SPACE_ID)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_space_id(self):
        from core.agents.strategic_onboarding import load_okr_suggestions

        db = AsyncMock()
        result = await load_okr_suggestions(db, "")
        assert result == []
        db.execute.assert_not_called()
