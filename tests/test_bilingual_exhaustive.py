"""
Exhaustive bilingual EN/PT test suite — Phase 1 validation.

Structure:
  Layer 1 — Unit: every i18n function, all edge cases
  Layer 2 — Component: orchestrator state flow, formatter contract
  Layer 3 — System boundaries: gatekeeper paths, confirmation detection,
             known gaps (ensure_language bypass, jargon false-positives)
"""

import json
import re
import pytest
from unittest.mock import MagicMock

from core.i18n.i18n import (
    _normalize_lang_code,
    detect_language,
    get_message,
    language_decision,
    resolve_language,
    thread_language_from_history,
    unsupported_language_message,
    SUPPORTED_LANGUAGES,
    _CONFIDENCE_THRESHOLD,
    _MIN_TEXT_LENGTH,
)


# ────────────────────────────────────────────────────────────────────────────
# HELPERS
# ────────────────────────────────────────────────────────────────────────────

def make_llm(response_json: dict):
    """Return a mock LLM that returns a fixed JSON payload."""
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=json.dumps(response_json))
    return llm


def make_state(**kwargs) -> dict:
    """Minimal AgentState-like dict."""
    base = {
        "question": "",
        "chat_history": [],
        "last_suggestions": None,
        "locale": None,
        "detected_language": None,
    }
    base.update(kwargs)
    return base


# ────────────────────────────────────────────────────────────────────────────
# LAYER 1 — UNIT: i18n functions
# ────────────────────────────────────────────────────────────────────────────

class TestNormalizeLangCode:
    @pytest.mark.parametrize("raw,expected", [
        ("pt-BR", "pt"),
        ("pt_BR", "pt"),
        ("PT",    "pt"),
        ("pt",    "pt"),
        ("en-US", "en"),
        ("en_US", "en"),
        ("EN",    "en"),
        ("  en  ","en"),
        ("fr",    "fr"),
        ("",      ""),
        (None,    ""),
    ])
    def test_normalises(self, raw, expected):
        assert _normalize_lang_code(raw) == expected


class TestDetectLanguage:
    """Tests for the RAW detector — which can return unsupported codes."""

    def test_clear_english(self):
        assert detect_language("what were the total sales last month?") == "en"

    def test_clear_portuguese(self):
        assert detect_language("quais foram as vendas totais do mês passado?") == "pt"

    def test_short_text_falls_back_to_en(self):
        # Text shorter than _MIN_TEXT_LENGTH should fall back gracefully
        assert detect_language("ok") == "en"
        assert detect_language("sim") == "en"  # too short for confident detection

    def test_empty_string_returns_en(self):
        assert detect_language("") == "en"

    def test_none_like_empty_returns_en(self):
        assert detect_language("   ") == "en"

    def test_returns_string(self):
        result = detect_language("bonjour le monde")
        assert isinstance(result, str) and len(result) >= 2


class TestResolveLanguage:
    """Priority chain: locale → thread → detect → fallback."""

    # --- locale wins ---
    def test_locale_pt_beats_en_thread_and_en_question(self):
        assert resolve_language(
            "what were the sales?", locale="pt-BR", thread_language="en"
        ) == "pt"

    def test_locale_en_beats_pt_thread(self):
        assert resolve_language(
            "quais as vendas?", locale="en", thread_language="pt"
        ) == "en"

    def test_locale_region_variant_normalised(self):
        assert resolve_language("hi", locale="pt_BR") == "pt"
        assert resolve_language("hi", locale="en-US") == "en"

    def test_unsupported_locale_falls_through(self):
        # "fr" is not supported → should fall through to thread/detect
        result = resolve_language(
            "what were the sales?", locale="fr", thread_language="pt"
        )
        assert result == "pt"

    # --- thread wins when no locale ---
    def test_thread_pt_keeps_short_followup_in_pt(self):
        assert resolve_language("sim", thread_language="pt") == "pt"

    def test_thread_en_keeps_short_followup_in_en(self):
        assert resolve_language("ok", thread_language="en") == "en"

    def test_thread_overrides_ambiguous_detection(self):
        # "sim" alone can't be confidently detected; thread must win
        assert resolve_language("sim", thread_language="pt") == "pt"

    # --- detect used when no locale/thread ---
    def test_detects_pt_without_signals(self):
        assert resolve_language("quais foram as vendas do mês passado?") == "pt"

    def test_detects_en_without_signals(self):
        assert resolve_language("what were the sales last month?") == "en"

    # --- fallback ---
    def test_empty_question_no_signals_returns_en(self):
        assert resolve_language("") == "en"

    def test_always_returns_supported_language(self):
        # Spanish question, no signals → must land on en or pt, never "es"
        result = resolve_language("¿cuáles fueron las ventas del mes pasado?")
        assert result in SUPPORTED_LANGUAGES


class TestThreadLanguageFromHistory:

    def test_none_history_returns_none(self):
        assert thread_language_from_history(None) is None

    def test_empty_history_returns_none(self):
        assert thread_language_from_history([]) is None

    def test_picks_first_reliable_user_pt(self):
        history = [
            {"role": "user", "content": "quais foram as vendas do mês passado?"},
            {"role": "assistant", "content": "As vendas foram R$ 1,2 milhão."},
        ]
        assert thread_language_from_history(history) == "pt"

    def test_picks_first_reliable_user_en(self):
        history = [
            {"role": "user", "content": "what were the total sales last month?"},
            {"role": "assistant", "content": "Sales were $1.2M."},
        ]
        assert thread_language_from_history(history) == "en"

    def test_ignores_assistant_messages(self):
        history = [
            {"role": "assistant", "content": "quais foram as vendas do mês passado?"},
            {"role": "user",      "content": "what were the total sales last month?"},
        ]
        # Should pick the user message (EN), not the assistant (PT)
        assert thread_language_from_history(history) == "en"

    def test_ignores_short_user_messages(self):
        history = [
            {"role": "user", "content": "ok"},          # too short
            {"role": "user", "content": "sim"},          # too short
            {"role": "user", "content": "what were the total sales last month?"},
        ]
        assert thread_language_from_history(history) == "en"

    def test_all_short_messages_returns_none(self):
        history = [
            {"role": "user", "content": "ok"},
            {"role": "user", "content": "sim"},
        ]
        assert thread_language_from_history(history) is None

    def test_sticky_scenario_end_to_end(self):
        """Classic bug: PT conversation, user replies 'sim' → must stay PT."""
        history = [
            {"role": "user",      "content": "quais foram as vendas do mês passado?"},
            {"role": "assistant", "content": "As vendas foram R$ 1,2 milhão."},
        ]
        thread_lang = thread_language_from_history(history)
        assert resolve_language("sim", thread_language=thread_lang) == "pt"


class TestLanguageDecision:
    """Gatekeeper: returns (blocked, lang)."""

    # --- should NOT block ---
    def test_clear_en_not_blocked(self):
        blocked, lang = language_decision("what were the sales last month?")
        assert blocked is False and lang == "en"

    def test_clear_pt_not_blocked(self):
        blocked, lang = language_decision("quais foram as vendas do mês passado?")
        assert blocked is False and lang == "pt"

    def test_locale_prevents_block(self):
        blocked, lang = language_decision(
            "quel a été le chiffre d'affaires?", locale="pt-BR"
        )
        assert blocked is False and lang == "pt"

    def test_thread_prevents_block(self):
        blocked, lang = language_decision(
            "quel a été le chiffre d'affaires?", thread_language="en"
        )
        assert blocked is False and lang == "en"

    def test_short_message_not_blocked_falls_back_to_en(self):
        # Short text → detect_language returns "en" (fallback) → not blocked
        blocked, _ = language_decision("sim")
        assert blocked is False

    def test_jargon_heavy_pt_not_blocked(self):
        # Business jargon in PT — common false-positive trigger for langdetect.
        # Only include questions where langdetect is reliably confident (>70%)
        # about PT. Terms like "ROI da campanha de marketing" are genuinely
        # ambiguous (EN loan words) and may flip — see test_known_gap below.
        for question in [
            "qual o churn da NovaTech no Q3?",
            "EBITDA do último trimestre",
            "qual o MRR do produto X?",
        ]:
            blocked, _ = language_decision(question)
            assert blocked is False, f"Falsely blocked: {question!r}"

    def test_known_gap_jargon_with_en_loanwords(self):
        """
        KNOWN GAP: Questions mixing PT structure with EN acronyms/loanwords
        (e.g. "ROI da campanha de marketing") are non-deterministically
        classified by langdetect. Without a thread or locale, they can be
        blocked as 'unsupported language'.

        Mitigation: locale or a prior PT turn prevents the block.
        This test documents the gap — fix it in the langdetect layer or by
        always requiring locale in the request.
        """
        question = "ROI da campanha de marketing"
        # With locale set: never blocked
        blocked_with_locale, _ = language_decision(question, locale="pt")
        assert blocked_with_locale is False
        # With thread: never blocked
        blocked_with_thread, _ = language_decision(question, thread_language="pt")
        assert blocked_with_thread is False
        # Without signals: may or may not block (non-deterministic) — just
        # assert it never returns an unsupported language code when not blocked.
        blocked_raw, lang_raw = language_decision(question)
        if not blocked_raw:
            assert lang_raw in SUPPORTED_LANGUAGES

    # --- should block ---
    def test_clear_french_blocked_no_signals(self):
        blocked, lang = language_decision(
            "quel a été le chiffre d'affaires du mois dernier en France?"
        )
        assert blocked is True
        assert lang in SUPPORTED_LANGUAGES  # fallback to en/pt even when blocked

    def test_always_returns_supported_language_even_when_blocked(self):
        blocked, lang = language_decision(
            "quel a été le chiffre d'affaires du mois dernier en France?"
        )
        assert lang in SUPPORTED_LANGUAGES


class TestUnsupportedLanguageMessage:

    def test_contains_english(self):
        msg = unsupported_language_message()
        assert "English and Portuguese" in msg

    def test_contains_portuguese(self):
        msg = unsupported_language_message()
        assert "inglês e português" in msg

    def test_is_non_empty_string(self):
        msg = unsupported_language_message()
        assert isinstance(msg, str) and len(msg) > 20


class TestGetMessage:
    """i18n message catalogue."""

    @pytest.mark.parametrize("key", [
        "SECURITY_BLOCKED", "PII_BLOCKED", "TECHNICAL_ERROR",
        "NO_DATA_FOUND", "NO_DATA_GENERIC",
    ])
    def test_returns_en_and_pt_for_all_keys(self, key):
        en_msg = get_message(key, "en", topic="X")
        pt_msg = get_message(key, "pt", topic="X")
        assert isinstance(en_msg, str) and len(en_msg) > 5
        assert isinstance(pt_msg, str) and len(pt_msg) > 5
        # They should differ (actual translations, not same string)
        assert en_msg != pt_msg

    def test_unknown_key_falls_back_gracefully(self):
        result = get_message("NONEXISTENT_KEY", "en")
        assert isinstance(result, str)

    def test_unsupported_lang_falls_back_to_en(self):
        en = get_message("TECHNICAL_ERROR", "en")
        fr = get_message("TECHNICAL_ERROR", "fr")
        assert en == fr  # "fr" not supported → falls back to en


# ────────────────────────────────────────────────────────────────────────────
# LAYER 2 — COMPONENT: orchestrator state flow
# ────────────────────────────────────────────────────────────────────────────

class TestOrchestratorLanguageFlow:
    """
    Test the language decision inside run_orchestrator without a real LLM or DB.
    We call run_orchestrator with a minimal AgentConfig that has no tables,
    which causes it to return early after setting detected_language — giving us
    a clean window to assert on language resolution.
    """

    def _run(self, question, chat_history=None, locale=None, last_suggestions=None):
        from core.llm.orchestrator import run_orchestrator
        from core.agents.generic_sql_agent import AgentConfig

        state = make_state(
            question=question,
            chat_history=chat_history or [],
            locale=locale,
            last_suggestions=last_suggestions,
        )
        # AgentConfig with no tables → orchestrator exits early after lang detection
        config = AgentConfig(id="test", name="test", tables=[])
        llm = make_llm({"is_confirmation": False, "chosen_index": None})
        run_orchestrator(state, config, llm)
        return state

    def test_clear_pt_question_detected(self):
        state = self._run("quais foram as vendas do mês passado?")
        assert state["detected_language"] == "pt"

    def test_clear_en_question_detected(self):
        state = self._run("what were the total sales last month?")
        assert state["detected_language"] == "en"

    def test_locale_pt_overrides_en_question(self):
        state = self._run("what were the sales?", locale="pt-BR")
        assert state["detected_language"] == "pt"

    def test_thread_sticky_keeps_pt_on_short_followup(self):
        history = [
            {"role": "user", "content": "quais foram as vendas do mês passado?"},
            {"role": "assistant", "content": "As vendas foram R$ 1,2 milhão."},
        ]
        state = self._run("sim", chat_history=history)
        assert state["detected_language"] == "pt"

    def test_thread_sticky_keeps_en_on_ok(self):
        history = [
            {"role": "user", "content": "what were the total sales last month?"},
        ]
        state = self._run("ok", chat_history=history)
        assert state["detected_language"] == "en"

    def test_unsupported_language_sets_answer_and_returns(self):
        state = self._run(
            "quel a été le chiffre d'affaires du mois dernier en France?"
        )
        assert "answer" in state
        # Message must be bilingual
        assert "English and Portuguese" in state["answer"]
        assert "inglês e português" in state["answer"]

    def test_locale_prevents_block_for_unsupported_detected_lang(self):
        state = self._run(
            "quel a été le chiffre d'affaires?", locale="pt-BR"
        )
        # Should NOT be blocked; detected_language should be "pt"
        assert state.get("answer") != unsupported_language_message()
        assert state["detected_language"] == "pt"

    def test_jargon_pt_not_blocked_no_history(self):
        """Business jargon common in PT mixed with EN terms."""
        for question in [
            "qual o churn da NovaTech no Q3?",
            "me mostra o EBITDA consolidado",
            "qual foi o MRR do mês passado?",
        ]:
            state = self._run(question)
            assert "answer" not in state or "inglês e português" not in state.get("answer", ""), \
                f"Falsely blocked: {question!r}"


class TestOrchestratorConfirmationFlow:
    """Context-recall: numeric, obvious PT, LLM-decided."""

    SUGGESTIONS = [
        "vendas por região no último trimestre",
        "comparativo com o ano passado",
        "top 10 clientes por receita",
    ]

    def _run(self, question, llm_response=None):
        from core.llm.orchestrator import run_orchestrator
        from core.agents.generic_sql_agent import AgentConfig

        state = make_state(
            question=question,
            last_suggestions=self.SUGGESTIONS,
            chat_history=[
                {"role": "user",      "content": "quais são as opções?"},
                {"role": "assistant", "content": "Posso mostrar: " + ", ".join(self.SUGGESTIONS)},
            ],
        )
        config = AgentConfig(id="test", name="test", tables=[])
        resp = llm_response or {"is_confirmation": False, "chosen_index": None}
        llm = make_llm(resp)
        run_orchestrator(state, config, llm)
        return state

    def test_numeric_1_maps_to_first_suggestion(self):
        state = self._run("1")
        assert state["question"] == self.SUGGESTIONS[0]

    def test_numeric_2_maps_to_second_suggestion(self):
        state = self._run("2")
        assert state["question"] == self.SUGGESTIONS[1]

    def test_obvious_affirmation_sim(self):
        state = self._run("sim")
        assert state["question"] == self.SUGGESTIONS[0]

    def test_obvious_affirmation_yes(self):
        state = self._run("yes")
        assert state["question"] == self.SUGGESTIONS[0]

    def test_llm_decides_second_option_pt(self):
        state = self._run(
            "manda o segundo",
            llm_response={"is_confirmation": True, "chosen_index": 1},
        )
        assert state["question"] == self.SUGGESTIONS[1]

    def test_llm_decides_not_confirmation(self):
        original = "qual foi o crescimento do produto X?"
        state = self._run(
            original,
            llm_response={"is_confirmation": False, "chosen_index": None},
        )
        assert state["question"] == original


# ────────────────────────────────────────────────────────────────────────────
# LAYER 3 — SYSTEM BOUNDARIES & KNOWN GAPS
# ────────────────────────────────────────────────────────────────────────────

class TestFormatterLanguageContract:
    """
    Verify formatter respects detected_language from state.
    Gap: if detected_language missing, _ensure_language falls back to raw
    detect_language (bypasses the chain). We document this as a known gap.
    """

    def test_ensure_language_uses_state_when_present(self):
        from core.llm.formatter import _ensure_language
        # When state has detected_language, it must be used verbatim
        assert _ensure_language("sim", "pt") == "pt"
        assert _ensure_language("what were the sales?", "en") == "en"

    def test_ensure_language_detects_when_state_missing(self):
        from core.llm.formatter import _ensure_language
        # GAP: when detected_language is None, falls back to raw detection.
        # For a clear question this still works, but short follow-ups may differ.
        result = _ensure_language("quais foram as vendas do mês passado?", None)
        assert result == "pt"

    def test_known_gap_short_followup_without_state_lang(self):
        """
        KNOWN GAP (documented): if detected_language is not propagated in state
        to the formatter (e.g. a node fails before setting it), a short follow-up
        like 'sim' may be detected as 'en' because it bypasses the sticky chain.
        This test documents the gap — do NOT remove it; fix the gap instead.
        """
        from core.llm.formatter import _ensure_language
        result = _ensure_language("sim", None)
        # langdetect returns 'en' for 'sim' (too short) — acceptable given the gap
        assert result in ("en", "pt")  # not "es", "fr", etc.


class TestFormatterPromptLanguage:
    """The formatter prompt must enforce the resolved language.

    Uses build_formatter_prompt_legacy (simpler interface) which shares the
    same language-resolution logic as the main builder.
    """

    def test_pt_prompt_says_portuguese(self):
        from core.llm.prompts.formatter_prompts import build_formatter_prompt_legacy
        sys_msg, _ = build_formatter_prompt_legacy(
            question="quais as vendas?",
            sql="SELECT total FROM sales",
            data_preview="total: 1000",
            detected_language="pt",
        )
        assert "Portuguese" in sys_msg["content"]

    def test_en_prompt_says_english(self):
        from core.llm.prompts.formatter_prompts import build_formatter_prompt_legacy
        sys_msg, _ = build_formatter_prompt_legacy(
            question="what were the sales?",
            sql="SELECT total FROM sales",
            data_preview="total: 1000",
            detected_language="en",
        )
        assert "English" in sys_msg["content"]

    def test_none_detected_language_defaults_to_en(self):
        from core.llm.prompts.formatter_prompts import build_formatter_prompt_legacy
        sys_msg, _ = build_formatter_prompt_legacy(
            question="what were the sales?",
            sql="SELECT total FROM sales",
            data_preview="total: 1000",
            detected_language=None,
        )
        assert "English" in sys_msg["content"]

    def test_unsupported_detected_language_defaults_to_en(self):
        from core.llm.prompts.formatter_prompts import build_formatter_prompt_legacy
        sys_msg, _ = build_formatter_prompt_legacy(
            question="quelles sont les ventes?",
            sql="SELECT total FROM sales",
            data_preview="total: 1000",
            detected_language="fr",  # unsupported
        )
        assert "English" in sys_msg["content"]


class TestGatekeeperPaths:
    """
    The gatekeeper exists in 3 places: orchestrator, sync route, streaming route.
    We test the orchestrator gate here; route gates require HTTP client.
    """

    def _gate_result(self, question, locale=None, thread_language=None):
        blocked, lang = language_decision(
            question, locale=locale, thread_language=thread_language
        )
        return blocked, lang

    @pytest.mark.parametrize("question", [
        "quel a été le chiffre d'affaires du mois dernier en France?",
        "¿cuáles fueron las ventas del mes pasado en España?",
        "Was waren die Verkaufszahlen im letzten Monat?",
    ])
    def test_clear_unsupported_languages_blocked(self, question):
        blocked, _ = self._gate_result(question)
        assert blocked is True

    @pytest.mark.parametrize("question,expected_lang", [
        ("what were the sales last month?", "en"),
        ("quais foram as vendas do mês passado?", "pt"),
    ])
    def test_supported_languages_pass(self, question, expected_lang):
        blocked, lang = self._gate_result(question)
        assert blocked is False
        assert lang == expected_lang

    def test_gatekeeper_block_message_is_bilingual(self):
        msg = unsupported_language_message()
        assert "English" in msg and "português" in msg

    def test_thread_in_pt_protects_against_noise(self):
        """A noisy/ambiguous question inside a PT thread must never be blocked."""
        blocked, lang = self._gate_result(
            "sim", thread_language="pt"
        )
        assert blocked is False and lang == "pt"

    def test_locale_pt_protects_against_any_question_language(self):
        blocked, lang = self._gate_result(
            "quel a été le chiffre d'affaires?", locale="pt"
        )
        assert blocked is False and lang == "pt"


class TestConfirmationDetection:
    """_detect_confirmation: fast-paths, LLM path, failure modes."""

    def _detect(self, message, suggestions=None, llm_response=None):
        from core.llm.orchestrator import _detect_confirmation
        sugg = suggestions or [
            "vendas por região",
            "comparativo anual",
            "top clientes",
        ]
        resp = llm_response or {"is_confirmation": False, "chosen_index": None}
        llm = make_llm(resp)
        return _detect_confirmation(message, sugg, llm)

    # Fast-path: obvious PT affirmations (should NOT call LLM)
    @pytest.mark.parametrize("msg", ["sim", "ok", "okay"])
    def test_obvious_affirmation_pt_fast_path(self, msg):
        llm = MagicMock()
        from core.llm.orchestrator import _detect_confirmation
        is_conf, idx = _detect_confirmation(msg, ["opção 1", "opção 2"], llm)
        assert is_conf is True and idx == 0
        llm.invoke.assert_not_called()

    # Fast-path: obvious EN affirmations
    @pytest.mark.parametrize("msg", ["yes"])
    def test_obvious_affirmation_en_fast_path(self, msg):
        llm = MagicMock()
        from core.llm.orchestrator import _detect_confirmation
        is_conf, idx = _detect_confirmation(msg, ["option 1", "option 2"], llm)
        assert is_conf is True and idx == 0
        llm.invoke.assert_not_called()

    def test_llm_called_for_ambiguous_pt(self):
        llm = MagicMock()
        llm.invoke.return_value = MagicMock(
            content='{"is_confirmation": true, "chosen_index": 1}'
        )
        from core.llm.orchestrator import _detect_confirmation
        is_conf, idx = _detect_confirmation(
            "manda o segundo", ["opção 1", "opção 2", "opção 3"], llm
        )
        assert is_conf is True and idx == 1
        llm.invoke.assert_called_once()

    def test_llm_called_for_en_phrase(self):
        llm = MagicMock()
        llm.invoke.return_value = MagicMock(
            content='{"is_confirmation": true, "chosen_index": 0}'
        )
        from core.llm.orchestrator import _detect_confirmation
        is_conf, idx = _detect_confirmation(
            "the first one please", ["option 1", "option 2"], llm
        )
        assert is_conf is True and idx == 0

    def test_new_question_returns_false(self):
        is_conf, idx = self._detect(
            "qual foi o crescimento em 2024?",
            llm_response={"is_confirmation": False, "chosen_index": None}
        )
        assert is_conf is False

    def test_llm_error_returns_false_not_exception(self):
        from core.llm.orchestrator import _detect_confirmation
        broken_llm = MagicMock()
        broken_llm.invoke.side_effect = RuntimeError("timeout")
        is_conf, idx = _detect_confirmation("manda o segundo", ["a", "b"], broken_llm)
        assert is_conf is False and idx == -1

    def test_llm_hallucinated_index_out_of_range(self):
        is_conf, _ = self._detect(
            "quero o décimo",
            llm_response={"is_confirmation": True, "chosen_index": 99}
        )
        assert is_conf is False

    def test_llm_returns_malformed_json(self):
        from core.llm.orchestrator import _detect_confirmation
        llm = MagicMock()
        llm.invoke.return_value = MagicMock(content="sure, that sounds great!")
        is_conf, idx = _detect_confirmation("manda o segundo", ["a", "b"], llm)
        assert is_conf is False and idx == -1

    def test_llm_returns_negative_index(self):
        is_conf, _ = self._detect(
            "manda um",
            llm_response={"is_confirmation": True, "chosen_index": -1}
        )
        assert is_conf is False


class TestDavinciLanguageConfig:
    """Davinci agent must not hardcode English."""

    def test_no_force_english_in_davinci_prompt(self):
        import inspect
        from core.agents import davinci_dashboard_agent
        source = inspect.getsource(davinci_dashboard_agent)
        # Old hardcoded string must be gone
        assert "ALWAYS respond in English" not in source
        assert "regardless of the user" not in source.lower()

    def test_no_language_en_hardcoded_in_apply_refactor(self):
        import inspect
        from core.agents import apply_davinci_refactor
        source = inspect.getsource(apply_davinci_refactor)
        assert "Force English only" not in source


class TestQueryRequestLocaleField:
    """locale field wired into the public API schema."""

    def test_locale_field_exists_and_is_optional(self):
        from api.schemas import QueryRequest
        req = QueryRequest(question="hi")
        assert req.locale is None

    def test_locale_field_accepts_pt_br(self):
        from api.schemas import QueryRequest
        req = QueryRequest(question="oi", locale="pt-BR")
        assert req.locale == "pt-BR"

    def test_locale_field_accepts_en(self):
        from api.schemas import QueryRequest
        req = QueryRequest(question="hi", locale="en")
        assert req.locale == "en"
