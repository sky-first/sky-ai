"""
HTTP client for calling the sky-poc-backend REST API.

The AI service uses this to fetch strategy, signals, and relationship data
so that multi-agent specialists can answer questions about business context
without generating SQL.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("dataassistant")

_client: Optional["BackendClient"] = None


def _generate_service_token() -> str:
    """Generate a JWT service token for internal AI→Backend calls."""
    import datetime, os
    try:
        import jwt
        # Load JWT secret from settings (which reads from .env JWT_SECRET_KEY)
        from config.settings import settings
        jwt_secret = getattr(settings, "jwt_secret_key", "") or os.environ.get("JWT_SECRET_KEY", "")
        if not jwt_secret:
            logger.warning("No JWT_SECRET_KEY found — backend calls will be unauthenticated")
            return ""
        # Use the actual admin user so the backend's auth middleware accepts it
        payload = {
            "sub": "b11c2d26-d9c8-4676-b96a-6cba2fc446b1",  # admin user
            "email": "lucas.ventura@skyfirstlabs.com",
            "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24),
            "iat": datetime.datetime.now(datetime.timezone.utc),
            "type": "access",
        }
        token = jwt.encode(payload, jwt_secret, algorithm="HS256")
        logger.info(f"Service token generated (len={len(token)})")
        return token
    except Exception as e:
        logger.warning(f"Failed to generate service token: {e}")
        return ""


class BackendClient:
    """Thin HTTP wrapper around the sky-poc-backend API."""

    def __init__(self, base_url: str, timeout: float = 30.0):
        self._base_url = base_url.rstrip("/")
        token = _generate_service_token()
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._http = httpx.Client(base_url=self._base_url, timeout=timeout, headers=headers)

    # ── Strategy ──────────────────────────────────────────────

    def get_strategy_tree(self, space_id: Optional[str] = None) -> Dict[str, Any]:
        """GET /strategy/tree — full hierarchy: pillars, objectives, OKRs, initiatives."""
        params: Dict[str, str] = {}
        if space_id:
            params["space_id"] = space_id
        try:
            r = self._http.get("/strategy/tree", params=params)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"BackendClient.get_strategy_tree failed: {e}")
            return {}

    def get_strategy_health(self, space_id: Optional[str] = None) -> Dict[str, Any]:
        """GET /strategy/health — aggregated health metrics."""
        params: Dict[str, str] = {}
        if space_id:
            params["space_id"] = space_id
        try:
            r = self._http.get("/strategy/health", params=params)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"BackendClient.get_strategy_health failed: {e}")
            return {}

    # ── Signals & Events ──────────────────────────────────────

    def get_signal_events(
        self,
        space_id: Optional[str] = None,
        crew_id: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """GET /signal-events — manual user-created events."""
        params: Dict[str, str] = {}
        if space_id:
            params["space_id"] = space_id
        if crew_id:
            params["crew_id"] = crew_id
        if category:
            params["category"] = category
        try:
            r = self._http.get("/signal-events/", params=params)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"BackendClient.get_signal_events failed: {e}")
            return []

    def get_intelligence_signals(
        self,
        page_id: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """GET /intelligence/signals — AI-generated signals."""
        params: Dict[str, str] = {}
        if page_id:
            params["page_id"] = page_id
        if category:
            params["category"] = category
        try:
            r = self._http.get("/intelligence/signals/", params=params)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"BackendClient.get_intelligence_signals failed: {e}")
            return []

    # ── Enterprise Relationships ──────────────────────────────

    def get_enterprise_relationships(self) -> List[Dict[str, Any]]:
        """GET /enterprise/relationships — cross-space semantic relationships."""
        try:
            r = self._http.get("/enterprise/relationships/")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"BackendClient.get_enterprise_relationships failed: {e}")
            return []

    # ── People, Spaces & Crews ─────────────────────────────

    def get_spaces(self) -> List[Dict[str, Any]]:
        """GET /spaces — all spaces in the organization."""
        try:
            r = self._http.get("/spaces/")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"BackendClient.get_spaces failed: {e}")
            return []

    def get_crews(self, space_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """GET /crews — crews, optionally filtered by space."""
        params: Dict[str, str] = {}
        if space_id:
            params["space_id"] = space_id
        try:
            r = self._http.get("/crews/", params=params)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"BackendClient.get_crews failed: {e}")
            return []

    def get_users(self) -> List[Dict[str, Any]]:
        """GET /users — all users."""
        try:
            r = self._http.get("/users/")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"BackendClient.get_users failed: {e}")
            return []

    # ── Widgets & Dashboards ──────────────────────────────

    def get_dashboards(self, page_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """GET /dashboards — dashboards for a page."""
        params: Dict[str, str] = {}
        if page_id:
            params["page_id"] = page_id
        try:
            r = self._http.get("/dashboards/", params=params)
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else data.get("items", [])
        except Exception as e:
            logger.warning(f"BackendClient.get_dashboards failed: {e}")
            return []

    def get_widgets(self, dashboard_id: str) -> List[Dict[str, Any]]:
        """GET /dashboards/{id}/widgets — widgets on a dashboard."""
        try:
            r = self._http.get(f"/dashboards/{dashboard_id}/widgets")
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"BackendClient.get_widgets failed: {e}")
            return []

    # ── AI History ────────────────────────────────────────

    def get_ai_history(self, space_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """GET /ai/history — past questions and answers."""
        params: Dict[str, Any] = {"limit": limit}
        if space_id:
            params["space_id"] = space_id
        try:
            r = self._http.get("/ai/history", params=params)
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else data.get("items", [])
        except Exception as e:
            logger.warning(f"BackendClient.get_ai_history failed: {e}")
            return []

    def close(self):
        self._http.close()


def get_backend_client() -> BackendClient:
    """Singleton factory — lazily creates the client from settings."""
    global _client
    if _client is None:
        from config.settings import settings
        _client = BackendClient(base_url=settings.backend_url)
        logger.info(f"BackendClient initialized: {settings.backend_url}")
    return _client


def reset_backend_client():
    """Reset the singleton (useful after config changes or in tests)."""
    global _client
    if _client:
        _client.close()
    _client = None
