"""Unit tests for core/rag/knowledge_retrieval.py.

Tests the scope filter logic, boost logic, and citation generation.
No real DB or embedding model — all mocked.

Run:
    pytest tests/test_knowledge_retrieval.py -v
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.schemas import Citation


# ── Helpers ───────────────────────────────────────────────────────────────────

def _chunk(file_id, chunk_index=0, page_number=1, text="some content"):
    c = MagicMock()
    c.file_id = file_id
    c.chunk_index = chunk_index
    c.page_number = page_number
    c.text = text
    c.embedding = [0.1] * 768
    return c


def _file(file_id=None, scope="crew", scope_id=None, original_name="doc.pdf", status="ready"):
    f = MagicMock()
    f.id = file_id or uuid.uuid4()
    f.scope = scope
    f.scope_id = scope_id or uuid.uuid4()
    f.original_name = original_name
    f.status = status
    f.deleted_at = None
    return f


# ══════════════════════════════════════════════════════════════════════════════
# 1. _build_scope_filter logic
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildScopeFilter:

    def test_returns_none_when_no_scope(self):
        from core.rag.knowledge_retrieval import _build_scope_filter
        result = _build_scope_filter(
            user_id=None, space_id=None, crew_ids=[],
            mentioned_file_ids=[], is_personal=False,
        )
        assert result is None

    def test_crew_ids_produces_clause(self):
        from core.rag.knowledge_retrieval import _build_scope_filter
        result = _build_scope_filter(
            user_id=None, space_id=None, crew_ids=[str(uuid.uuid4())],
            mentioned_file_ids=[], is_personal=False,
        )
        assert result is not None

    def test_personal_only_when_is_personal_true(self):
        from core.rag.knowledge_retrieval import _build_scope_filter
        uid = str(uuid.uuid4())
        no_personal = _build_scope_filter(
            user_id=uid, space_id=None, crew_ids=[],
            mentioned_file_ids=[], is_personal=False,
        )
        with_personal = _build_scope_filter(
            user_id=uid, space_id=None, crew_ids=[],
            mentioned_file_ids=[], is_personal=True,
        )
        assert no_personal is None
        assert with_personal is not None


# ══════════════════════════════════════════════════════════════════════════════
# 2. _make_citations
# ══════════════════════════════════════════════════════════════════════════════

class TestMakeCitations:

    def test_returns_citation_per_unique_chunk(self):
        from core.rag.knowledge_retrieval import KnowledgeHit, _make_citations

        fid = uuid.uuid4()
        f = _file(file_id=fid)
        c1 = _chunk(fid, chunk_index=0, text="first chunk")
        c2 = _chunk(fid, chunk_index=1, text="second chunk")

        hits = [
            KnowledgeHit(chunk=c1, file=f, score=0.9),
            KnowledgeHit(chunk=c2, file=f, score=0.8),
        ]
        citations = _make_citations(hits)
        assert len(citations) == 2
        assert all(isinstance(c, Citation) for c in citations)

    def test_deduplicates_same_chunk_keeps_highest_score(self):
        from core.rag.knowledge_retrieval import KnowledgeHit, _make_citations

        fid = uuid.uuid4()
        f = _file(file_id=fid)
        c = _chunk(fid, chunk_index=0)

        hits = [
            KnowledgeHit(chunk=c, file=f, score=0.7),
            KnowledgeHit(chunk=c, file=f, score=0.95),
        ]
        citations = _make_citations(hits)
        assert len(citations) == 1
        assert citations[0].score == 0.95

    def test_score_capped_at_1(self):
        from core.rag.knowledge_retrieval import KnowledgeHit, _make_citations

        fid = uuid.uuid4()
        f = _file(file_id=fid)
        c = _chunk(fid, chunk_index=0)

        # Simulates a 10× boosted score
        hits = [KnowledgeHit(chunk=c, file=f, score=9.5)]
        citations = _make_citations(hits)
        assert citations[0].score <= 1.0

    def test_excerpt_truncated_to_300_chars(self):
        from core.rag.knowledge_retrieval import KnowledgeHit, _make_citations

        fid = uuid.uuid4()
        f = _file(file_id=fid)
        c = _chunk(fid, chunk_index=0, text="x" * 500)

        hits = [KnowledgeHit(chunk=c, file=f, score=0.8)]
        citations = _make_citations(hits)
        assert len(citations[0].excerpt) <= 300


# ══════════════════════════════════════════════════════════════════════════════
# 3. _format_blocks — mentioned files get [REFERENCED BY USER] prefix
# ══════════════════════════════════════════════════════════════════════════════

class TestFormatBlocks:

    def test_mentioned_file_gets_referenced_prefix(self):
        from core.rag.knowledge_retrieval import KnowledgeHit, _format_blocks

        fid = uuid.uuid4()
        f = _file(file_id=fid, original_name="report.pdf")
        c = _chunk(fid, chunk_index=0, text="revenue grew 20%")

        hits = [KnowledgeHit(chunk=c, file=f, score=9.0)]
        blocks = _format_blocks(hits, mentioned_ids=[str(fid)])

        assert blocks[0].startswith("[REFERENCED BY USER]")
        assert "report.pdf" in blocks[0]

    def test_non_mentioned_file_has_no_prefix(self):
        from core.rag.knowledge_retrieval import KnowledgeHit, _format_blocks

        fid = uuid.uuid4()
        f = _file(file_id=fid)
        c = _chunk(fid, chunk_index=0)

        hits = [KnowledgeHit(chunk=c, file=f, score=0.7)]
        blocks = _format_blocks(hits, mentioned_ids=[])

        assert not blocks[0].startswith("[REFERENCED BY USER]")
        assert "[KNOWLEDGE FILE]" in blocks[0]


# ══════════════════════════════════════════════════════════════════════════════
# 4. retrieve_knowledge_context — empty question returns empty result
# ══════════════════════════════════════════════════════════════════════════════

class TestRetrieveKnowledgeContext:

    @pytest.mark.asyncio
    async def test_empty_question_returns_empty(self):
        from core.rag.knowledge_retrieval import retrieve_knowledge_context

        db = AsyncMock()
        provider = AsyncMock()
        blocks, citations = await retrieve_knowledge_context(
            db=db, embedding_provider=provider, question=""
        )
        assert blocks == []
        assert citations == []
        provider.embed_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_embedding_failure_returns_empty(self):
        from core.rag.knowledge_retrieval import retrieve_knowledge_context

        db = AsyncMock()
        provider = AsyncMock()
        provider.embed_async = AsyncMock(side_effect=RuntimeError("model down"))

        blocks, citations = await retrieve_knowledge_context(
            db=db, embedding_provider=provider, question="what is revenue?"
        )
        assert blocks == []
        assert citations == []
