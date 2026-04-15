"""Tests for the brain-prompt helper and specialist wiring — Phase 4.1."""

from __future__ import annotations

import inspect

import pytest

from core.llm._brain_prompt import (
    DEFAULT_MAX_BLOCKS,
    brain_context_summary,
    iter_brain_blocks,
    prepend_brain_context,
)


# ─── prepend_brain_context ───────────────────────────────────────────────
def test_empty_state_returns_question_unchanged():
    out = prepend_brain_context("What are my OKRs?", {})
    assert out == "What are my OKRs?"


def test_empty_blocks_returns_question_unchanged():
    out = prepend_brain_context("q", {"brain_context": []})
    assert out == "q"


def test_none_blocks_returns_question_unchanged():
    out = prepend_brain_context("q", {"brain_context": None})
    assert out == "q"


def test_populated_blocks_wrap_in_tag_and_prefix():
    out = prepend_brain_context(
        "What are my OKRs?",
        {"brain_context": ["[okr] Grow ARR 20%\nOwner: CFO", "[goal] Increase ARR\nStatus: on_track"]},
    )
    assert "<contexto_recuperado>" in out
    assert "</contexto_recuperado>" in out
    assert "[okr] Grow ARR 20%" in out
    assert out.endswith("What are my OKRs?")


def test_non_string_blocks_are_skipped():
    out = prepend_brain_context(
        "q",
        {"brain_context": [None, 42, "", "   ", "[goal] real"]},
    )
    assert "[goal] real" in out
    assert "None" not in out
    assert "42" not in out


def test_cap_enforced():
    blocks = [f"[kind-{i}] body-{i}" for i in range(30)]
    out = prepend_brain_context("q", {"brain_context": blocks}, max_blocks=5)
    assert "[kind-4]" in out
    assert "[kind-5]" not in out


def test_default_cap_kicks_in():
    blocks = [f"[kind-{i}] body" for i in range(50)]
    out = prepend_brain_context("q", {"brain_context": blocks})
    # 50 blocks → trimmed to DEFAULT_MAX_BLOCKS
    assert f"[kind-{DEFAULT_MAX_BLOCKS - 1}]" in out
    assert f"[kind-{DEFAULT_MAX_BLOCKS}]" not in out


def test_question_is_preserved_verbatim():
    q = "What are my OKRs and how are they doing vs. last quarter?"
    out = prepend_brain_context(q, {"brain_context": ["[okr] x"]})
    assert out.endswith(q)


# ─── brain_context_summary ───────────────────────────────────────────────
def test_summary_empty_state():
    assert brain_context_summary({}) == "brain=empty"


def test_summary_counts_docs_and_dedupes_kinds():
    state = {
        "brain_doc_ids": ["id-1", "id-2", "id-3", "id-4"],
        "brain_doc_kinds": ["goal", "okr", "goal", "table"],
    }
    s = brain_context_summary(state)
    assert "brain=4docs" in s
    assert "goal" in s and "okr" in s and "table" in s
    # Deduped — "goal" once, not twice
    assert s.count("goal") == 1


# ─── iter_brain_blocks ───────────────────────────────────────────────────
def test_iter_returns_kept_blocks_only():
    blocks = iter_brain_blocks(
        {"brain_context": ["a", "", None, "b"]}, max_blocks=10,
    )
    assert list(blocks) == ["a", "b"]


# ─── Specialist wiring: regression check ─────────────────────────────────
# The wiring is load-bearing — if a specialist stops calling
# prepend_brain_context, the brain's retrieval silently stops informing
# that specialist's answers. These tests pin the wiring at a source
# level so the regression surfaces in CI, not production.


@pytest.mark.parametrize(
    "module_path",
    [
        "core.llm.strategy_specialist",
        "core.llm.events_specialist",
        "core.llm.relationships_specialist",
        "core.llm.people_specialist",
        "core.llm.widgets_specialist",
        "core.llm.api_specialist",
    ],
)
def test_specialist_calls_prepend_brain_context(module_path):
    import importlib

    mod = importlib.import_module(module_path)
    src = inspect.getsource(mod)
    assert "prepend_brain_context" in src, (
        f"{module_path} no longer calls prepend_brain_context — "
        "brain evidence is not reaching this specialist's prompt."
    )
