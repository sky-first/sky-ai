"""Knowledge Specialist Node — replaces strategy_specialist post-refactor.

Strategy entities (Pillars/OKRs/Initiatives) were removed in the
Knowledge refactor (Phases 1a/1b). The Knowledge layer that replaced
them lives in three pieces:

  • Metrics    (with optional formula_text + scope + certified flag)
  • Glossary   (terms + definitions + aliases)
  • Relationships (cross-source joins, AI-inferred + confidence)

This specialist answers any question that previously routed to the
old strategy_specialist (OKRs, goals, KPIs) AND the new questions the
refactor created (define X, what's the formula for Y, how is A
related to B). It does NOT generate SQL — it composes a natural-
language answer from the curated catalog.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from core.logging_utils import log_event
from core.llm.lingua_da_resposta import lingua_de_quem_fala, nome_da_lingua

logger = logging.getLogger("dataassistant")


KNOWLEDGE_SYSTEM_PROMPT = """You are an enterprise knowledge analyst.

You have access to the company's curated Knowledge layer below. Treat
it as the authoritative source.

## How to structure your answer
Split your answer into two clearly labelled sections, in this order:

**From your catalog** — quote what's in the catalog VERBATIM. Do not
expand, paraphrase, or invent details. If the catalog only has a
short definition, only that short definition appears here. If
nothing matches, write "(no matching entry)" and skip this section.

**Background** — only include this when general context would help
the reader. Keep it brief, factual, generic. Never claim it came
from the catalog. If the catalog already answers the question fully,
omit this section entirely.

Use Markdown headings exactly: `## From your catalog` and `## Background`.

When the question asks about a metric, surface its name, definition,
formula, and unit (only fields the catalog actually has). When it
asks about a term, surface the term + its catalog definition. When
it asks how things connect, surface the relationship (sources →
target, type, confidence if any).

Answer ONLY in {lingua}. This is not a preference — the reader may not read English.

## Knowledge catalog
{knowledge_block}
"""


def _format_metric(m: Dict[str, Any]) -> str:
    name = m.get("name", "Unnamed")
    scope = (m.get("scope") or "").upper()
    certified = bool(m.get("certified_by_user_id"))
    tag = (
        "[ORG-CERTIFIED]"
        if certified and scope == "ORG"
        else f"[{scope}]" if scope else ""
    )
    desc = m.get("formula_description") or m.get("description") or ""
    formula = m.get("formula_text")
    unit = m.get("unit")
    bits = [f"- **{name}** {tag}".rstrip()]
    if desc:
        bits.append(f"  · {desc}")
    if formula:
        formula_short = formula if len(formula) <= 160 else formula[:157] + "..."
        bits.append(f"  · formula: `{formula_short}`")
    if unit:
        bits.append(f"  · unit: {unit}")
    return "\n".join(bits)


def _format_term(g: Dict[str, Any]) -> str:
    term = g.get("term", "")
    definition = g.get("definition", "")
    aliases = g.get("aliases") or []
    cert = bool(g.get("certified_by_user_id"))
    tag = "[ORG-CERTIFIED]" if cert else ""
    line = f"- **{term}** {tag} — {definition}".rstrip()
    if aliases:
        line += f" (also known as: {', '.join(str(a) for a in aliases[:3])})"
    return line


def _format_relationship(r: Dict[str, Any]) -> str:
    name = r.get("name", "")
    sources = r.get("sources") or []
    src = ", ".join(str(s.get("name") or s.get("id", "?")) for s in sources[:3]) or "?"
    targets = r.get("targets") or []
    if targets:
        tgt = ", ".join(str(t.get("id", "?")) for t in targets[:3])
    else:
        tgt = r.get("target_id", "?")
    rel_type = r.get("relationship_type") or r.get("type") or ""
    line = f"- **{name}**: {src} → {tgt}"
    tag_bits: List[str] = []
    if rel_type:
        tag_bits.append(rel_type)
    if r.get("ai_inferred"):
        conf = r.get("confidence")
        if isinstance(conf, (int, float)):
            conf_pct = int(conf * 100) if conf <= 1 else int(conf)
            tag_bits.append(f"AI-inferred {conf_pct}%")
        else:
            tag_bits.append("AI-inferred")
    if tag_bits:
        line += f" [{' · '.join(tag_bits)}]"
    return line


def _build_knowledge_block(
    metrics: List[Dict[str, Any]],
    glossary: List[Dict[str, Any]],
    relationships: List[Dict[str, Any]],
) -> str:
    parts: List[str] = []
    if metrics:
        parts.append(f"### Metrics ({len(metrics)})")
        parts.extend(_format_metric(m) for m in metrics[:50])
    if glossary:
        parts.append(f"\n### Glossary ({len(glossary)})")
        parts.extend(_format_term(g) for g in glossary[:50])
    if relationships:
        parts.append(f"\n### Relationships ({len(relationships)})")
        parts.extend(_format_relationship(r) for r in relationships[:30])
    if not parts:
        return "(No metrics, glossary terms or relationships have been created yet.)"
    return "\n".join(parts)


_EVIDENCE_SNIPPET_MAX = 240


def _build_evidence_chunks(
    metrics: List[Dict[str, Any]],
    glossary: List[Dict[str, Any]],
    relationships: List[Dict[str, Any]],
    question: str,
) -> List[Dict[str, Any]]:
    """Pick the catalog rows the LLM is likely to cite (Sources tab).

    Cheap relevance filter: any row whose name/term appears in the
    question (case-insensitive) is forced in; everything else is
    capped so the Sources tab doesn't drown in unrelated rows. Each
    chunk gets a deep-link href so the user can click through and
    edit/inspect the catalog row.
    """
    q = (question or "").lower()
    chunks: List[Dict[str, Any]] = []

    def _trunc(text: str) -> str:
        text = text or ""
        return (
            text
            if len(text) <= _EVIDENCE_SNIPPET_MAX
            else text[: _EVIDENCE_SNIPPET_MAX - 1] + "…"
        )

    metric_hits = [m for m in metrics if (m.get("name") or "").lower() in q]
    if not metric_hits:
        metric_hits = metrics[:3]
    for m in metric_hits[:5]:
        snippet = _trunc(m.get("formula_description") or m.get("description") or "")
        chunks.append(
            {
                "id": str(m.get("id", "")),
                "kind": "metric",
                "source_label": m.get("name") or "Metric",
                "snippet": snippet,
                "href": f"/dashboard/universe-intelligence#metric/{m.get('id', '')}",
            }
        )

    term_hits = [g for g in glossary if (g.get("term") or "").lower() in q]
    if not term_hits:
        term_hits = glossary[:3]
    for g in term_hits[:5]:
        chunks.append(
            {
                "id": str(g.get("id", "")),
                "kind": "glossary",
                "source_label": g.get("term") or "Term",
                "snippet": _trunc(g.get("definition") or ""),
                "href": f"/dashboard/universe-intelligence#glossary/{g.get('id', '')}",
            }
        )

    for r in relationships[:3]:
        srcs = r.get("sources") or []
        src_label = (
            ", ".join(str(s.get("name") or s.get("id", "?")) for s in srcs[:2]) or "?"
        )
        tgts = r.get("targets") or []
        tgt_label = (
            ", ".join(str(t.get("id", "?")) for t in tgts[:2])
            if tgts
            else (r.get("target_id") or "?")
        )
        chunks.append(
            {
                "id": str(r.get("id", "")),
                "kind": "relationship",
                "source_label": r.get("name") or "Relationship",
                "snippet": _trunc(
                    f"{src_label} → {tgt_label} · {r.get('description') or ''}"
                ),
                "href": f"/dashboard/universe-intelligence#relationship/{r.get('id', '')}",
            }
        )

    return chunks


def run_knowledge_specialist(
    state: Dict[str, Any],
    llm: Any,
    backend_client: Any,
) -> Dict[str, Any]:
    """LangGraph node — answers Knowledge questions (metrics / glossary / relationships)."""
    question = state.get("question", "")

    log_event("knowledge_specialist_start", {"question": question[:100]})

    # ── Reasoning trace (rich + generic; no model name / latency) ──
    # Each user-facing string here lands in the transparency panel.
    # Keep them human-readable and free of stack/infra details — the
    # user explicitly asked us not to expose how the answer is made.
    steps: List[Dict[str, Any]] = [
        {
            "kind": "router",
            "summary": "Recognised this as a question about your knowledge catalog.",
        },
    ]

    metrics = (
        backend_client.get_metrics() if hasattr(backend_client, "get_metrics") else []
    )
    glossary = (
        backend_client.get_glossary() if hasattr(backend_client, "get_glossary") else []
    )
    relationships = (
        backend_client.get_enterprise_relationships()
        if hasattr(backend_client, "get_enterprise_relationships")
        else []
    )

    catalog_summary = (
        f"Loaded {len(metrics)} metric"
        + ("s" if len(metrics) != 1 else "")
        + f", {len(glossary)} glossary term"
        + ("s" if len(glossary) != 1 else "")
        + f", {len(relationships)} relationship"
        + ("s" if len(relationships) != 1 else "")
        + " from your catalog."
    )
    steps.append({"kind": "retrieval", "summary": catalog_summary})

    if not metrics and not glossary and not relationships:
        log_event("knowledge_specialist_empty_catalog", {})
        state["answer"] = (
            "Your Knowledge layer is empty — there are no metrics, glossary terms or "
            "relationships defined yet. Open the Knowledge panel on the left toolbar to "
            "create your first metric or term, or define a relationship between data "
            "sources, and I'll be able to answer with curated definitions."
        )
        state["data"] = []
        state["sql"] = None
        state["chosen_tables"] = []
        state["chosen_tables_physical"] = []
        state["evidence"] = []
        state["reasoning_steps"] = steps
        return state

    knowledge_block = _build_knowledge_block(metrics, glossary, relationships)
    system_prompt = KNOWLEDGE_SYSTEM_PROMPT.format(
        knowledge_block=knowledge_block,
        lingua=nome_da_lingua(lingua_de_quem_fala(state, question)),
    )

    evidence = _build_evidence_chunks(metrics, glossary, relationships, question)
    if evidence:
        steps.append(
            {
                "kind": "retrieval",
                "summary": (
                    f"Selected {len(evidence)} entr"
                    + ("y" if len(evidence) == 1 else "ies")
                    + " most likely to answer your question."
                ),
            }
        )

    # Phase 4.1: layer brain context (RAG evidence) on top of the Knowledge
    # block. No-op when empty.
    from core.llm._brain_prompt import prepend_brain_context

    user_content = prepend_brain_context(question, state)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    try:
        response = llm.invoke(messages)
        answer = response.content if hasattr(response, "content") else str(response)
        steps.append(
            {"kind": "format", "summary": "Composed the answer from the catalog."}
        )
    except Exception as e:
        logger.error(f"Knowledge specialist LLM error: {e}")
        answer = f"I found Knowledge data but ran into an error analyzing it: {e}"
        steps.append(
            {
                "kind": "format",
                "summary": "Tried to compose the answer but hit an error.",
            }
        )

    log_event(
        "knowledge_specialist_done",
        {
            "question": question[:100],
            "answer_preview": (answer or "")[:200],
            "num_metrics": len(metrics),
            "num_glossary": len(glossary),
            "num_relationships": len(relationships),
            "num_evidence": len(evidence),
        },
    )

    state["answer"] = answer
    state["data"] = []
    state["sql"] = None
    state["generated_title"] = f"Knowledge: {question[:60]}"
    state["chosen_tables"] = []
    state["chosen_tables_physical"] = []
    state["evidence"] = evidence
    state["reasoning_steps"] = steps

    return state
