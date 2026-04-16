"""Full-context scan agent — Phase 5.1.

The most ambitious mode in the master plan. When a user (usually an
admin or leadership role) runs ``monitor_type='context'`` it
effectively says: *"read the whole brain, not just the kinds I hint
at, and tell me what I should know"*.

Mechanics:

  1. Pull a wide retrieval blend (k=200 by default) across every
     context kind in scope — strategy, events, relationships,
     platform, connections, outputs. Same `retrieve_context` call
     every other surface uses; just no ``kinds`` filter and a much
     bigger ``k``.

  2. Hand the LLM the blend with a system prompt that asks for:
        - a 3-6 bullet narrative summary of what matters
        - a list of suggested follow-up questions the user could ask
        - a list of the doc ids the narrative actually cited
     Strict JSON so downstream UI renders reliably.

  3. Return a `FullContextResult` the worker / endpoint can convert
     into the standard run response shape (`result_payload` +
     `delta_summary` + `context_doc_ids` + `context_intent='context'`).

No DB or HTTP here. The function takes ``retrieve`` and ``llm`` as
callables so tests can exercise every branch without a stack. The
worker composes it with the real brain + provider.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable, Optional, Sequence

logger = logging.getLogger(__name__)


DEFAULT_K = 200


@dataclass
class FullContextResult:
    narrative: list[str]              # 3–6 bullet lines
    follow_ups: list[str]             # 3–6 suggested questions
    cited_doc_ids: list[str]          # doc ids the LLM explicitly cited
    retrieved_doc_ids: list[str]      # full retrieval trail (audit)
    retrieved_kinds: list[str]        # unique kinds actually seen
    tokens_used: int = 0
    cost_usd: float = 0.0
    fallback_reason: Optional[str] = None

    def to_result_payload(self) -> dict[str, Any]:
        """Shape the worker / endpoint will persist as
        `agent_executions.result_payload`."""
        return {
            "mode": "context",
            "narrative": self.narrative,
            "follow_ups": self.follow_ups,
            "cited_doc_ids": self.cited_doc_ids,
            "retrieved_kinds": self.retrieved_kinds,
            "retrieved_doc_count": len(self.retrieved_doc_ids),
        }


# ─── LLM protocol (same shape as delta_detector) ────────────────────────
@dataclass
class LLMResponse:
    content: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


# Callable types so tests can pass plain closures.
Retriever = Callable[..., Awaitable[list[Any]]]
LLMCall = Callable[[list[dict[str, str]]], Awaitable[LLMResponse]]


SYSTEM_PROMPT = (
    "You are a senior analyst reading an organisation's entire context "
    "graph (strategy, goals, OKRs, KPIs, risks, events, relationships, "
    "platform fabric, data sources, recent widgets / conversations). "
    "Your job is to tell leadership what they should know.\n\n"
    "Output STRICT JSON matching this schema — nothing else, no prose "
    "wrapper, no markdown fences:\n"
    "{\n"
    '  "narrative":   [string, ...],   // 3 to 6 bullets; each one sentence.\n'
    '  "follow_ups":  [string, ...],   // 3 to 6 questions the user should ask next.\n'
    '  "cited_doc_ids": [string, ...]  // doc ids you quoted; use the form shown next to each block\n'
    "}\n\n"
    "Rules:\n"
    " - Narrative bullets name the metric / goal / event explicitly.\n"
    " - Follow-ups are specific questions a decision-maker would ask, "
    "not meta-questions ('what data do we have').\n"
    " - Cite conservatively — only the doc ids you actually used.\n"
    " - If the retrieved context is empty, return empty arrays and a "
    "single narrative bullet: \"No context available for this scope yet.\""
)


# ──────────────────────────── pure pipeline ──────────────────────────────
async def run_full_context_scan(
    *,
    question: str,
    retrieve: Retriever,
    llm: LLMCall,
    k: int = DEFAULT_K,
    retrieve_kwargs: Optional[dict[str, Any]] = None,
    max_chars_for_llm: int = 24_000,
) -> FullContextResult:
    """Execute one full-context scan.

    ``retrieve`` is called with ``(question, kinds=None, k=k, **retrieve_kwargs)``
    and expected to return an iterable of RankedDoc-like objects. Each
    must expose ``.doc.id``, ``.doc.kind``, ``.doc.title``, ``.doc.body``
    — i.e. the shape Phase 2.5 already produces.

    ``llm`` is the async callable returning an ``LLMResponse``.

    Failures degrade gracefully:
      * retriever exception → narrative = apology + retrieval_error
      * LLM exception → narrative = apology + llm_error
      * unparseable JSON → narrative = apology + unparseable_json

    Every degraded path still returns a valid `FullContextResult` so
    the caller writes a sensible row to agent_executions rather than
    crashing the worker.
    """
    retrieve_kwargs = dict(retrieve_kwargs or {})
    retrieve_kwargs.setdefault("kinds", None)
    retrieve_kwargs.setdefault("k", k)

    try:
        ranked = await retrieve(question, **retrieve_kwargs)
    except Exception as exc:
        logger.exception("full_context retrieve failed")
        return FullContextResult(
            narrative=[
                "Could not scan the context graph right now — the "
                "retrieval layer raised an error."
            ],
            follow_ups=[],
            cited_doc_ids=[],
            retrieved_doc_ids=[],
            retrieved_kinds=[],
            fallback_reason=f"retrieval_error:{type(exc).__name__}",
        )

    ranked = list(ranked or [])
    retrieved_doc_ids = [_doc_id(r) for r in ranked]
    retrieved_kinds = sorted({_doc_kind(r) for r in ranked if _doc_kind(r)})

    if not ranked:
        return FullContextResult(
            narrative=["No context available for this scope yet."],
            follow_ups=[],
            cited_doc_ids=[],
            retrieved_doc_ids=[],
            retrieved_kinds=[],
        )

    user_prompt = _build_user_prompt(question, ranked, max_chars_for_llm)

    try:
        resp = await llm(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
        )
    except Exception as exc:
        logger.exception("full_context LLM call failed")
        return FullContextResult(
            narrative=[
                "Retrieved the context but could not synthesise a "
                "summary — the LLM provider failed."
            ],
            follow_ups=[],
            cited_doc_ids=[],
            retrieved_doc_ids=retrieved_doc_ids,
            retrieved_kinds=retrieved_kinds,
            fallback_reason=f"llm_error:{type(exc).__name__}",
        )

    parsed = _parse_scan_json(resp.content)
    if parsed is None:
        return FullContextResult(
            narrative=[
                "Retrieved the context but the synthesis step returned "
                "an unparseable response."
            ],
            follow_ups=[],
            cited_doc_ids=[],
            retrieved_doc_ids=retrieved_doc_ids,
            retrieved_kinds=retrieved_kinds,
            tokens_used=resp.tokens_in + resp.tokens_out,
            cost_usd=resp.cost_usd,
            fallback_reason="unparseable_json",
        )

    narrative, follow_ups, cited = parsed

    # Restrict cited ids to the ones we actually retrieved. Prevents
    # the LLM from inventing doc ids and lets the UI's "show evidence"
    # feature trust the list.
    valid = set(retrieved_doc_ids)
    cited = [c for c in cited if c in valid]

    return FullContextResult(
        narrative=narrative,
        follow_ups=follow_ups,
        cited_doc_ids=cited,
        retrieved_doc_ids=retrieved_doc_ids,
        retrieved_kinds=retrieved_kinds,
        tokens_used=resp.tokens_in + resp.tokens_out,
        cost_usd=resp.cost_usd,
    )


# ───────────────────────────── helpers ────────────────────────────────────
def _doc_id(ranked_item: Any) -> str:
    doc = getattr(ranked_item, "doc", None) or ranked_item
    return str(getattr(doc, "id", "") or "")


def _doc_kind(ranked_item: Any) -> str:
    doc = getattr(ranked_item, "doc", None) or ranked_item
    return str(getattr(doc, "kind", "") or "")


def _doc_title(ranked_item: Any) -> str:
    doc = getattr(ranked_item, "doc", None) or ranked_item
    return str(getattr(doc, "title", "") or "")


def _doc_body(ranked_item: Any) -> str:
    doc = getattr(ranked_item, "doc", None) or ranked_item
    return str(getattr(doc, "body", "") or "")


def _build_user_prompt(question: str, ranked: list[Any], max_chars: int) -> str:
    """Assemble a single user-message body with every retrieved block,
    each tagged with its id + kind so the LLM can cite by id.

    Hard-budget the total char count: when the blend exceeds
    ``max_chars`` we keep the first N blocks and truncate the rest.
    Ordering preserves retrieval rank so the highest-signal docs win.
    """
    header = (
        f"Question / scope trigger: {question.strip() or '(full-context scan)'}\n\n"
        "Below are the retrieved brain documents, in relevance order. "
        "Each is preceded by its id and kind in square brackets — use "
        "those ids when filling `cited_doc_ids`.\n\n"
    )
    out = [header]
    total = len(header)
    kept = 0
    for r in ranked:
        block = (
            f"[id={_doc_id(r)}][kind={_doc_kind(r)}] {_doc_title(r)}\n"
            f"{_doc_body(r)}\n\n"
        )
        if total + len(block) > max_chars:
            remaining = len(ranked) - kept
            out.append(
                f"… {remaining} more document(s) truncated to fit the LLM "
                "budget. The narrative should acknowledge that the scan "
                "saw more than it summarised."
            )
            break
        out.append(block)
        total += len(block)
        kept += 1
    return "".join(out)


def _parse_scan_json(content: str) -> Optional[tuple[list[str], list[str], list[str]]]:
    if not content:
        return None
    txt = content.strip()
    # Strip markdown fences when the LLM ignored the "no fences" rule.
    if txt.startswith("```"):
        lines = txt.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        txt = "\n".join(lines).strip()
    start = txt.find("{")
    end = txt.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        obj = json.loads(txt[start : end + 1])
    except json.JSONDecodeError:
        return None

    narrative = _coerce_str_list(obj.get("narrative"))
    follow_ups = _coerce_str_list(obj.get("follow_ups"))
    cited = _coerce_str_list(obj.get("cited_doc_ids"))

    if not narrative:
        return None  # treat missing narrative as unparseable

    # Clamp sizes so an overzealous model can't balloon the payload.
    narrative = narrative[:10]
    follow_ups = follow_ups[:10]
    cited = cited[:50]
    return narrative, follow_ups, cited


def _coerce_str_list(v: Any) -> list[str]:
    if not isinstance(v, list):
        return []
    out: list[str] = []
    for x in v:
        if isinstance(x, str):
            s = x.strip()
            if s:
                out.append(s[:400])
    return out
