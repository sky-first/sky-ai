"""Cell-level PII redaction for agent / chat responses — Phase 3.6.

The Context Layer already records which columns are PII (the
``column`` render template sets ``pii_flags=[column_name]`` when
``row['is_pii']`` is true — see ``core/rag/render/__init__.py``).
Retrieval surfaces the same flags on every ``CandidateDoc``.

Before handing a payload back to the caller we MUST redact the
cell values of flagged columns. We keep the column NAME — the
LLM still needs to know the shape of the data, just not the
values.

Two entry points:

  * ``mask_rows(rows, pii_columns)`` — given a list-of-dict result
    plus a set of column names to redact, returns a new list with
    those values replaced by ``"<redacted>"``.

  * ``collect_pii_columns(ranked)`` — walks the brain's
    ``RankedDoc`` list and pulls out every ``pii_flags`` value.
    This is what the caller passes to ``mask_rows`` before shipping
    the answer.

Redaction is deliberately conservative: when in doubt, mask. The
alternative (leaking a cell we shouldn't have) is the kind of
mistake that ends up in a regulator letter.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

logger = logging.getLogger(__name__)


REDACTED_VALUE = "<redacted>"


def mask_rows(
    rows: list[dict[str, Any]],
    pii_columns: Iterable[str],
) -> list[dict[str, Any]]:
    """Return a new list of rows with PII-column values replaced.

    Case-insensitive match on column name because upstream sources
    (BigQuery, Postgres, Mongo) capitalise inconsistently and we'd
    rather over-match than miss.
    """
    cols_lower = {c.lower() for c in pii_columns if isinstance(c, str) and c}
    if not cols_lower or not rows:
        return list(rows)

    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            # Defensive: don't try to redact non-dict rows; pass through
            # untouched rather than drop or crash.
            out.append(r)
            continue
        masked = dict(r)
        for k in list(masked.keys()):
            if isinstance(k, str) and k.lower() in cols_lower:
                masked[k] = REDACTED_VALUE
        out.append(masked)
    return out


def collect_pii_columns(ranked_docs: Iterable[Any]) -> set[str]:
    """Flatten ``pii_flags`` from every brain doc into one set of
    column names.

    Accepts anything that iterates as a ``RankedDoc``-like object
    with ``.doc.pii_flags`` or raw ``CandidateDoc`` with
    ``.pii_flags`` — lets supervisor code reuse this regardless of
    which layer it's consuming.
    """
    cols: set[str] = set()
    for item in ranked_docs:
        flags = _extract_flags(item)
        for f in flags:
            if isinstance(f, str) and f:
                cols.add(f)
    return cols


def _extract_flags(item: Any) -> list[str]:
    # RankedDoc (has `.doc.pii_flags`)
    doc = getattr(item, "doc", None)
    if doc is not None and hasattr(doc, "pii_flags"):
        return list(getattr(doc, "pii_flags") or [])
    # CandidateDoc (has `.pii_flags` directly)
    if hasattr(item, "pii_flags"):
        return list(getattr(item, "pii_flags") or [])
    # Dict-shaped (defensive)
    if isinstance(item, dict):
        flags = item.get("pii_flags") or []
        if isinstance(flags, list):
            return list(flags)
    return []


def mask_response_payload(
    payload: dict[str, Any],
    pii_columns: Iterable[str],
) -> dict[str, Any]:
    """Redact the ``rows`` array inside a standard response shape.

    The rest of the payload is passed through unchanged. This is the
    function to call right before returning from a chat / agent-run
    endpoint — we keep the answer, the schema, the SQL, and the
    metadata; we only censor the cell values that the Context Layer
    told us were sensitive.
    """
    if not isinstance(payload, dict):
        return payload
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return payload
    return {**payload, "rows": mask_rows(rows, pii_columns)}
