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


def _generate_service_token(
    user_id: Optional[str] = None, email: Optional[str] = None
) -> str:
    """Generate a JWT service token for internal AI→Backend calls.

    The user identity is read from env (`AI_SERVICE_USER_ID` /
    `AI_SERVICE_USER_EMAIL`) so installs don't drift when the seeded
    admin UUID changes. The previous hardcoded UUID was silently
    failing auth — every BE call returned 401, the client swallowed
    it, and specialists saw an empty Knowledge catalog.

    Caller can override per-call by passing user_id/email — useful
    when we eventually thread the real chat user's id through.
    """
    import datetime, os

    try:
        import jwt
        from config.settings import settings

        jwt_secret = getattr(settings, "jwt_secret_key", "") or os.environ.get(
            "JWT_SECRET_KEY", ""
        )
        if not jwt_secret:
            logger.warning(
                "No JWT_SECRET_KEY found — backend calls will be unauthenticated"
            )
            return ""
        sub = (
            user_id
            or os.environ.get("AI_SERVICE_USER_ID")
            or getattr(settings, "ai_service_user_id", None)
        )
        if not sub:
            logger.warning(
                "AI_SERVICE_USER_ID not set — backend calls will fall back to a "
                "no-op token and 401 on every request. Set it in sky-poc-ai/.env "
                "to a real user UUID (e.g. an owner of the org)."
            )
            return ""
        mail = (
            email
            or os.environ.get("AI_SERVICE_USER_EMAIL")
            or getattr(settings, "ai_service_user_email", None)
            or ""
        )
        payload = {
            "sub": sub,
            "email": mail,
            "exp": datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=24),
            "iat": datetime.datetime.now(datetime.timezone.utc),
            "type": "access",
        }
        token = jwt.encode(payload, jwt_secret, algorithm="HS256")
        logger.info(f"Service token generated for sub={sub} (len={len(token)})")
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
        # Some endpoints redirect (e.g. /enterprise/relationships/ → /enterprise/relationships).
        # Without follow_redirects the client raises and the call returns []
        # silently — exactly the kind of dead-end the Knowledge specialist
        # was hitting. Keep it on so the client behaves like a real browser.
        self._http = httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            headers=headers,
            follow_redirects=True,
        )

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

    # ── Popular questions (chat bootstrap recommender) ────────

    def get_popular_questions(
        self, limit: int = 5, space_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """GET /ai/popular-questions — anonymised top-asked questions.

        Returns rows like {question, count}, already filtered to recent
        completed queries with mine excluded by the backend. Used by the
        Sherlock bootstrap to surface "people in your space have been
        asking…" cards instead of generic placeholders.
        """
        params: Dict[str, Any] = {"limit": limit}
        if space_id:
            params["space_id"] = space_id
        try:
            r = self._http.get("/ai/popular-questions", params=params)
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.warning(f"BackendClient.get_popular_questions failed: {e}")
            return []

    # ── Knowledge (Metrics + Glossary) ────────────────────────

    def get_metrics(self) -> List[Dict[str, Any]]:
        """GET /metrics/ — Knowledge layer metrics scoped to the caller."""
        try:
            r = self._http.get("/metrics/")
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else data.get("items", [])
        except Exception as e:
            logger.warning(f"BackendClient.get_metrics failed: {e}")
            return []

    def get_glossary(self) -> List[Dict[str, Any]]:
        """GET /glossary/ — Knowledge layer glossary terms scoped to the caller."""
        try:
            r = self._http.get("/glossary/")
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else data.get("items", [])
        except Exception as e:
            logger.warning(f"BackendClient.get_glossary failed: {e}")
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

    def get_ai_history(
        self, space_id: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
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

    def notify_scan_insight(
        self,
        space_id: str,
        title: str,
        summary: str = "",
    ) -> bool:
        """POST /ai/scan-insights/notify — tell the backend a new insight was generated.

        The backend uses this to push a notification to connected users.
        Returns True on success, False on any error (never raises).
        """
        try:
            payload = {"space_id": space_id, "title": title, "summary": summary[:500]}
            r = self._http.post("/ai/scan-insights/notify", json=payload)
            r.raise_for_status()
            return True
        except Exception as exc:
            logger.debug(
                "BackendClient.notify_scan_insight failed (non-critical): %s", exc
            )
            return False

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
