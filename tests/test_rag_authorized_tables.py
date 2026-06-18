"""RAG control-plane: table/column context is filtered by the backend
authorized-tables allow-list, so the retrieval context can't leak another
crew's table names/descriptions. Non-table docs keep their own scoping.
"""

from types import SimpleNamespace

from core.rag.context_retrieval import (
    _filter_ranked_by_authorized_tables,
    _normalize_table_name,
)


def _rd(kind, title, metadata=None):
    """Minimal RankedDoc stand-in: only .doc.kind/.title/.metadata are used."""
    return SimpleNamespace(
        doc=SimpleNamespace(kind=kind, title=title, metadata=metadata or {})
    )


def test_keeps_only_authorized_tables_and_columns():
    ranked = [
        _rd("table", "invoices"),
        _rd("table", "payments"),  # not authorized → dropped
        _rd("column", "amount", {"table_name": "invoices"}),
        _rd("column", "value", {"table_name": "payments"}),  # dropped
        _rd("goal", "Q4 revenue"),  # non-table → always kept
        _rd("okr", "ARR target"),  # non-table → always kept
    ]
    out = _filter_ranked_by_authorized_tables(ranked, ["invoices"])
    assert [r.doc.title for r in out] == [
        "invoices",
        "amount",
        "Q4 revenue",
        "ARR target",
    ]


def test_none_means_no_restriction():
    ranked = [_rd("table", "payments")]
    assert _filter_ranked_by_authorized_tables(ranked, None) is ranked


def test_empty_list_is_fail_closed_for_tables():
    # [] = authorized for nothing → all table/column docs drop, non-table stay.
    ranked = [_rd("table", "invoices"), _rd("goal", "x")]
    out = _filter_ranked_by_authorized_tables(ranked, [])
    assert [r.doc.kind for r in out] == ["goal"]


def test_normalizes_schema_and_connection_prefixes():
    ranked = [_rd("table", "conn::finance.invoices")]
    out = _filter_ranked_by_authorized_tables(ranked, ["invoices"])
    assert len(out) == 1
    assert _normalize_table_name("conn::finance.invoices") == "invoices"


def test_unattributable_table_doc_is_dropped():
    # a column doc with no resolvable table name is dropped (fail-closed).
    ranked = [_rd("column", "orphan_col", {})]
    assert _filter_ranked_by_authorized_tables(ranked, ["invoices"]) == []
