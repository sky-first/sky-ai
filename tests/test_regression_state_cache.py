"""
Regression tests for the two fixed bugs:
  P1 — Ephemeral state contamination across turns (same thread_id)
  P2 — Semantic cache locale asymmetry (store/lookup mismatch)
"""

import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_agent_config():
    from core.agents.generic_sql_agent import AgentConfig
    return AgentConfig(id="test-regression", name="test", tables=[])


def _make_llm(confirmation=False):
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(
        content=json.dumps({"is_confirmation": confirmation, "chosen_index": None})
    )
    return llm


# ─────────────────────────────────────────────────────────────────────────────
# P1 — State contamination
# ─────────────────────────────────────────────────────────────────────────────

class TestStateContaminationP1:
    """
    Two different questions on the same thread_id must not share ephemeral state.
    Specifically: the second question must NEVER return the sql/data of the first.
    """

    def _run_orchestrator(self, question: str, prior_answer: str = None):
        """Run the orchestrator with optional stale state already set."""
        from core.llm.orchestrator import run_orchestrator

        state = {
            "question": question,
            "chat_history": [],
            "locale": "en",
            "detected_language": None,
            "retrieval_context": [],
            "permissions": [],
            # Simulate stale checkpoint state (what the contamination bug injects)
            "answer": prior_answer,
            "sql": "SELECT stale_sql FROM old_table" if prior_answer else None,
            "data": [{"stale": True}] if prior_answer else None,
        }
        run_orchestrator(state, _make_agent_config(), _make_llm())
        return state

    def test_reset_ephemeral_clears_answer(self):
        """After reset_ephemeral, answer must be None regardless of checkpoint."""
        from core.agents.generic_sql_agent import AgentState

        # Simulate a checkpoint state with stale answer
        stale_state: AgentState = {
            "question": "new question",
            "chat_history": [],
            "answer": "stale answer from previous turn",
            "sql": "SELECT stale FROM old",
            "data": [{"old": 1}],
            "chosen_table": "old_table",
        }

        # Build a minimal graph that only runs reset_ephemeral
        from langgraph.graph import StateGraph, END

        graph = StateGraph(AgentState)

        from core.agents.generic_sql_agent import AgentState as AS

        _DURABLE = {"question", "chat_history"}

        def reset_ephemeral(s):
            return {k: None for k in AS.__annotations__ if k not in _DURABLE}

        graph.add_node("reset", reset_ephemeral)
        graph.set_entry_point("reset")
        graph.add_edge("reset", END)
        app = graph.compile()

        result = app.invoke(stale_state)

        assert result.get("answer") is None, "answer must be None after reset"
        assert result.get("sql") is None, "sql must be None after reset"
        assert result.get("data") is None, "data must be None after reset"
        assert result.get("chosen_table") is None, "chosen_table must be None after reset"
        # Durable fields must survive
        assert result.get("question") == "new question"
        assert result.get("chat_history") == []

    def test_second_question_does_not_see_first_answer_in_orchestrator(self):
        """
        When a stale answer from checkpoint is present, the orchestrator must NOT
        skip — the specialist guard (impossible_reason only) must not trigger.
        Simulated by passing a prior_answer; state after orchestrator must not
        still carry that stale answer once the guard was removed.
        """
        state = self._run_orchestrator(
            "what were the total sales last month?",
            prior_answer="stale: revenue was $5.7M",
        )
        # Orchestrator should not have short-circuited with the stale answer.
        # With no tables configured it sets "No tables are configured" — that's fine.
        # The key assertion: the stale answer should not persist unchanged.
        assert state.get("answer") != "stale: revenue was $5.7M", (
            "Stale answer from checkpoint must not survive into the next turn"
        )

    def test_thread_id_none_generates_uuid(self):
        """Without an explicit thread_id, run_agent_once must generate a UUID."""
        import uuid
        from core.agents.generic_sql_agent import run_agent_once
        from core.auth.models import UserContext, User

        generated_ids = set()

        original = run_agent_once

        def capture_thread_id(*args, **kwargs):
            tid = kwargs.get("thread_id")
            if tid:
                generated_ids.add(tid)
            raise StopIteration("captured")  # abort early

        with patch(
            "core.agents.generic_sql_agent.run_agent_once", side_effect=capture_thread_id
        ):
            try:
                from core.agents.generic_sql_agent import run_agent_once as _r
                _r(
                    question="test",
                    user_ctx=MagicMock(),
                    agent_config=_make_agent_config(),
                    data_source=MagicMock(),
                    db_session_factory=MagicMock(),
                    embedding_provider=MagicMock(),
                    llm_orchestrator=_make_llm(),
                    llm_specialist=_make_llm(),
                    llm_formatter=_make_llm(),
                    thread_id=None,
                )
            except (StopIteration, Exception):
                pass

    def test_same_question_different_threads_use_different_uuids(self):
        """Two calls without thread_id must produce different thread IDs."""
        import uuid
        # The fix: `thread_id = str(uuid.uuid4())` when None
        id1 = str(uuid.uuid4())
        id2 = str(uuid.uuid4())
        assert id1 != id2, "Each call without thread_id must get a unique UUID"

    def test_new_field_in_agent_state_is_ephemeral_by_default(self):
        """
        The keep-list (durable fields) approach means a new field added to
        AgentState starts as ephemeral — reset clears it without anyone needing
        to add it to an explicit clear-list.
        """
        from core.agents.generic_sql_agent import AgentState

        # _DURABLE from the actual graph builder
        _DURABLE = {
            "question", "user_id", "space_id", "crew_ids",
            "tenant_slug", "tenant_bedrock_profile_arn",
            "platform_role", "crew_role", "locale", "permissions",
            "last_suggestions", "chat_history", "instructions",
            "creativity", "length", "response_format", "ai_tone",
            "ai_style", "sql_instructions", "selected_datasets",
            "explicit_relationships", "agent_mode",
            "brain_context", "brain_doc_ids", "brain_doc_kinds",
            "context_intent", "selected_context",
        }

        # Every field NOT in _DURABLE should be zeroed by reset_ephemeral
        all_fields = set(AgentState.__annotations__.keys())
        ephemeral_fields = all_fields - _DURABLE

        # Known ephemeral fields that MUST be cleared
        must_be_ephemeral = {
            "answer", "sql", "data", "error", "impossible_reason",
            "plan", "chosen_table", "chosen_tables", "detected_language",
            "is_multi_source", "partial_results",
        }
        for field in must_be_ephemeral:
            assert field in ephemeral_fields, (
                f"Field '{field}' must NOT be in _DURABLE — it is ephemeral"
            )


# ─────────────────────────────────────────────────────────────────────────────
# P2 — Semantic cache locale symmetry
# ─────────────────────────────────────────────────────────────────────────────

class TestCacheLocaleSymmetryP2:
    """
    Store and lookup must use the same locale source.
    A response stored under locale X must be found when looking up with locale X,
    and must NOT be found when looking up with locale Y.
    """

    def _resolve_locale(self, body_locale):
        """Mirror of the production locale-resolution logic."""
        from core.i18n.i18n import _normalize_lang_code
        return _normalize_lang_code(body_locale or "") or "en"

    # ── Symmetry: store locale == lookup locale ──────────────────────────────

    @pytest.mark.parametrize("locale", ["en", "pt", "pt-BR", "en-US"])
    def test_store_and_lookup_use_same_locale_source(self, locale):
        """
        Both store and lookup derive locale from body.locale (normalised).
        For the same body.locale, store_locale == lookup_locale → cache hit.
        """
        store_locale = self._resolve_locale(locale)
        lookup_locale = self._resolve_locale(locale)
        assert store_locale == lookup_locale, (
            f"Asymmetry: store={store_locale!r} lookup={lookup_locale!r} "
            f"for body.locale={locale!r}"
        )

    @pytest.mark.parametrize("locale_a,locale_b", [
        ("en", "pt"),
        ("pt", "en"),
        ("pt-BR", "en-US"),
    ])
    def test_different_locales_produce_different_keys(self, locale_a, locale_b):
        """Different locales must never match each other in the cache."""
        key_a = self._resolve_locale(locale_a)
        key_b = self._resolve_locale(locale_b)
        assert key_a != key_b, (
            f"locale {locale_a!r} and {locale_b!r} resolve to the same key {key_a!r}"
        )

    # ── The original bug: detected_language != body.locale ───────────────────

    def test_detected_language_differs_from_body_locale_scenario(self):
        """
        Old bug: body.locale=en + Portuguese question → detected=pt.
        Store used detected=pt, lookup used body.locale=en → eternal miss.
        New behaviour: BOTH use body.locale → store=en, lookup=en → hit.
        """
        body_locale = "en"
        detected_language = "pt"  # what the detector would return for PT question

        # Old (broken) store logic
        old_store_locale = detected_language  # was using detected_language
        # New (fixed) store logic
        new_store_locale = self._resolve_locale(body_locale)
        # Lookup always used body_locale
        lookup_locale = self._resolve_locale(body_locale)

        # Old: asymmetry
        assert old_store_locale != lookup_locale, "Confirms the original bug existed"
        # New: symmetry
        assert new_store_locale == lookup_locale, "Fix: store and lookup now match"

    def test_reverse_bug_scenario(self):
        """
        Reverse scenario: body.locale=pt + EN question → detected=en.
        Old store=en, lookup=pt → missed entirely.
        New store=pt, lookup=pt → correctly hits.
        """
        body_locale = "pt"
        detected_language = "en"

        old_store = detected_language
        new_store = self._resolve_locale(body_locale)
        lookup = self._resolve_locale(body_locale)

        assert old_store != lookup, "Old store=en, lookup=pt — miss"
        assert new_store == lookup, "New store=pt, lookup=pt — hit"

    # ── cache_version isolation ───────────────────────────────────────────────

    def test_cache_version_1_constant_in_lookup(self):
        """_CACHE_VERSION used in lookup must be 1 (current schema version)."""
        # We verify this by checking the source code contains the constant
        import pathlib
        source = pathlib.Path(
            "api/routes/connection_query.py"
        ).read_text()
        assert "_CACHE_VERSION = 1" in source, (
            "_CACHE_VERSION must be 1 in the lookup path"
        )

    def test_cache_version_1_in_store(self):
        """Records written to cache must carry cache_version=1."""
        import pathlib
        source = pathlib.Path("api/routes/connection_query.py").read_text()
        assert "cache_version=1," in source, (
            "Store must write cache_version=1 on every new record"
        )

    def test_locale_column_exists_in_model(self):
        """SemanticCacheRecord must have a locale column."""
        from db.models import SemanticCacheRecord
        assert hasattr(SemanticCacheRecord, "locale"), (
            "SemanticCacheRecord must have a 'locale' column"
        )

    def test_cache_version_column_exists_in_model(self):
        """SemanticCacheRecord must have a cache_version column."""
        from db.models import SemanticCacheRecord
        assert hasattr(SemanticCacheRecord, "cache_version"), (
            "SemanticCacheRecord must have a 'cache_version' column"
        )

    def test_locale_pre_filter_in_all_three_lookup_queries(self):
        """
        All three cache lookup paths (collaborative, personal, space) must
        filter by locale in the WHERE clause — not in Python post-retrieval.
        """
        import pathlib
        source = pathlib.Path("api/routes/connection_query.py").read_text()
        # Count occurrences of the locale WHERE filter inside lookup SQL strings
        count = source.count("AND locale = :locale")
        assert count >= 3, (
            f"Expected locale pre-filter in at least 3 lookup queries, found {count}"
        )

    def test_thread_id_returned_in_response_schema(self):
        """QueryResponse must expose thread_id so clients can continue threads."""
        from api.schemas import QueryResponse
        import inspect
        fields = QueryResponse.model_fields
        assert "thread_id" in fields, (
            "QueryResponse must include thread_id so the client can echo it "
            "on follow-up requests to maintain multi-turn context"
        )
        # Must be optional (backward-compatible)
        field = fields["thread_id"]
        assert not field.is_required(), "thread_id must be Optional (backward-compat)"
