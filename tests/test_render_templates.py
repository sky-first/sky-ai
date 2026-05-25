"""Tests for Phase 2.3 context render templates.

These exist to keep the render contract stable — every `kind` the backend
emits must have a template that returns a non-empty title + body. Future
PRs that add a new kind just drop another case here.
"""

from __future__ import annotations

import pytest

from core.rag.render import RenderedDoc, has_template, render

KINDS = [
    "pillar",
    "goal",
    "okr",
    "initiative",
    "kpi",
    "risk",
    "glossary",
    "event_internal",
    "event_external",
    "event_trend",
    "event_macro",
    "relationship",
    "user",
    "role",
    "space",
    "crew",
    "membership",
    "connection",
    "table",
    "column",
    "widget",
    "insight",
    "pin",
    "conversation",
    "message",
    "like",
]


@pytest.mark.parametrize("kind", KINDS)
def test_every_kind_has_template(kind: str):
    assert has_template(kind), f"missing template for kind={kind!r}"


@pytest.mark.parametrize("kind", KINDS)
def test_templates_produce_nonempty_output_on_empty_row(kind: str):
    # Even with no data, the template must not crash and must return a
    # human-readable placeholder — the ingest worker receives partial rows
    # during the backfill sweep and must not die.
    doc = render(kind, {})
    assert isinstance(doc, RenderedDoc)
    assert doc.title.strip(), "title must not be empty"
    assert doc.body.strip(), "body must not be empty"


def test_goal_template_surfaces_key_fields():
    row = {
        "type": "corporate",
        "title": "Increase ARR by 20%",
        "description": "Main growth lever for 2026",
        "status": "on_track",
        "priority": "P0",
        "area": "revenue",
        "owner": "cfo",
        "kpis": ["arr", "new_logos"],
        "budget": 1_500_000,
        "pillar_title": "Growth",
    }
    doc = render("goal", row)
    assert "Increase ARR by 20%" in doc.title
    assert "Increase ARR by 20%" in doc.body
    assert "Main growth lever" in doc.body
    assert "P0" in doc.body
    assert "Growth" in doc.body, "parent pillar must appear as evidence link"
    assert doc.metadata["priority"] == "P0"


def test_okr_template_links_to_objective_and_cycle():
    row = {
        "title": "Close 100 deals Q4",
        "objective_title": "Increase ARR by 20%",
        "cycle_title": "2026-Q4",
        "baseline": 70,
        "target": 100,
        "deadline": "2026-12-31",
        "measurement_frequency": "weekly",
    }
    doc = render("okr", row)
    assert "Close 100 deals Q4" in doc.title
    assert "Increase ARR by 20%" in doc.body, "must cite parent objective"
    assert "2026-Q4" in doc.body


def test_event_templates_prefix_with_category():
    internal = render(
        "event_internal", {"sub_type": "layoff", "description": "restructure"}
    )
    external = render("event_external", {"sub_type": "fx_move", "description": "USD"})
    trend = render("event_trend", {"sub_type": "ai_demand", "description": "up 40%"})
    macro = render("event_macro", {"sub_type": "rates", "description": "Selic"})
    assert "internal" in internal.title.lower()
    assert "external" in external.title.lower()
    assert "trend" in trend.title.lower()
    assert "macro" in macro.title.lower()


def test_column_marks_pii_flag():
    row = {
        "name": "email",
        "table_name": "customers",
        "data_type": "text",
        "description": "customer email",
        "is_pii": True,
    }
    doc = render("column", row)
    assert "email" in doc.pii_flags


def test_user_marks_email_pii_always():
    doc = render("user", {"name": "Paulo", "email": "paulo@sky.com", "role": "admin"})
    assert "email" in doc.pii_flags


def test_table_metadata_carries_connection_id_and_row_count():
    row = {
        "name": "orders",
        "schema": "public",
        "connection_name": "hubspot",
        "connection_id": "c1",
        "row_count": 125_000,
        "description": "orders table",
    }
    doc = render("table", row)
    assert doc.metadata["connection_id"] == "c1"
    assert doc.metadata["row_count"] == 125_000
