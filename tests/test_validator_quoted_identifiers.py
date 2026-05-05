"""Lucas's 2026-05-05 demo QA: the orchestrator picked the correct
table (``opportunities``) and the SQL specialist produced valid
postgres ``SELECT ... FROM "crm"."opportunities"``, but the SQL
validator rejected it with ``Table 'crm"."opportunities' is not
allowed``.

The bug was in ``_extract_tables``: ``ident.strip('"')`` only peels
the outermost pair of quotes, so a quoted compound identifier
collapses to ``crm"."opportunities`` instead of ``crm.opportunities``.
Then ``_table_variants`` splits on ``.`` and ends up with
``{'crm"', '"opportunities', 'crm"."opportunities'}`` — none of which
match the allow-list entry ``crm.opportunities``.

These tests pin the invariant: every reasonable postgres quoting
combination must reduce to the same allow-list-matchable identifier.
"""

from __future__ import annotations

from core.sql.validator_advanced import AdvancedSQLValidator


ALLOWED = ["crm.opportunities", "crm.accounts"]


def _validator() -> AdvancedSQLValidator:
    return AdvancedSQLValidator(allowed_tables=ALLOWED)


def test_unquoted_compound_identifier_is_allowed():
    ok, err = _validator().validate('SELECT id FROM crm.opportunities LIMIT 5', dialect="postgres")
    assert ok, f"unexpected reject: {err}"


def test_double_quoted_compound_identifier_is_allowed():
    """The exact failure Lucas saw: GPT-4o emits postgres-style
    ``"schema"."table"``. Stripping only the outer quotes used to
    leave an internal ``"`` that broke variant-matching."""
    ok, err = _validator().validate(
        'SELECT id FROM "crm"."opportunities" LIMIT 5', dialect="postgres"
    )
    assert ok, f"unexpected reject for quoted compound: {err}"


def test_double_quoted_table_only_is_allowed():
    ok, err = _validator().validate(
        'SELECT id FROM "opportunities" LIMIT 5', dialect="postgres"
    )
    assert ok, f"unexpected reject for quoted bare: {err}"


def test_disallowed_table_still_rejected():
    """Defence-in-depth: the fix must not turn into a blanket allow.
    A table outside the allow-list must still be rejected — even when
    the LLM tries to sneak it in via heavy quoting."""
    ok, err = _validator().validate(
        'SELECT * FROM "secrets"."internal_keys" LIMIT 1', dialect="postgres"
    )
    assert not ok
    assert err and "not allowed" in err.lower()


def test_mixed_case_quoted_identifier_normalised():
    ok, err = _validator().validate(
        'SELECT id FROM "CRM"."Opportunities" LIMIT 5', dialect="postgres"
    )
    assert ok, f"unexpected reject for mixed case: {err}"
