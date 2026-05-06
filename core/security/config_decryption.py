"""Decrypt connection config payloads written by the backend.

The backend (sky-poc-backend) stores ``data_connections.config`` as
``{"__encrypted": "<fernet-token>"}`` using Fernet symmetric
encryption keyed by the ``ENCRYPTION_KEY`` env var. The AI service
receives that same row and needs to read host/port/user/password/dsn
to open the data source — without decrypting first the factory raises
``DataConnection ... do tipo postgres precisa de config.dsn``.

This is a read-only mirror of ``src/utils/encryption.py`` from the
backend. Both services must share the same ``ENCRYPTION_KEY`` value
(provisioned via Azure Key Vault in staging/prod). When the env var
is absent, ``decrypt_config`` returns the input untouched so legacy
plaintext rows still work — failure mode is the same as before this
helper existed.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


def _get_fernet() -> Optional[Fernet]:
    key = os.environ.get("ENCRYPTION_KEY")
    if not key:
        return None
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:
        derived = base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest())
        return Fernet(derived)


def decrypt_config(data: Dict[str, Any]) -> Dict[str, Any]:
    """Decrypt a connection config dict.

    Idempotent: when the dict is already plaintext (no ``__encrypted``
    key) it is returned untouched. Failures (missing key, wrong key,
    corrupted ciphertext) log a warning and return the input as-is —
    the caller will then fail on the downstream factory with a clear
    "needs config.dsn" error, which is preferable to silently leaking
    encrypted state into log payloads.
    """
    if not isinstance(data, dict) or "__encrypted" not in data:
        return data
    f = _get_fernet()
    if not f:
        logger.warning(
            "config_decryption.no_key: encrypted config received but ENCRYPTION_KEY env var is not set"
        )
        return data
    try:
        ciphertext = data["__encrypted"].encode("utf-8")
        plaintext = f.decrypt(ciphertext)
        return json.loads(plaintext)
    except InvalidToken:
        logger.error(
            "config_decryption.invalid_token: ENCRYPTION_KEY does not match the key used to encrypt this config"
        )
        return data
    except Exception as exc:
        logger.error("config_decryption.failed: %s", exc)
        return data
