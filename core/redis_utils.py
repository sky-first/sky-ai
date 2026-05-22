# core/redis_utils.py
"""Shared Redis client factory.

redis-py's ``from_url()`` reads ``ssl_cert_reqs`` from the URL query string
as a plain string (e.g. ``"CERT_REQUIRED"``), but the underlying ssl module
expects the enum value ``ssl.CERT_REQUIRED`` (int 2).  Managed Redis services
(ElastiCache, Upstash) routinely embed this parameter in the connection URL,
which causes every ``rediss://`` client to raise:
    "Invalid SSL Certificate Requirements Flag: CERT_REQUIRED"

This module provides ``make_redis_client()`` which strips the problematic
query param from the URL and re-injects it as the correct Python enum so
every caller gets a working SSL connection without duplicating the workaround.
"""
from __future__ import annotations

import ssl
import logging
from typing import Optional
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

logger = logging.getLogger(__name__)

_CERT_MAP: dict[str, int] = {
    "CERT_NONE": ssl.CERT_NONE,
    "CERT_OPTIONAL": ssl.CERT_OPTIONAL,
    "CERT_REQUIRED": ssl.CERT_REQUIRED,
}


def _strip_ssl_cert_reqs(url: str) -> tuple[str, Optional[int]]:
    """Remove ``ssl_cert_reqs`` from the URL query string and return it
    as the proper ``ssl`` enum integer (or ``None`` if absent)."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)

    cert_reqs: Optional[int] = None
    if "ssl_cert_reqs" in params:
        raw = params.pop("ssl_cert_reqs")[0]
        # Already an integer string?
        try:
            cert_reqs = int(raw)
        except ValueError:
            cert_reqs = _CERT_MAP.get(raw.upper())
            if cert_reqs is None:
                logger.warning(
                    "Unknown ssl_cert_reqs value %r — defaulting to CERT_REQUIRED", raw
                )
                cert_reqs = ssl.CERT_REQUIRED

    clean_query = urlencode(params, doseq=True)
    clean_url = urlunparse(parsed._replace(query=clean_query))
    return clean_url, cert_reqs


def make_redis_client(
    url: str,
    *,
    decode_responses: bool = True,
    socket_connect_timeout: int = 2,
    socket_timeout: int = 2,
):
    """Return a connected ``redis.Redis`` client.

    Handles the ``ssl_cert_reqs`` string-vs-enum mismatch transparently.
    Raises the original exception if the connection fails so callers can
    fall back gracefully.
    """
    import redis

    clean_url, cert_reqs = _strip_ssl_cert_reqs(url)

    kwargs: dict = {
        "decode_responses": decode_responses,
        "socket_connect_timeout": socket_connect_timeout,
        "socket_timeout": socket_timeout,
    }

    is_ssl = clean_url.startswith("rediss://")
    if is_ssl:
        # Inject the enum value redis-py actually accepts.
        kwargs["ssl_cert_reqs"] = (
            cert_reqs if cert_reqs is not None else ssl.CERT_REQUIRED
        )

    client = redis.from_url(clean_url, **kwargs)
    client.ping()
    return client
