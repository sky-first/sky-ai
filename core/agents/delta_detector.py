"""Delta detection for insight-mode agent reruns — Phase 3.6.

An insight agent reruns on a schedule. Every rerun produces a result
payload, and we have to decide one of three things:

    none      — identical to last run; suppress the notification.
    trivial   — changed but not worth pinging (e.g. row count went
                from 1200 → 1201).
    material  — user actually cares; emit INSIGHT_AGENT_MATERIAL and
                attach a 1-sentence narrative summary.

Two strategies ship together so the caller can pick per-agent:

  * ``HashDeltaStrategy`` — cheap. Normalises the payload, sha256s
    it, compares to the previous hash. Returns ``none`` on match,
    ``first_run`` on first-ever run, ``material`` otherwise. No LLM
    call, no cost. Good default.

  * ``LLMDeltaStrategy`` — slower / costlier, much smarter. When the
    hash differs, ask a small LLM to classify the delta as material
    vs trivial and, if material, produce a 1-sentence summary the
    notification can surface. The LLM never sees PII — pass sanitised
    rows only (see ``core.security.pii_response_filter``).

Both strategies return the same ``DeltaResult`` so the caller is
substrate-agnostic. The backend's `agent_executions.delta_kind /
delta_summary / delta_tokens / delta_cost_usd` columns map 1:1 to
the fields here.

This module is deliberately pure — no DB, no network, no settings
lookups. The LLM provider and the previous-run snapshot are passed
in. That's what makes it testable without a full stack.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Protocol, Sequence

logger = logging.getLogger(__name__)


# ───────────────────────────── types ──────────────────────────────────────
DeltaKind = str  # 'first_run' | 'none' | 'trivial' | 'material'


@dataclass
class DeltaResult:
    kind: DeltaKind
    result_hash: str
    summary: Optional[str] = None
    tokens_used: int = 0
    cost_usd: float = 0.0
    # When LLM classification fails we fall through to material + a
    # generic summary so the user isn't silently dropped; `fallback`
    # tells the caller why so observability isn't lying to it.
    fallback_reason: Optional[str] = None


class LLMCall(Protocol):
    """Minimal protocol the LLM strategy needs. Mirrors the existing
    LangChain-style ``llm.ainvoke([{role, content}, ...])`` shape but
    we depend only on a callable so tests can pass a fake."""

    async def __call__(
        self, messages: list[dict[str, str]]
    ) -> "LLMResponse": ...


@dataclass
class LLMResponse:
    content: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


# ─────────────────────── result-hash normalisation ────────────────────────
def compute_result_hash(payload: Any) -> str:
    """Canonical sha256 hash of a result payload.

    Sorting keys + separators + ensure_ascii make the hash stable
    across platforms / Python versions. Strings are normalised with
    single spaces so cosmetic whitespace doesn't churn the hash.
    """
    normalised = _normalise(payload)
    blob = json.dumps(normalised, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


_WS_RE = re.compile(r"\s+")


def _normalise(v: Any) -> Any:
    if v is None or isinstance(v, (int, float, bool)):
        return v
    if isinstance(v, str):
        return _WS_RE.sub(" ", v.strip())
    if isinstance(v, list):
        return [_normalise(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _normalise(val) for k, val in v.items()}
    return str(v)


# ───────────────────────────── strategies ─────────────────────────────────
@dataclass
class HashDeltaStrategy:
    """Trivial hash-only strategy. Every change is ``material`` —
    users who want finer-grained classification use the LLM strategy."""

    async def classify(
        self,
        *,
        current_payload: Any,
        previous_hash: Optional[str],
    ) -> DeltaResult:
        current_hash = compute_result_hash(current_payload)
        if previous_hash is None:
            return DeltaResult(kind="first_run", result_hash=current_hash)
        if current_hash == previous_hash:
            return DeltaResult(kind="none", result_hash=current_hash)
        return DeltaResult(kind="material", result_hash=current_hash)


SYSTEM_PROMPT_DELTA = (
    "You are a careful analyst that classifies *changes* between two runs "
    "of the same data question. You receive JSON for PREV and CURR. Decide:\n"
    "  - 'none'     — essentially identical (ignore rounding / row order).\n"
    "  - 'trivial'  — changed but not worth pinging a user about.\n"
    "  - 'material' — a decision-maker should look at this.\n"
    "Then write ONE sentence (max 180 chars, plain text, no markdown) "
    "summarising the change. For 'none' and 'trivial' the sentence is "
    "informational; for 'material' it must name the metric and the direction.\n"
    "Return STRICT JSON: {\"kind\": string, \"summary\": string}."
)


@dataclass
class LLMDeltaStrategy:
    """LLM classification fallback. Uses a cheap model (phi3 / haiku)
    and strict-JSON output. Failures degrade to ``material`` rather
    than ``none`` — it's worse to suppress a change than to page too
    eagerly when the classifier hiccups.

    Pass ``llm`` at construct time. The strategy is stateless
    otherwise.
    """

    llm: LLMCall
    # Cap the payload size sent to the LLM — bigger than this we switch
    # to summary-of-summaries; see `_compact`. Keeps tokens predictable.
    max_chars_per_side: int = 4000

    async def classify(
        self,
        *,
        current_payload: Any,
        previous_hash: Optional[str],
        previous_payload: Any = None,
    ) -> DeltaResult:
        current_hash = compute_result_hash(current_payload)
        if previous_hash is None:
            return DeltaResult(kind="first_run", result_hash=current_hash)
        if current_hash == previous_hash:
            return DeltaResult(kind="none", result_hash=current_hash)

        # Hash differs — ask the LLM to classify.
        prev_blob = _compact(previous_payload, self.max_chars_per_side)
        curr_blob = _compact(current_payload, self.max_chars_per_side)
        user_msg = (
            f"PREV:\n{prev_blob}\n\nCURR:\n{curr_blob}\n\n"
            "Return {\"kind\": \"none|trivial|material\", \"summary\": \"...\"}."
        )

        try:
            resp = await self.llm(
                [
                    {"role": "system", "content": SYSTEM_PROMPT_DELTA},
                    {"role": "user", "content": user_msg},
                ]
            )
        except Exception as exc:
            logger.exception("LLM delta classification failed — degrading to material")
            return DeltaResult(
                kind="material",
                result_hash=current_hash,
                summary="Unable to summarise — payload changed.",
                fallback_reason=f"llm_error:{type(exc).__name__}",
            )

        parsed = _parse_delta_json(resp.content)
        if parsed is None:
            return DeltaResult(
                kind="material",
                result_hash=current_hash,
                summary="Payload changed (unparseable classification).",
                tokens_used=resp.tokens_in + resp.tokens_out,
                cost_usd=resp.cost_usd,
                fallback_reason="unparseable_json",
            )

        kind, summary = parsed
        return DeltaResult(
            kind=kind,
            result_hash=current_hash,
            summary=summary,
            tokens_used=resp.tokens_in + resp.tokens_out,
            cost_usd=resp.cost_usd,
        )


# ───────────────────────────── helpers ────────────────────────────────────
def _compact(payload: Any, max_chars: int) -> str:
    """Bound the size of the payload shown to the LLM.

    If the full JSON fits within the budget, return it verbatim. If
    not, return a truncated view that preserves head + tail so the
    classifier still sees top + bottom rows — the extremes carry most
    of the signal for "did something move?".
    """
    blob = json.dumps(_normalise(payload), sort_keys=True, separators=(",", ":"))
    if len(blob) <= max_chars:
        return blob
    half = max_chars // 2
    return f"{blob[:half]} …[truncated {len(blob) - max_chars} chars]… {blob[-half:]}"


def _parse_delta_json(content: str) -> Optional[tuple[DeltaKind, str]]:
    """Best-effort JSON parse with the usual LLM quirks (markdown
    fences, leading prose).
    """
    if not content:
        return None

    # Strip markdown code fences.
    txt = content.strip()
    if txt.startswith("```"):
        # Drop the first fence line and any trailing fence.
        lines = txt.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        txt = "\n".join(lines).strip()

    # Find the JSON object (first '{' to last '}') — tolerant of
    # preamble like "Here is the classification:".
    start = txt.find("{")
    end = txt.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        obj = json.loads(txt[start : end + 1])
    except json.JSONDecodeError:
        return None

    kind_raw = str(obj.get("kind") or "").strip().lower()
    if kind_raw not in {"none", "trivial", "material"}:
        return None
    summary = str(obj.get("summary") or "").strip() or None
    # Clamp summary length so an overzealous LLM can't blow up the
    # notification description field.
    if summary and len(summary) > 200:
        summary = summary[:197].rstrip() + "…"
    return kind_raw, summary or ""
