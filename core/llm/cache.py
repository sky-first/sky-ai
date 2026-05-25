"""
Inference Cache for CPU-Optimized LLM

Caches LLM responses to avoid expensive re-inference on CPU.
Critical for sqlcoder:7b which takes 8-12 seconds per query.

Cache Strategy:
- Key: Hash of (messages + model + temperature)
- TTL: 30 minutes (configurable)
- Storage: In-memory (can be migrated to Redis later)
- Eviction: LRU when max size reached
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Optional, Dict, Tuple
from collections import OrderedDict

from core.logging_utils import log_event
from config.settings import settings


class InferenceCache:
    """
    LRU cache for LLM inference results.

    Optimized for CPU models where inference is expensive (8-12s).
    Each cache hit saves significant latency.
    """

    def __init__(
        self, max_size: int = 1000, ttl_seconds: int = 1800  # 30 minutes default
    ):
        """
        Initialize inference cache.

        Args:
            max_size: Maximum number of cached responses
            ttl_seconds: Time-to-live for cached entries
        """
        self._cache: OrderedDict[str, Tuple[Any, float]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._hits = 0
        self._misses = 0

    def get(self, prompt_hash: str) -> Optional[Any]:
        """
        Retrieve cached response if still valid.

        Args:
            prompt_hash: Hash of the prompt

        Returns:
            Cached response or None if not found/expired
        """
        if prompt_hash not in self._cache:
            self._misses += 1
            return None

        response, timestamp = self._cache[prompt_hash]

        # Check TTL
        if time.time() - timestamp > self._ttl:
            # Expired - remove
            del self._cache[prompt_hash]
            self._misses += 1
            log_event(
                "inference_cache_expired",
                {"hash": prompt_hash[:8], "age_seconds": int(time.time() - timestamp)},
            )
            return None

        # Move to end (LRU)
        self._cache.move_to_end(prompt_hash)
        self._hits += 1

        log_event(
            "inference_cache_hit",
            {
                "hash": prompt_hash[:8],
                "hit_rate": self.hit_rate(),
                "latency_saved": (
                    "8-12s" if "sql" in str(response).lower()[:100] else "1-2s"
                ),
            },
        )

        return response

    def set(self, prompt_hash: str, response: Any):
        """
        Cache a response.

        Args:
            prompt_hash: Hash of the prompt
            response: Response to cache
        """
        # Evict oldest if at capacity
        if len(self._cache) >= self._max_size:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
            log_event(
                "inference_cache_evicted",
                {"evicted_hash": oldest_key[:8], "cache_size": len(self._cache)},
            )

        self._cache[prompt_hash] = (response, time.time())

        log_event(
            "inference_cache_set",
            {
                "hash": prompt_hash[:8],
                "cache_size": len(self._cache),
                "max_size": self._max_size,
            },
        )

    def clear(self):
        """Clear all cached entries."""
        self._cache.clear()
        self._hits = 0
        self._misses = 0
        log_event("inference_cache_cleared", {})

    def hit_rate(self) -> float:
        """
        Calculate cache hit rate.

        Returns:
            Hit rate as percentage (0-100)
        """
        total = self._hits + self._misses
        if total == 0:
            return 0.0
        return (self._hits / total) * 100

    def stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache stats
        """
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate_pct": round(self.hit_rate(), 2),
            "ttl_seconds": self._ttl,
        }


def hash_prompt(
    messages: list, model: str = "", temperature: float = 0.0, extra_context: str = ""
) -> str:
    """
    Generate hash for prompt caching.

    Args:
        messages: List of message dicts
        model: Model name
        temperature: Temperature setting
        extra_context: Additional context to include in hash

    Returns:
        MD5 hash of the prompt
    """
    # Serialize messages to string
    messages_str = str(messages)

    # Include model and temperature in hash
    hash_input = f"{messages_str}|{model}|{temperature}|{extra_context}"

    # MD5 is fast and sufficient for cache keys (not cryptographic use)
    return hashlib.md5(hash_input.encode()).hexdigest()


# Global cache instance
_global_cache: Optional[InferenceCache] = None


def get_inference_cache() -> InferenceCache:
    """
    Get global inference cache instance.

    Lazy initialization with settings.

    Returns:
        Global InferenceCache instance
    """
    global _global_cache

    if _global_cache is None:
        # Initialize from settings
        cache_enabled = getattr(settings, "enable_inference_cache", True)
        max_size = getattr(settings, "inference_cache_max_size", 1000)
        ttl = getattr(settings, "inference_cache_ttl_seconds", 1800)

        if cache_enabled:
            _global_cache = InferenceCache(max_size=max_size, ttl_seconds=ttl)
            log_event(
                "inference_cache_initialized",
                {"max_size": max_size, "ttl_seconds": ttl},
            )
        else:
            # Disabled cache (always miss)
            _global_cache = _NullCache()
            log_event("inference_cache_disabled", {})

    return _global_cache


class _NullCache:
    """Null object pattern for disabled cache."""

    def get(self, prompt_hash: str) -> None:
        return None

    def set(self, prompt_hash: str, response: Any):
        pass

    def clear(self):
        pass

    def hit_rate(self) -> float:
        return 0.0

    def stats(self) -> Dict[str, Any]:
        return {"enabled": False}
