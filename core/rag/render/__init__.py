"""Context document render templates — Phase 2.3.

The ingest worker consumes events from the ``context:ingest`` Redis
stream (produced by sky-poc-backend), fetches the full row from the
backend (per-kind endpoint, HMAC authenticated), and calls the matching
template below to produce the (title, body, metadata) tuple that is
then embedded and written to ``context_documents``.

A template has ONE responsibility: turn a source-row dict into the
textual form that best serves retrieval. A good template:

- Front-loads the most semantically distinctive fields in the title.
- Writes the body in natural language so the LLM can *quote* it back
  to the user (retrieval = evidence).
- Includes related context (pillar owner → goal render, connection
  dataset list → table render) to bridge graph edges.
- Never includes PII values — that's the response filter's job. PII
  column NAMES are fine; the VALUES must stay behind masking.

Add a new kind by:
1. Dropping ``<kind>.py`` in this package with a ``render(row) -> RenderedDoc``.
2. Registering in ``_templates`` at the bottom of this file.
3. Adding a matching ContextMapping in the backend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class RenderedDoc:
    title: str
    body: str
    metadata: dict[str, Any] = field(default_factory=dict)
    pii_flags: list[str] = field(default_factory=list)
    language: str = "pt"


Renderer = Callable[[dict[str, Any]], RenderedDoc]


def render(kind: str, row: dict[str, Any]) -> RenderedDoc:
    """Dispatch to the right template for ``kind``.

    Raises KeyError if no template is registered — callers should treat
    that as a programming error (every kind the backend emits must have
    a template here; ingest worker should skip and log).
    """
    return _templates[kind](row)


def has_template(kind: str) -> bool:
    return kind in _templates


def register(kind: str, renderer: Renderer) -> None:
    _templates[kind] = renderer


def _coerce(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, (list, tuple)):
        return ", ".join(_coerce(x) for x in v) if v else "—"
    if isinstance(v, dict):
        return ", ".join(f"{k}: {_coerce(val)}" for k, val in v.items())
    return str(v)


# ─── Strategy family ──────────────────────────────────────────────────────
def _render_pillar(row: dict[str, Any]) -> RenderedDoc:
    title = f"Pillar: {row.get('title') or row.get('name') or 'Untitled'}"
    body = (
        f"Strategic pillar: {row.get('title') or row.get('name')}\n"
        f"Description: {row.get('description') or '—'}\n"
        f"Owner: {_coerce(row.get('owner'))}\n"
        f"Status: {row.get('status') or '—'}"
    )
    return RenderedDoc(title=title, body=body, metadata={"owner": row.get("owner")})


def _render_goal(row: dict[str, Any]) -> RenderedDoc:
    title = f"Goal: {row.get('title') or 'Untitled'}"
    body = (
        f"Strategic goal (type={row.get('type') or '—'}): {row.get('title')}\n"
        f"Description: {row.get('description') or '—'}\n"
        f"Status: {row.get('status') or '—'}  |  Priority: {row.get('priority') or '—'}  |  Area: {row.get('area') or '—'}\n"
        f"Owner: {_coerce(row.get('owner'))}\n"
        f"KPIs: {_coerce(row.get('kpis'))}\n"
        f"Budget: {row.get('budget') if row.get('budget') is not None else '—'}\n"
        f"Pillar: {row.get('pillar_title') or '—'}"
    )
    return RenderedDoc(title=title, body=body, metadata={
        "priority": row.get("priority"),
        "status": row.get("status"),
        "area": row.get("area"),
    })


def _render_okr(row: dict[str, Any]) -> RenderedDoc:
    title = f"OKR: {row.get('title') or 'Untitled'}"
    body = (
        f"Objective-key-result: {row.get('title')}\n"
        f"Objective (parent goal): {row.get('objective_title') or '—'}\n"
        f"Cycle: {row.get('cycle_title') or '—'}\n"
        f"Baseline → Target: {row.get('baseline') if row.get('baseline') is not None else '—'} → "
        f"{row.get('target') if row.get('target') is not None else '—'}\n"
        f"Deadline: {row.get('deadline') or '—'}  |  Measurement: {row.get('measurement_frequency') or '—'}"
    )
    return RenderedDoc(title=title, body=body, metadata={
        "deadline": row.get("deadline"),
        "baseline": row.get("baseline"),
        "target": row.get("target"),
    })


def _render_initiative(row: dict[str, Any]) -> RenderedDoc:
    title = f"Initiative: {row.get('title') or 'Untitled'}"
    body = (
        f"Strategic initiative: {row.get('title')}\n"
        f"Description: {row.get('description') or '—'}\n"
        f"Status: {row.get('status') or '—'}  |  Owner: {_coerce(row.get('owner'))}\n"
        f"Linked goals: {_coerce(row.get('linked_goals'))}"
    )
    return RenderedDoc(title=title, body=body)


def _render_kpi(row: dict[str, Any]) -> RenderedDoc:
    # Maps to StrategyKeyResult in the backend.
    title = f"KPI: {row.get('title') or 'Untitled'}"
    body = (
        f"Key result / KPI: {row.get('title')}\n"
        f"Description: {row.get('description') or '—'}\n"
        f"Unit: {row.get('unit') or '—'}  |  Target: {row.get('target') if row.get('target') is not None else '—'}\n"
        f"Current: {row.get('current_value') if row.get('current_value') is not None else '—'}  |  "
        f"Progress: {row.get('progress_pct') if row.get('progress_pct') is not None else '—'}%"
    )
    return RenderedDoc(title=title, body=body)


def _render_risk(row: dict[str, Any]) -> RenderedDoc:
    # Maps to StrategyAssumption in the backend.
    title = f"Risk: {row.get('title') or 'Untitled'}"
    body = (
        f"Risk / assumption: {row.get('title')}\n"
        f"Description: {row.get('description') or '—'}\n"
        f"Likelihood: {row.get('likelihood') or '—'}  |  Impact: {row.get('impact') or '—'}\n"
        f"Owner: {_coerce(row.get('owner'))}"
    )
    return RenderedDoc(title=title, body=body)


def _render_glossary(row: dict[str, Any]) -> RenderedDoc:
    title = f"Term: {row.get('term') or row.get('title') or 'Untitled'}"
    body = (
        f"{row.get('term') or row.get('title')}\n"
        f"Definition: {row.get('definition') or row.get('description') or '—'}"
    )
    return RenderedDoc(title=title, body=body)


# ─── Events family ────────────────────────────────────────────────────────
def _render_event_generic(category: str):
    def _renderer(row: dict[str, Any]) -> RenderedDoc:
        title = f"{category.title()} event: {row.get('title') or row.get('sub_type') or '—'}"
        body = (
            f"{category.title()} event ({row.get('sub_type') or '—'} / "
            f"{row.get('nature') or '—'}, confidence={row.get('confidence') or '—'}).\n"
            f"Description: {row.get('description') or '—'}\n"
            f"Start: {row.get('start_date') or '—'}  |  Impact: {row.get('impact_date') or '—'}\n"
            f"Related: {_coerce(row.get('relations'))}"
        )
        return RenderedDoc(title=title, body=body, metadata={
            "nature": row.get("nature"),
            "confidence": row.get("confidence"),
        })

    return _renderer


# ─── Relationships ────────────────────────────────────────────────────────
def _render_relationship(row: dict[str, Any]) -> RenderedDoc:
    title = (
        f"Relationship: {row.get('source_label') or row.get('source_id') or '?'} "
        f"→ {row.get('target_label') or row.get('target_id') or '?'}"
    )
    body = (
        f"{row.get('source_label') or row.get('source_id')} "
        f"→ {row.get('target_label') or row.get('target_id')}\n"
        f"Type: {row.get('relationship_type') or row.get('kind') or '—'}\n"
        f"Strength: {row.get('strength') if row.get('strength') is not None else '—'}\n"
        f"Description: {row.get('description') or '—'}"
    )
    return RenderedDoc(title=title, body=body)


# ─── Platform fabric ──────────────────────────────────────────────────────
def _render_user(row: dict[str, Any]) -> RenderedDoc:
    title = f"User: {row.get('name') or row.get('email') or 'Unknown'}"
    body = (
        f"Platform user: {row.get('name') or '—'} <{row.get('email') or '—'}>\n"
        f"Role: {row.get('role') or '—'}\n"
        f"Title / job: {row.get('job_title') or '—'}\n"
        f"Crews: {_coerce(row.get('crews'))}"
    )
    return RenderedDoc(title=title, body=body, pii_flags=["email"])


def _render_space(row: dict[str, Any]) -> RenderedDoc:
    title = f"Space: {row.get('name') or 'Untitled'}"
    body = (
        f"Space: {row.get('name')}\n"
        f"Description: {row.get('description') or '—'}\n"
        f"Crews: {_coerce(row.get('crews'))}  |  Members: {_coerce(row.get('members'))}\n"
        f"Connections: {_coerce(row.get('connections'))}"
    )
    return RenderedDoc(title=title, body=body)


def _render_crew(row: dict[str, Any]) -> RenderedDoc:
    title = f"Crew: {row.get('name') or 'Untitled'}"
    body = (
        f"Crew: {row.get('name')} (space: {row.get('space_name') or '—'})\n"
        f"Members: {_coerce(row.get('members'))}\n"
        f"Connections granted: {_coerce(row.get('connections'))}"
    )
    return RenderedDoc(title=title, body=body)


# ─── Connections / Tables / Columns ───────────────────────────────────────
def _render_connection(row: dict[str, Any]) -> RenderedDoc:
    title = f"Connection: {row.get('name') or 'Untitled'}"
    body = (
        f"Data connection {row.get('name')} "
        f"(type={row.get('connection_type') or row.get('type') or '—'}).\n"
        f"Description: {row.get('description') or '—'}\n"
        f"Tables: {_coerce(row.get('tables'))}"
    )
    return RenderedDoc(title=title, body=body)


def _render_table(row: dict[str, Any]) -> RenderedDoc:
    title = f"Table: {row.get('name') or 'Untitled'}"
    body = (
        f"Table {row.get('schema') or ''}.{row.get('name')}\n"
        f"Description: {row.get('description') or '—'}\n"
        f"Connection: {row.get('connection_name') or '—'}\n"
        f"Columns: {_coerce(row.get('columns'))}\n"
        f"Row count estimate: {row.get('row_count') if row.get('row_count') is not None else '—'}"
    )
    return RenderedDoc(title=title, body=body, metadata={
        "connection_id": row.get("connection_id"),
        "row_count": row.get("row_count"),
    })


def _render_column(row: dict[str, Any]) -> RenderedDoc:
    title = f"Column: {row.get('table_name') or '?'}.{row.get('name') or 'Untitled'}"
    pii = []
    if row.get("is_pii") or (row.get("pii_flag") and row.get("pii_flag") != "none"):
        pii.append(row.get("name") or "column")
    body = (
        f"Column {row.get('table_name') or '?'}.{row.get('name')}\n"
        f"Type: {row.get('data_type') or '—'}\n"
        f"Description: {row.get('description') or '—'}\n"
        f"Nullable: {row.get('is_nullable')}  |  PII: {bool(row.get('is_pii'))}\n"
        f"Sample values: {_coerce(row.get('sample_values'))}"
    )
    # Metadata surfaces the (connection_id, table_name, column_name) triple
    # so retrieval can apply per-space `hidden_columns` filters without
    # parsing the title string. Without this, the per-space visibility
    # feature (sky-poc-backend#190) can't drop column docs reliably.
    return RenderedDoc(
        title=title,
        body=body,
        pii_flags=pii,
        metadata={
            "connection_id": row.get("connection_id"),
            "table_name": row.get("table_name"),
            "column_name": row.get("name"),
        },
    )


# ─── Outputs & social ─────────────────────────────────────────────────────
def _render_widget(row: dict[str, Any]) -> RenderedDoc:
    title = f"Widget: {row.get('title') or 'Untitled'}"
    body = (
        f"Dashboard widget: {row.get('title')} "
        f"(type={row.get('type') or '—'}).\n"
        f"Dashboard: {row.get('dashboard_name') or '—'}  |  "
        f"Connection: {row.get('connection_name') or '—'}\n"
        f"Question / prompt: {row.get('question') or row.get('prompt') or '—'}\n"
        f"Last answer: {row.get('last_answer') or '—'}"
    )
    return RenderedDoc(title=title, body=body)


def _render_insight(row: dict[str, Any]) -> RenderedDoc:
    # "Insight" is the user-facing name for a widget that the chat pinned.
    # Re-use widget template but keep a distinct kind for retrieval weights.
    doc = _render_widget(row)
    doc.title = f"Insight: {row.get('title') or 'Untitled'}"
    return doc


def _render_pin(row: dict[str, Any]) -> RenderedDoc:
    title = f"Pin: {row.get('title') or row.get('source_title') or 'Untitled'}"
    body = (
        f"Pinned item: {row.get('title') or row.get('source_title')}\n"
        f"On page: {row.get('page_name') or '—'}\n"
        f"Note: {row.get('note') or '—'}"
    )
    return RenderedDoc(title=title, body=body)


def _render_conversation(row: dict[str, Any]) -> RenderedDoc:
    title = f"Conversation: {row.get('title') or 'Untitled'}"
    body = (
        f"Chat thread: {row.get('title') or '—'}\n"
        f"On page: {row.get('page_name') or '—'}\n"
        f"Messages: {row.get('message_count') if row.get('message_count') is not None else '—'}  "
        f"|  Last activity: {row.get('updated_at') or '—'}\n"
        f"Summary: {row.get('summary') or '—'}"
    )
    return RenderedDoc(title=title, body=body)


def _render_message(row: dict[str, Any]) -> RenderedDoc:
    # Messages are embedded so the brain can cite specific Q/A exchanges.
    role = row.get("role") or "user"
    title = f"Message ({role}): {(row.get('content') or '')[:60]}"
    body = (
        f"Role: {role}\n"
        f"Content: {row.get('content') or '—'}\n"
        f"Conversation: {row.get('conversation_title') or '—'}"
    )
    return RenderedDoc(title=title, body=body)


def _render_like(row: dict[str, Any]) -> RenderedDoc:
    title = f"Like on {row.get('target_kind') or 'item'}: {row.get('target_title') or '—'}"
    body = (
        f"User {row.get('user_name') or '—'} liked "
        f"{row.get('target_kind') or 'item'} '{row.get('target_title') or '—'}' "
        f"on {row.get('created_at') or '—'}."
    )
    return RenderedDoc(title=title, body=body)


def _render_role(row: dict[str, Any]) -> RenderedDoc:
    title = f"Role: {row.get('name') or 'Untitled'}"
    body = (
        f"Role: {row.get('name')}\n"
        f"Description: {row.get('description') or '—'}\n"
        f"Permissions: {_coerce(row.get('permissions'))}"
    )
    return RenderedDoc(title=title, body=body)


def _render_membership(row: dict[str, Any]) -> RenderedDoc:
    title = (
        f"Membership: {row.get('user_name') or row.get('user_id') or '?'}"
        f" in {row.get('crew_name') or row.get('space_name') or '?'}"
    )
    body = (
        f"Membership link: {row.get('user_name') or row.get('user_id')} "
        f"({row.get('role') or '—'}) in "
        f"{row.get('crew_name') or row.get('space_name')}"
    )
    return RenderedDoc(title=title, body=body)


# ─── Registry ─────────────────────────────────────────────────────────────
_templates: dict[str, Renderer] = {
    "pillar": _render_pillar,
    "goal": _render_goal,
    "okr": _render_okr,
    "initiative": _render_initiative,
    "kpi": _render_kpi,
    "risk": _render_risk,
    "glossary": _render_glossary,
    "event_internal": _render_event_generic("internal"),
    "event_external": _render_event_generic("external"),
    "event_trend": _render_event_generic("trend"),
    "event_macro": _render_event_generic("macro"),
    "relationship": _render_relationship,
    "user": _render_user,
    "role": _render_role,
    "space": _render_space,
    "crew": _render_crew,
    "membership": _render_membership,
    "connection": _render_connection,
    "table": _render_table,
    "column": _render_column,
    "widget": _render_widget,
    "insight": _render_insight,
    "pin": _render_pin,
    "conversation": _render_conversation,
    "message": _render_message,
    "like": _render_like,
}
