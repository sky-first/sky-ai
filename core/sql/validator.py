# core/sql/validator.py
from __future__ import annotations

from typing import Tuple, Optional
import re

# Pode depois puxar de core/constants.py
MAX_SQL_LENGTH = 10_000


def validate_sql_strict(sql: str) -> Tuple[bool, Optional[str]]:
    """
    Validação estrita de SQL para prevenir SQL injection.
    - Obriga começar com SELECT
    - Bloqueia comandos DDL/DML perigosos
    - Impede múltiplas queries no mesmo SQL
    """
    if not sql or not isinstance(sql, str):
        return False, "Invalid SQL."

    sql_clean = sql.strip()

    if len(sql_clean) == 0:
        return False, "SQL cannot be empty."

    if len(sql_clean) > MAX_SQL_LENGTH:
        return False, f"SQL too long. Maximum of {MAX_SQL_LENGTH} characters."

    lower = sql_clean.lower()

    if not lower.startswith("select") and not lower.startswith("with"):
        return False, "🚫 Only SELECT queries are allowed."

    # Só uma query por vez
    if sql_clean.count(";") > 1 or (sql_clean.count(";") == 1 and not sql_clean.rstrip().endswith(";")):
        return False, "🚫 Only one SELECT query at a time is allowed."

    forbidden_keywords = [
        "insert", "update", "delete", "drop", "create",
        "alter", "truncate", "merge", "exec", "execute",
        "grant", "revoke", "commit", "rollback"
    ]

    for keyword in forbidden_keywords:
        pattern = rf'\b{re.escape(keyword)}\b'
        if re.search(pattern, lower):
            return False, f"🚫 Command '{keyword.upper()}' is not allowed."

    injection_patterns = [
        # r'--',  <-- REMOVED: Allow comments for better SQL explanation
        r'/\*',
        r'union\s+select',
        r'or\s+1\s*=\s*1',
        r';.*drop',
    ]

    for pattern in injection_patterns:
        if re.search(pattern, lower, re.IGNORECASE):
            return False, "🚫 SQL contains suspicious security patterns."

    return True, None


def ensure_safe_select(sql: str) -> Optional[str]:
    """
    Convenience: retorna mensagem de erro se for inseguro, ou None se estiver ok.
    """
    is_valid, error_msg = validate_sql_strict(sql)
    if not is_valid:
        return error_msg
    return None
