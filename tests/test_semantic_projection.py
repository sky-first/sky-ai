"""Tests for ``core.rag.semantic_projection``.

These cover the pure numpy helpers that the FastAPI route depends on.
They run without a database, without an HTTP layer, and without the
LLM/embedding provider — fast enough to be a tight feedback loop while
iterating on UMAP/HDBSCAN parameters.
"""

from __future__ import annotations

import numpy as np
import pytest

from core.rag.semantic_projection import (
    ClusterParams,
    ProjectionParams,
    cluster_centroids,
    cluster_points,
    project_to_low_dim,
)

# ─── project_to_low_dim ──────────────────────────────────────────────


def test_project_to_low_dim_returns_correct_shape_for_50_points():
    rng = np.random.RandomState(0)
    v = rng.randn(50, 768).astype(np.float32)
    out = project_to_low_dim(v)
    assert out.shape == (50, 3)


def test_project_to_low_dim_returns_2d_when_requested():
    rng = np.random.RandomState(0)
    v = rng.randn(50, 768).astype(np.float32)
    out = project_to_low_dim(v, ProjectionParams(n_components=2))
    assert out.shape == (50, 2)


def test_project_to_low_dim_is_deterministic_with_seed():
    rng = np.random.RandomState(0)
    v = rng.randn(40, 64).astype(np.float32)
    a = project_to_low_dim(v)
    b = project_to_low_dim(v)
    np.testing.assert_allclose(a, b, atol=1e-5)


def test_project_to_low_dim_handles_empty_input():
    v = np.zeros((0, 768), dtype=np.float32)
    out = project_to_low_dim(v)
    assert out.shape == (0, 3)


def test_project_to_low_dim_tiny_input_uses_fallback():
    # N=3 < 5 → fallback path (mean-center + std-scale). No UMAP import
    # gets triggered, so this test passes even if umap-learn isn't
    # available in the env.
    v = np.array(
        [
            [1.0, 2.0, 3.0, 4.0, 5.0],
            [2.0, 4.0, 6.0, 8.0, 10.0],
            [3.0, 6.0, 9.0, 12.0, 15.0],
        ],
        dtype=np.float32,
    )
    out = project_to_low_dim(v, ProjectionParams(n_components=3))
    assert out.shape == (3, 3)
    # Mean-centred → each column sums to ~0.
    assert np.allclose(out.mean(axis=0), 0.0, atol=1e-5)


def test_project_to_low_dim_rejects_non_2d_input():
    v = np.zeros((10, 5, 3), dtype=np.float32)
    with pytest.raises(ValueError, match="2D"):
        project_to_low_dim(v)


def test_project_to_low_dim_clamps_n_neighbors_to_n_minus_1():
    # n_neighbors > n-1 is invalid for UMAP — the helper must clamp.
    rng = np.random.RandomState(1)
    v = rng.randn(8, 16).astype(np.float32)
    out = project_to_low_dim(v, ProjectionParams(n_components=2, n_neighbors=50))
    # Doesn't raise; shape is right.
    assert out.shape == (8, 2)


def test_project_to_low_dim_pads_when_umap_returns_fewer_dims():
    # n_components clamped to n-1 inside the helper; the result must
    # still expose the requested column count (zero-padded).
    rng = np.random.RandomState(2)
    v = rng.randn(6, 16).astype(np.float32)
    out = project_to_low_dim(v, ProjectionParams(n_components=3))
    assert out.shape == (6, 3)


def test_project_to_low_dim_replaces_nan_with_zero():
    # Force UMAP to see degenerate input (all zeros) → UMAP can return
    # NaN. The helper must scrub them before returning.
    v = np.zeros((30, 8), dtype=np.float32)
    # Tiny perturbation to keep UMAP from outright crashing.
    v[0, 0] = 1e-12
    out = project_to_low_dim(v, ProjectionParams(n_components=2))
    assert np.isfinite(out).all()


# ─── cluster_points ──────────────────────────────────────────────────


def test_cluster_points_returns_one_label_per_point():
    rng = np.random.RandomState(0)
    coords = rng.randn(40, 3).astype(np.float32)
    labels, n_clusters = cluster_points(coords, ClusterParams(min_cluster_size=4))
    assert labels.shape == (40,)
    assert n_clusters >= 0


def test_cluster_points_emits_minus_one_for_noise():
    # Two clear clusters + a few isolated outliers → outliers get -1.
    rng = np.random.RandomState(0)
    cluster_a = rng.randn(20, 3) + np.array([10.0, 10.0, 10.0])
    cluster_b = rng.randn(20, 3) + np.array([-10.0, -10.0, -10.0])
    outliers = np.array([[100.0, 100.0, 100.0], [-100.0, 0.0, 0.0]])
    coords = np.vstack([cluster_a, cluster_b, outliers]).astype(np.float32)
    labels, _ = cluster_points(coords, ClusterParams(min_cluster_size=5))
    # The two outliers should not land in any HDBSCAN cluster.
    assert (labels == -1).any()


def test_cluster_points_returns_zero_clusters_for_tiny_input():
    rng = np.random.RandomState(0)
    coords = rng.randn(3, 3).astype(np.float32)
    labels, n_clusters = cluster_points(coords, ClusterParams(min_cluster_size=5))
    assert n_clusters == 0
    assert (labels == -1).all()


def test_cluster_points_empty_input():
    coords = np.zeros((0, 3), dtype=np.float32)
    labels, n_clusters = cluster_points(coords)
    assert labels.shape == (0,)
    assert n_clusters == 0


# ─── cluster_centroids ───────────────────────────────────────────────


def test_cluster_centroids_geometric_mean_per_cluster():
    coords = np.array(
        [
            [0.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
            [10.0, 10.0, 10.0],
            [12.0, 10.0, 10.0],
        ],
        dtype=np.float32,
    )
    labels = np.array([0, 0, 1, 1], dtype=np.int32)
    out = cluster_centroids(coords, labels)
    assert out.shape == (2, 3)
    np.testing.assert_allclose(out[0], [1.0, 0.0, 0.0])
    np.testing.assert_allclose(out[1], [11.0, 10.0, 10.0])


def test_cluster_centroids_skips_noise_points():
    coords = np.array(
        [
            [0.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
            [100.0, 100.0, 100.0],  # noise — should be excluded
        ],
        dtype=np.float32,
    )
    labels = np.array([0, 0, -1], dtype=np.int32)
    out = cluster_centroids(coords, labels)
    assert out.shape == (1, 3)
    np.testing.assert_allclose(out[0], [1.0, 0.0, 0.0])


def test_cluster_centroids_returns_empty_when_all_noise():
    coords = np.array([[1.0, 2.0, 3.0]], dtype=np.float32)
    labels = np.array([-1], dtype=np.int32)
    out = cluster_centroids(coords, labels)
    assert out.shape == (0, 3)


# ─── Integration: projection + clustering pipeline ────────────────────


def test_full_pipeline_50_random_embeddings_yields_clusters():
    # Two well-separated clouds in 768-D space → UMAP should pull them
    # apart in 3-D and HDBSCAN should label them.
    rng = np.random.RandomState(7)
    a = rng.randn(25, 768) + np.array([5.0] + [0.0] * 767)
    b = rng.randn(25, 768) + np.array([-5.0] + [0.0] * 767)
    v = np.vstack([a, b]).astype(np.float32)
    coords = project_to_low_dim(v)
    labels, n_clusters = cluster_points(coords, ClusterParams(min_cluster_size=5))
    assert coords.shape == (50, 3)
    assert n_clusters >= 1


def test_full_pipeline_returns_finite_coordinates():
    rng = np.random.RandomState(7)
    v = rng.randn(30, 64).astype(np.float32)
    coords = project_to_low_dim(v)
    assert np.isfinite(coords).all()
