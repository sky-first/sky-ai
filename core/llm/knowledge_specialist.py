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

logger = logging.getLogger("dataassistant")


KNOWLEDGE_SYSTEM_PROMPT = """You are an enterprise knowledge analyst.

You have access to the company's curated Knowledge layer below. Use it
as the authoritative source — prefer Org-certified definitions over
your prior knowledge.

When the question asks about a metric, cite its definition / formula
description / unit. When it asks about a term, cite the glossary
definition. When it asks how things connect, cite the matching
relationship (sources → target, type, AI-inferred confidence if any).

If the catalog doesn't cover the question, say so plainly and suggest
the user create the missing Metric / Glossary / Relationship entry.

Respond in the same language as the user's question.

## Knowledge catalog
{knowledge_block}
"""


def _format_metric(m: Dict[str, Any]) -> str:
    name = m.get("name", "Unnamed")
    scope = (m.get("scope") or "").upper()
    certified = bool(m.get("certified_by_user_id"))
    tag = "[ORG-CERTIFIED]" if certified and scope == "ORG" else f"[{scope}]" if scope else ""
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


def run_knowledge_specialist(
    state: Dict[str, Any],
    llm: Any,
    backend_client: Any,
) -> Dict[str, Any]:
    """LangGraph node — answers Knowledge questions (metrics / glossary / relationships)."""
    question = state.get("question", "")

    log_event("knowledge_specialist_start", {"question": question[:100]})

    metrics = backend_client.get_metrics() if hasattr(backend_client, "get_metrics") else []
    glossary = backend_client.get_glossary() if hasattr(backend_client, "get_glossary") else []
    relationships = (
        backend_client.get_enterprise_relationships()
        if hasattr(backend_client, "get_enterprise_relationships")
        else []
    )

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
        return state

    knowledge_block = _build_knowledge_block(metrics, glossary, relationships)
    system_prompt = KNOWLEDGE_SYSTEM_PROMPT.format(knowledge_block=knowledge_block)

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
    except Exception as e:
        logger.error(f"Knowledge specialist LLM error: {e}")
        answer = f"I found Knowledge data but ran into an error analyzing it: {e}"

    log_event("knowledge_specialist_done", {
        "question": question[:100],
        "answer_preview": (answer or "")[:200],
        "num_metrics": len(metrics),
        "num_glossary": len(glossary),
        "num_relationships": len(relationships),
    })

    state["answer"] = answer
    state["data"] = []
    state["sql"] = None
    state["generated_title"] = f"Knowledge: {question[:60]}"
    state["chosen_tables"] = []
    state["chosen_tables_physical"] = []

    return state
