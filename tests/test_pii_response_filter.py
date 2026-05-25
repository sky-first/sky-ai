"""Tests for cell-level PII redaction — Phase 3.6."""

from __future__ import annotations

from datetime import datetime, timezone

from core.rag.context_brain import CandidateDoc, RankedDoc
from core.security.pii_response_filter import (
    REDACTED_VALUE,
    collect_pii_columns,
    mask_response_payload,
    mask_rows,
)


# ─── mask_rows ───────────────────────────────────────────────────────────
def test_mask_rows_redacts_listed_columns():
    rows = [
        {"id": 1, "email": "alice@x.com", "revenue": 100},
        {"id": 2, "email": "bob@x.com", "revenue": 200},
    ]
    out = mask_rows(rows, ["email"])
    assert out[0]["email"] == REDACTED_VALUE
    assert out[1]["email"] == REDACTED_VALUE
    # Non-PII columns untouched
    assert out[0]["revenue"] == 100
    assert out[1]["id"] == 2


def test_mask_rows_is_case_insensitive():
    rows = [{"Email": "a@b.com", "Phone": "555"}]
    out = mask_rows(rows, ["email", "phone"])
    assert out[0]["Email"] == REDACTED_VALUE
    assert out[0]["Phone"] == REDACTED_VALUE


def test_mask_rows_returns_copy_not_mutation():
    rows = [{"ssn": "123-45-6789"}]
    _ = mask_rows(rows, ["ssn"])
    # Original must not be mutated (defensive — caller may hold a
    # reference for audit logging).
    assert rows[0]["ssn"] == "123-45-6789"


def test_mask_rows_noop_when_empty_pii_set():
    rows = [{"email": "a@b.com"}]
    out = mask_rows(rows, [])
    assert out == rows


def test_mask_rows_noop_when_empty_rows():
    assert mask_rows([], ["email"]) == []


def test_mask_rows_passes_through_non_dict_rows():
    rows = ["scalar-row", 42, {"ok": 1, "email": "a@b.com"}]
    out = mask_rows(rows, ["email"])
    # Non-dicts unchanged; dict still redacted.
    assert out[0] == "scalar-row"
    assert out[1] == 42
    assert out[2]["email"] == REDACTED_VALUE


def test_mask_rows_drops_empty_or_none_column_names():
    rows = [{"email": "a@b.com"}]
    # Mixed garbage input — real-world brain sometimes emits junk.
    out = mask_rows(rows, ["", None, "email"])  # type: ignore[list-item]
    assert out[0]["email"] == REDACTED_VALUE


# ─── collect_pii_columns ─────────────────────────────────────────────────
def _doc(pii_flags: list[str]) -> CandidateDoc:
    return CandidateDoc(
        id="1",
        kind="column",
        source_table="column_metadata",
        source_id="1",
        title="x",
        body="y",
        metadata={},
        space_id=None,
        crew_id=None,
        owner_user_id=None,
        visibility="space",
        pii_flags=pii_flags,
        updated_at=datetime.now(timezone.utc),
        cosine=0,
        bm25=0,
    )


def test_collect_from_ranked_docs():
    ranked = [
        RankedDoc(doc=_doc(["email"]), score=1, components={}),
        RankedDoc(doc=_doc(["phone", "ssn"]), score=1, components={}),
    ]
    assert collect_pii_columns(ranked) == {"email", "phone", "ssn"}


def test_collect_from_raw_candidate_docs():
    docs = [_doc(["email"]), _doc(["email", "ssn"])]
    assert collect_pii_columns(docs) == {"email", "ssn"}


def test_collect_tolerates_empty_and_missing_flags():
    docs = [_doc([]), _doc(["email"])]
    assert collect_pii_columns(docs) == {"email"}


def test_collect_filters_non_string_entries():
    # pii_flags coming back weird shouldn't crash the sanitiser.
    class Weird:
        pii_flags = ["email", None, 42, ""]

    assert collect_pii_columns([Weird()]) == {"email"}


# ─── mask_response_payload ──────────────────────────────────────────────
def test_mask_response_payload_redacts_rows_only():
    payload = {
        "answer": "The customer with email alice@x.com bought 3 items.",
        "sql": "SELECT email FROM customers",
        "rows": [{"email": "alice@x.com", "orders": 3}],
    }
    out = mask_response_payload(payload, ["email"])
    assert out["rows"][0]["email"] == REDACTED_VALUE
    assert out["rows"][0]["orders"] == 3
    # Answer + SQL are LLM-generated surrounding text; the column
    # name in SQL is fine, and the answer is the LLM's responsibility
    # via upstream filters (prompt-injection detector). This filter
    # focuses on the cell values that actually contain PII.
    assert out["answer"] == payload["answer"]
    assert out["sql"] == payload["sql"]


def test_mask_response_payload_noop_when_no_rows_key():
    payload = {"answer": "…", "sql": "…"}
    assert mask_response_payload(payload, ["email"]) == payload


def test_mask_response_payload_noop_on_non_dict():
    assert mask_response_payload(None, ["email"]) is None  # type: ignore[arg-type]
    assert mask_response_payload("x", ["email"]) == "x"  # type: ignore[arg-type]
