"""Shared helper — inject Context-Layer evidence into specialist prompts.

Phase 4.1. Every specialist (strategy, events, relationships, people,
widgets, API, orchestrator) now prefixes its LLM user prompt with the
brain blend that ``brain_retrieval_node`` populated into ``AgentState``
at the top of the graph (Phase 2.6b).

Keeping this in one helper means:

  * All specialists share the exact same <contexto_recuperado>
    wrapper, so the model learns to trust it and quote from it.
  * If we later change the format (add a trailing source-id list, for
    instance, or switch tag name), it's one edit.
  * The helper is a no-op when the brain returned nothing — empty
    string, unchanged prompt, zero behavioural difference from the
    pre-4.1 world.

Usage:

    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": prepend_brain_context(question, state)},
    ]
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

# Bounded to keep the specialist prompt compact — if the brain returns
# a 50-doc blend we trim to the top 12 most-relevant blocks, which is
# roughly the sweet spot where recall stops adding signal for an
# answer-generation LLM and starts costing tokens.
DEFAULT_MAX_BLOCKS = 12


def prepend_brain_context(
    user_question: str,
    state: Mapping[str, Any],
    *,
    max_blocks: int = DEFAULT_MAX_BLOCKS,
) -> str:
    """Return ``user_question`` with a retrieved-context preamble if the
    brain found anything.

    ``state['brain_context']`` is a list of already-formatted text
    blocks (``[kind] title\\nbody``) set by the brain-retrieval node.
    When the list is empty or absent, returns ``user_question``
    unchanged.
    """
    blocks = state.get("brain_context") if isinstance(state, Mapping) else None
    if not blocks:
        return user_question
    kept = [b for b in blocks[:max_blocks] if isinstance(b, str) and b.strip()]
    if not kept:
        return user_question
    header = (
        "<contexto_recuperado>\n"
        "A plataforma recuperou o seguinte contexto relevante — use-o "
        "para ancorar sua resposta e citar explicitamente os itens "
        "quando aplicável. Se o contexto contradiz a pergunta do "
        "usuário, prefira o contexto.\n\n"
        + "\n\n".join(kept)
        + "\n</contexto_recuperado>"
    )
    return f"{header}\n\n{user_question}"


def brain_context_summary(state: Mapping[str, Any]) -> str:
    """Short log line describing what the brain retrieved, for
    observability. Used by specialists in their log_event payloads.
    """
    kinds = state.get("brain_doc_kinds") if isinstance(state, Mapping) else None
    ids = state.get("brain_doc_ids") if isinstance(state, Mapping) else None
    if not ids:
        return "brain=empty"
    unique_kinds = sorted(set(k for k in (kinds or []) if isinstance(k, str)))
    return f"brain={len(ids)}docs kinds={','.join(unique_kinds)}"


def iter_brain_blocks(
    state: Mapping[str, Any], max_blocks: int = DEFAULT_MAX_BLOCKS
) -> Iterable[str]:
    """Raw iterator for callers that want to weave the blocks into a
    larger prompt themselves instead of prepending."""
    blocks = state.get("brain_context") if isinstance(state, Mapping) else None
    if not blocks:
        return []
    return [b for b in list(blocks)[:max_blocks] if isinstance(b, str) and b.strip()]
