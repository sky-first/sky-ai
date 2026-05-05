"""Unit tests for the Personal-vs-Space isolation contract inside
``_build_embedding_base_query``. This is the single choke point that
the RAG depends on; if it ever regresses, every chat call starts
leaking Personal data across users.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.dialects import postgresql

from core.rag.vector_store import _build_embedding_base_query


def _compile(query) -> str:
    """Render the SQLAlchemy select as a raw SQL string using the
    postgres dialect so UUID params render correctly."""
    return str(
        query.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_personal_mode_filters_by_owner_user_id():
    user_a = uuid4()
    space = uuid4()
    q = _build_embedding_base_query(
        space_id=space, crew_ids=[], is_personal=True, user_id=user_a
    )
    sql = _compile(q)
    # Must filter on user_id = caller.
    assert f"embeddings.user_id = '{user_a}'" in sql
    # Must NOT constrain to space/crew — Personal is owner-scoped,
    # space metadata is irrelevant and would over-filter.
    assert "embeddings.space_id =" not in sql


def test_personal_mode_without_user_id_returns_nothing():
    # Defense-in-depth: Personal without user_id must not fall back to
    # unfiltered Space reads. The safest outcome is "match nothing".
    q = _build_embedding_base_query(
        space_id=uuid4(), crew_ids=[], is_personal=True, user_id=None
    )
    sql = _compile(q).lower()
    assert "false" in sql or "0 = 1" in sql


def test_space_mode_excludes_any_personal_rows():
    # The core anti-leak invariant: Space/Crew queries must only see
    # embeddings where owner_user_id IS NULL, so another user's
    # Personal rows cannot surface in a shared context.
    space = uuid4()
    q = _build_embedding_base_query(
        space_id=space, crew_ids=[uuid4()], is_personal=False
    )
    sql = _compile(q)
    assert "embeddings.user_id IS NULL" in sql
    assert f"embeddings.space_id = '{space}'" in sql


def test_space_mode_crew_filter_applied():
    c1, c2 = uuid4(), uuid4()
    q = _build_embedding_base_query(
        space_id=uuid4(), crew_ids=[c1, c2], is_personal=False
    )
    sql = _compile(q)
    assert "embeddings.crew_id IS NULL" in sql
    # In-clause with the two crew ids.
    assert f"'{c1}'" in sql
    assert f"'{c2}'" in sql


def test_connection_filter_personal_skips_space_where():
    # With a connection, Personal still means "my own items" — the
    # JOIN with TableMetadata restricts to this connection's tables
    # (or knowledge-graph rows with no table), but space/crew are
    # irrelevant because ownership is already unique.
    user_a = uuid4()
    conn = uuid4()
    q = _build_embedding_base_query(
        space_id=uuid4(),
        crew_ids=[],
        connection_id=conn,
        is_personal=True,
        user_id=user_a,
    )
    sql = _compile(q)
    assert f"embeddings.user_id = '{user_a}'" in sql
    assert f"table_metadata.data_connection_id = '{conn}'" in sql


def test_connection_filter_space_scope():
    space = uuid4()
    conn = uuid4()
    q = _build_embedding_base_query(
        space_id=space,
        crew_ids=[],
        connection_id=conn,
        is_personal=False,
    )
    sql = _compile(q)
    assert "embeddings.user_id IS NULL" in sql
    assert f"table_metadata.data_connection_id = '{conn}'" in sql


def test_space_mode_with_connection_id_includes_shared_embeddings():
    """Lucas's 2026-05-05 review: demo connections are indexed once with
    space_id=NULL and shared across every Space that bridges the
    connection. The RAG must surface those shared embeddings to every
    caller — `space_id == caller_space OR space_id IS NULL` — otherwise
    each visitor needs their own re-indexing pass and the AI answers
    'Sorry, I couldn't find any data' until the background discover
    finishes.
    """
    caller_space = uuid4()
    conn = uuid4()
    q = _build_embedding_base_query(
        space_id=str(caller_space),
        crew_ids=[],
        connection_id=str(conn),
        is_personal=False,
    )
    sql = _compile(q)
    # Must accept embeddings whose space_id is the caller's OR null.
    # The exact rendering is "embeddings.space_id = '<uuid>' OR embeddings.space_id IS NULL"
    assert f"embeddings.space_id = '{caller_space}'" in sql
    assert "embeddings.space_id IS NULL" in sql
    # And must still scope to the connection.
    assert f"table_metadata.data_connection_id = '{conn}'" in sql
