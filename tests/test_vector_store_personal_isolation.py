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
    # With a connection_id, Personal accepts:
    #   • this user's own items (`user_id = caller`), AND
    #   • truly-shared rows (`user_id IS NULL AND space_id IS NULL`)
    #     — pinned to the connection itself.
    # We deliberately do NOT accept `user_id IS NULL AND space_id !=
    # NULL` because that's space-scoped content for some space the
    # caller may not be a member of — leak vector flagged in Lucas's
    # 2026-05-05 adversarial review.
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
    # NULL acceptance must be paired with space_id IS NULL.
    assert "embeddings.user_id IS NULL" in sql
    assert "embeddings.space_id IS NULL" in sql
    assert f"table_metadata.data_connection_id = '{conn}'" in sql


def test_personal_mode_with_caller_space_ids_surfaces_member_space_content():
    """When the caller is a member of S1 and S2, Personal-mode RAG
    must surface NULL-user_id rows whose space_id is in {S1, S2} —
    that's how glossary / metrics / per-space customisations show
    up in the user's aggregated Personal view, per Lucas's
    Personal-aggregates-from-Spaces design."""
    me = uuid4()
    conn = uuid4()
    s1, s2 = uuid4(), uuid4()
    sql = _compile(
        _build_embedding_base_query(
            space_id=str(uuid4()),
            crew_ids=[],
            connection_id=str(conn),
            is_personal=True,
            user_id=me,
            caller_space_ids=[str(s1), str(s2)],
        )
    )
    # All three branches must be present:
    assert f"embeddings.user_id = '{me}'" in sql              # branch 1
    assert "embeddings.user_id IS NULL" in sql                # branches 2 + 3
    assert "embeddings.space_id IS NULL" in sql               # branch 2
    # branch 3: space_id IN (s1, s2)
    assert f"'{s1}'" in sql
    assert f"'{s2}'" in sql


def test_personal_mode_does_not_leak_other_spaces_scoped_content():
    """Adversarial review 2026-05-05: when the same connection is
    bridged to multiple spaces of one tenant, a Personal-mode
    caller (member of S1 only) must not see content stamped to S2
    via that connection. The fence is `(user_id IS NULL AND
    space_id IS NULL)` — strictly connection-level shared rows,
    nothing space-scoped."""
    me = uuid4()
    conn = uuid4()
    sql = _compile(
        _build_embedding_base_query(
            space_id=str(uuid4()),
            crew_ids=[],
            connection_id=str(conn),
            is_personal=True,
            user_id=me,
        )
    )
    # The pair must be present.
    assert "embeddings.user_id IS NULL" in sql
    assert "embeddings.space_id IS NULL" in sql
    # Crucially, there must NOT be a bare "user_id IS NULL" in an
    # OR with the connection filter only — that would be the leaky
    # version. We assert the AND coupling by checking both NULL
    # conditions are required together. (Structural: both IS NULL
    # tokens appear inside the same ANDed clause; the leaky version
    # would have user_id IS NULL without any space_id IS NULL.)
    null_idx = sql.find("embeddings.user_id IS NULL")
    space_null_idx = sql.find("embeddings.space_id IS NULL")
    assert null_idx >= 0 and space_null_idx >= 0
    # The two NULL conditions must appear close together (paired in
    # AND), not far apart (which would suggest separate clauses).
    assert abs(null_idx - space_null_idx) < 200, (
        "user_id IS NULL and space_id IS NULL must be ANDed together"
    )


def test_personal_mode_without_connection_stays_strict():
    """Without a connection_id we keep the legacy strict filter
    (only this user's own items). The OR-NULL relaxation only
    applies when an authorised connection scopes the result, so
    listing Personal items in the absence of a connection still
    can't surface another user's stuff or unscoped shared rows."""
    user_a = uuid4()
    q = _build_embedding_base_query(
        space_id=uuid4(),
        crew_ids=[],
        connection_id=None,
        is_personal=True,
        user_id=user_a,
    )
    sql = _compile(q)
    assert f"embeddings.user_id = '{user_a}'" in sql
    # NULL acceptance must NOT be in the WHERE for the no-connection
    # case — otherwise listing personal items would surface shared
    # connection rows that don't belong here.
    assert "embeddings.user_id IS NULL" not in sql


def test_personal_with_connection_does_not_leak_other_users_personal():
    """Defence-in-depth: in the OR-NULL personal branch, another
    user's Personal item (with their own user_id stamped) must NOT
    leak. The fence is the connection_id JOIN — embeddings tied to
    a TableMetadata of a different connection don't pass."""
    me = uuid4()
    my_conn = uuid4()
    sql = _compile(
        _build_embedding_base_query(
            space_id=uuid4(),
            crew_ids=[],
            connection_id=my_conn,
            is_personal=True,
            user_id=me,
        )
    )
    # The query never references another user's id at compile time
    # (would only show up via runtime data) — the structural
    # invariant we can pin is: only the caller's id and IS-NULL are
    # accepted on user_id. No `user_id != X` or `user_id IN (...)`.
    assert f"embeddings.user_id = '{me}'" in sql
    # And the connection fence is present.
    assert f"table_metadata.data_connection_id = '{my_conn}'" in sql


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


def test_connection_id_is_the_isolation_fence_not_space_id():
    """Lucas's 2026-05-05 follow-up question: "global indexing won't
    leak across Spaces, right?". The answer is: no, because the
    isolation fence is ``connection_id`` (gated by BE RBAC at the API
    layer), not ``space_id``. This test pins the invariant.

    Concretely: if visitor V1 (Space S1) queries with ``connection_id=A``,
    the rendered WHERE must constrain TableMetadata.data_connection_id
    to A — so embeddings of an unrelated connection B are filtered out
    even if B's rows also have ``space_id IS NULL``.
    """
    s1 = uuid4()
    conn_a = uuid4()
    conn_b_should_not_leak = uuid4()

    sql = _compile(
        _build_embedding_base_query(
            space_id=str(s1),
            crew_ids=[],
            connection_id=str(conn_a),
            is_personal=False,
        )
    )

    # The fence: filter pins to conn_a.
    assert f"table_metadata.data_connection_id = '{conn_a}'" in sql
    # The other connection MUST NOT appear anywhere — no SQL clause
    # would even consider it. (Trivially true here, but locks the
    # invariant: a regression that loosened the connection filter to
    # OR-NULL on data_connection_id would surface as another
    # connection's id leaking via NULL match.)
    assert str(conn_b_should_not_leak) not in sql

    # Symmetric check from V2 in S2 querying conn_b: must NOT see conn_a.
    s2 = uuid4()
    conn_b = uuid4()
    sql_v2 = _compile(
        _build_embedding_base_query(
            space_id=str(s2),
            crew_ids=[],
            connection_id=str(conn_b),
            is_personal=False,
        )
    )
    assert f"table_metadata.data_connection_id = '{conn_b}'" in sql_v2
    assert str(conn_a) not in sql_v2


def test_personal_rows_never_leak_into_space_mode_even_with_null_space():
    """Defence-in-depth: even on the demo's shared (space_id=NULL)
    branch, another visitor's Personal embeddings (where ``user_id``
    is set) must be filtered out by ``user_id IS NULL``. This is the
    invariant that keeps Personal isolated from Space queries."""
    caller_space = uuid4()
    conn = uuid4()
    sql = _compile(
        _build_embedding_base_query(
            space_id=str(caller_space),
            crew_ids=[],
            connection_id=str(conn),
            is_personal=False,
        )
    )
    # Hard assertion: Space/Crew mode strips any embedding with a
    # user_id set, regardless of space_id NULL match.
    assert "embeddings.user_id IS NULL" in sql
