"""The audit table's ensure-step must self-heal columns added later.

Regression cover for a production incident. ``_ensure_audit_table_async``
only ran ``CREATE TABLE IF NOT EXISTS``, which is a no-op once the table
exists — so every column appended to the DDL after the table first
shipped never reached environments created before it.

Production's ``query_audit_log`` was missing eight columns
(``platform_role``, ``crew_role`` and the whole PII block). Each flush
died with

    column "platform_role" of relation "query_audit_log" does not exist

and the audit rows were dropped silently, PII-detection evidence
included.

These tests are static: they read the SQL out of the source file rather
than standing up Postgres — and deliberately *read* it instead of
importing it, because ``core.security.audit`` pulls in the LLM provider
chain and would need the full runtime installed. The failure mode that
matters (the DDL and the ALTER drifting apart) is visible in the text.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

AUDIT_PY = Path(__file__).resolve().parents[1] / "core" / "security" / "audit.py"


@pytest.fixture(scope="module")
def source() -> str:
    return AUDIT_PY.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def create_columns(source: str) -> set:
    body = re.search(
        r"CREATE TABLE IF NOT EXISTS query_audit_log \((.*?)\);", source, re.S
    )
    assert body, "CREATE TABLE for query_audit_log not found"
    return {m.group(1) for m in re.finditer(r"^\s+(\w+)\s+\w", body.group(1), re.M)}


@pytest.fixture(scope="module")
def altered_columns(source: str) -> set:
    body = re.search(r"ALTER TABLE query_audit_log(.*?);", source, re.S)
    assert body, "self-healing ALTER TABLE not found — the CREATE alone " \
                 "cannot add columns to an existing table"
    return {
        m.group(1)
        for m in re.finditer(r"ADD COLUMN IF NOT EXISTS (\w+)", body.group(1))
    }


def test_alter_exists_at_all(altered_columns):
    """Without it, an environment whose table predates a new column can
    never acquire it, and every flush fails forever."""
    assert altered_columns


def test_every_altered_column_is_idempotent(source):
    """A bare ADD COLUMN would raise on the second run and take the whole
    ensure-step down with it."""
    alter = re.search(r"ALTER TABLE query_audit_log(.*?);", source, re.S).group(1)
    adds = re.findall(r"ADD COLUMN\s+(?:IF NOT EXISTS\s+)?(\w+)", alter)
    idempotent = re.findall(r"ADD COLUMN IF NOT EXISTS (\w+)", alter)
    assert sorted(adds) == sorted(idempotent)


def test_altered_columns_are_a_subset_of_the_ddl(create_columns, altered_columns):
    """The ALTER must never introduce a column the CREATE doesn't know
    about — a fresh environment would then differ from a healed one."""
    unknown = altered_columns - create_columns
    assert not unknown, f"columns only in the ALTER: {sorted(unknown)}"


@pytest.mark.parametrize(
    "column",
    [
        "platform_role",
        "crew_role",
        "pii_detected_in_prompt",
        "pii_detected_in_response",
        "pii_types",
        "pii_severity",
        "pii_patterns_matched",
        "pii_blocked",
    ],
)
def test_columns_missing_in_production_are_healed(column, altered_columns):
    """The exact eight columns absent from the production table on
    2026-08-03, verified against information_schema at the time."""
    assert column in altered_columns


def test_insert_columns_are_all_covered(source, create_columns):
    """Anything the INSERT writes must exist in the DDL, otherwise the
    flush fails for a *different* missing column next time."""
    insert = re.search(
        r"INSERT INTO query_audit_log \((.*?)\)\s*VALUES", source, re.S
    )
    assert insert, "INSERT INTO query_audit_log not found"
    written = {
        c.strip()
        for c in insert.group(1).replace("\n", " ").split(",")
        if c.strip() and not c.strip().startswith("--")
    }
    missing = written - create_columns
    assert not missing, f"INSERT writes columns absent from the DDL: {sorted(missing)}"
