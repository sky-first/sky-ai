"""Tests for the pure helper functions inside ``api.routes.semantic_map``.

The HTTP layer itself is exercised by manual smoke tests + the BE
proxy's full e2e suite. These tests focus on the bits that don't need
a live DB or embedding provider: scope parsing, vector decoding, and
the ``(kind, label, source_id)`` resolution that powers the canvas
labels.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import numpy as np

from api.routes.semantic_map import (
    SemanticMapRequest,
    _infer_kind,
    _label_for,
    _parse_uuid_list,
    _parse_vector,
    _source_id_for,
)


# ─── SemanticMapRequest defaults ────────────────────────────────────


def test_request_defaults_are_sane():
    req = SemanticMapRequest()
    assert req.n_components == 3
    assert req.n_neighbors == 15
    assert 0.0 <= req.min_dist <= 1.0
    assert req.enable_clustering is True
    assert req.limit == 2000
    assert req.user_id is None
    assert req.space_ids == []
    assert req.crew_ids == []


# ─── _parse_uuid_list ───────────────────────────────────────────────


def test_parse_uuid_list_drops_invalid_strings():
    valid = str(uuid4())
    result = _parse_uuid_list([valid, "not-a-uuid", "", "12345"])
    assert len(result) == 1
    assert result[0] == UUID(valid)


def test_parse_uuid_list_empty_input():
    assert _parse_uuid_list([]) == []


# ─── _parse_vector ──────────────────────────────────────────────────


def test_parse_vector_handles_list_input():
    v = _parse_vector([0.1, 0.2, 0.3])
    assert v is not None
    assert v.shape == (3,)
    assert v.dtype == np.float32


def test_parse_vector_handles_pgvector_text_format():
    v = _parse_vector("[0.1,0.2,0.3]")
    assert v is not None
    assert v.shape == (3,)
    np.testing.assert_allclose(v, [0.1, 0.2, 0.3], atol=1e-5)


def test_parse_vector_returns_none_on_garbage():
    assert _parse_vector(None) is None
    assert _parse_vector("") is None
    assert _parse_vector("[]") is None
    assert _parse_vector("not numbers") is None


# ─── _infer_kind / _label_for / _source_id_for ──────────────────────


def _stub(**kwargs):
    """Tiny stand-in for an EmbeddingRecord."""
    defaults = {
        "id": uuid4(),
        "space_id": None,
        "crew_id": None,
        "user_id": None,
        "table_metadata_id": None,
        "document_id": None,
        "embedding": None,
        "text": "",
        "extra_metadata": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_infer_kind_uses_explicit_metadata_kind():
    rec = _stub(extra_metadata={"kind": "metric"})
    assert _infer_kind(rec) == "metric"


def test_infer_kind_falls_back_to_table_for_table_metadata_fk():
    rec = _stub(table_metadata_id=uuid4())
    assert _infer_kind(rec) == "table"


def test_infer_kind_detects_column_from_metadata():
    rec = _stub(table_metadata_id=uuid4(), extra_metadata={"column": "revenue"})
    assert _infer_kind(rec) == "column"


def test_infer_kind_document_when_only_document_id_set():
    rec = _stub(document_id="doc-123")
    assert _infer_kind(rec) == "document"


def test_infer_kind_context_when_nothing_known():
    assert _infer_kind(_stub()) == "context"


def test_label_for_prefers_metadata_label():
    rec = _stub(extra_metadata={"label": "Net Revenue Retention"}, text="long text body")
    assert _label_for(rec) == "Net Revenue Retention"


def test_label_for_falls_back_to_text_truncated():
    rec = _stub(text="A" * 200)
    label = _label_for(rec)
    assert len(label) == 80
    assert label == "A" * 80


def test_label_for_returns_placeholder_when_empty():
    assert _label_for(_stub()) == "(untitled)"


def test_source_id_prefers_table_metadata():
    tmid = uuid4()
    rec = _stub(table_metadata_id=tmid, document_id="doc-1")
    assert _source_id_for(rec) == str(tmid)


def test_source_id_falls_back_to_document_id():
    rec = _stub(document_id="doc-123")
    assert _source_id_for(rec) == "doc-123"


def test_source_id_is_none_when_nothing_anchors():
    assert _source_id_for(_stub()) is None
