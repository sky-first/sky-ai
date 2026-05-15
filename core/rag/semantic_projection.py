"""Semantic projection helpers — pure numpy logic for the Universe
Intelligence v2 canvas.

Given a (N, D) embedding matrix:
  * ``project_to_low_dim`` reduces it to (N, 2) or (N, 3) via UMAP,
    falling back to a centered/scaled slice for tiny N where UMAP is
    undefined.
  * ``cluster_points`` runs HDBSCAN on the projected coords to surface
    cluster IDs for the FE's zoom-LOD (zoom-out = render centroids,
    zoom-in = render individuals).

Both helpers are deterministic (random_state=42) so the same set of
embeddings always projects to the same coordinates — important so the
constellation doesn't shuffle between page loads.

Keeping these helpers separate from the FastAPI route means the same
code is exercised by pytest without spinning up the HTTP layer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Tuple

import numpy as np

logger = logging.getLogger(__name__)


# Deterministic seed — see module docstring. Don't override casually:
# the FE caches projected coords per-render and a different seed would
# make the universe "flip" between sessions.
RANDOM_SEED = 42


@dataclass
class ProjectionParams:
    n_components: int = 3  # 2 or 3
    n_neighbors: int = 15
    min_dist: float = 0.1
    metric: str = "cosine"


def project_to_low_dim(
    vectors: np.ndarray,
    params: ProjectionParams | None = None,
) -> np.ndarray:
    """Project (N, D) to (N, n_components).

    For ``N < 5`` UMAP is undefined (it needs at least n_neighbors+1
    points and n_neighbors must be ≥ 2). In that case we return a
    centered + scaled slice of the first n_components dimensions —
    enough to render the empty/sparse state cleanly. Callers should
    not depend on this fallback being "semantic" for tiny N.
    """
    if params is None:
        params = ProjectionParams()
    if vectors.ndim != 2:
        raise ValueError(
            f"vectors must be 2D (N, D); got shape {vectors.shape}"
        )
    n, d = vectors.shape
    if n == 0:
        return np.zeros((0, params.n_components), dtype=np.float32)
    if n < 5:
        # Trivial fallback — first n_components dims, mean-centered, std-scaled.
        x = vectors[:, : params.n_components].astype(np.float32, copy=True)
        std = x.std(axis=0, keepdims=True)
        std[std == 0] = 1.0
        return (x - x.mean(axis=0, keepdims=True)) / std

    # UMAP requires n_neighbors <= n-1 and n_components <= n-1. Clamp.
    nn = max(2, min(params.n_neighbors, n - 1))
    nc = max(2, min(params.n_components, n - 1))

    # Local import — UMAP pulls in numba and is heavy to import at module load.
    import umap  # type: ignore[import-not-found]

    reducer = umap.UMAP(
        n_components=nc,
        n_neighbors=nn,
        min_dist=params.min_dist,
        metric=params.metric,
        random_state=RANDOM_SEED,
        # n_jobs=1 forces single-thread for full determinism — the
        # parallel BLAS path can perturb floating point ordering.
        n_jobs=1,
        verbose=False,
    )
    coords = reducer.fit_transform(vectors.astype(np.float32, copy=False))

    # Pad with zeros if caller asked for 3 dims but UMAP gave 2 (small N).
    if coords.shape[1] < params.n_components:
        pad = np.zeros((coords.shape[0], params.n_components - coords.shape[1]))
        coords = np.hstack([coords, pad])

    # UMAP can occasionally produce NaN for isolated points — replace
    # with zeros so the FE doesn't render off-canvas.
    if not np.isfinite(coords).all():
        logger.warning("UMAP produced non-finite coordinates; replacing with 0.")
        coords = np.nan_to_num(coords, nan=0.0, posinf=0.0, neginf=0.0)

    return coords


@dataclass
class ClusterParams:
    min_cluster_size: int = 5
    min_samples: int = 2


def cluster_points(
    coords: np.ndarray,
    params: ClusterParams | None = None,
) -> Tuple[np.ndarray, int]:
    """HDBSCAN cluster labels for projected coords.

    Returns ``(labels, n_clusters)``. Labels are -1 for noise points,
    0..n_clusters-1 for assigned clusters. For tiny inputs (N < 2 *
    min_cluster_size) returns all -1 since clustering is meaningless.
    """
    if params is None:
        params = ClusterParams()
    n = coords.shape[0]
    if n < 2 * params.min_cluster_size:
        return np.full(n, -1, dtype=np.int32), 0
    mcs = max(2, min(params.min_cluster_size, n // 4))
    ms = max(1, min(params.min_samples, mcs - 1))

    # Local import — hdbscan is heavy.
    import hdbscan  # type: ignore[import-not-found]

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=mcs,
        min_samples=ms,
        cluster_selection_epsilon=0.0,
    )
    labels = clusterer.fit_predict(coords).astype(np.int32)
    n_clusters = int(labels.max() + 1) if (labels >= 0).any() else 0
    return labels, n_clusters


def cluster_centroids(
    coords: np.ndarray,
    labels: np.ndarray,
) -> np.ndarray:
    """Compute the geometric centroid of each cluster.

    Returns ``(n_clusters, n_components)``. Noise points (label -1) are
    excluded. The result is indexed by cluster_id (row 0 = cluster 0).
    """
    n_clusters = int(labels.max() + 1) if (labels >= 0).any() else 0
    if n_clusters == 0:
        return np.zeros((0, coords.shape[1]), dtype=np.float32)
    out = np.zeros((n_clusters, coords.shape[1]), dtype=np.float32)
    for cid in range(n_clusters):
        mask = labels == cid
        if mask.any():
            out[cid] = coords[mask].mean(axis=0)
    return out
