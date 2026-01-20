# core/logging_utils.py
from __future__ import annotations

import json
import logging
from typing import Any, Dict

# Configura logging básico (pode ajustar depois)
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)

logger = logging.getLogger("dataassistant")


def _serialize_value(v: Any) -> Any:
    """Tenta serializar para JSON; se não der, converte para string cortada."""
    try:
        json.dumps(v)
        return v
    except (TypeError, ValueError):
        return str(v)[:500]


def log_event(event_type: str, payload: Dict[str, Any] | None = None) -> None:
    """
    Loga um evento em JSON estruturado.
    Ex:
      log_event("api_query_agent", {"agent_id": "billing_default", "user_id": "felipe"})
    """
    try:
        safe_payload: Dict[str, Any] = {}
        if payload:
            for k, v in payload.items():
                safe_payload[k] = _serialize_value(v)

        log_obj = {"event_type": event_type, **safe_payload}
        logger.info(json.dumps(log_obj, ensure_ascii=False))
    except Exception:
        # Nunca deixar logging quebrar o fluxo da aplicação
        logger.exception("Error while logging event")
