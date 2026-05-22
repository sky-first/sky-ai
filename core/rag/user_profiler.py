# core/rag/user_profiler.py
"""
User Query Profiling Module.

Analyzes user query history to identify frequently accessed tables
and injects this as context for better table selection.
"""

from __future__ import annotations

from typing import Dict, List, Optional
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from core.logging_utils import log_event


def get_user_table_profile(
    db: Session,
    user_id: str,
    space_id: Optional[str] = None,
    days: int = 30,
    limit: int = 10,
) -> Dict[str, int]:
    """
    Get a user's table usage profile from query audit logs.

    Args:
        db: Database session
        user_id: User ID to profile
        space_id: Optional space ID to filter by
        days: Number of days to look back (default: 30)
        limit: Maximum number of tables to return (default: 10)

    Returns:
        Dict mapping table names to usage counts, e.g.:
        {"invoices": 25, "payments": 10, "customers": 5}
    """
    if not user_id:
        return {}

    try:
        # Build query to aggregate chosen_tables from audit log
        # Uses UNNEST to expand the array and count occurrences
        query = text("""
            SELECT 
                unnest(chosen_tables) AS table_name, 
                COUNT(*) AS usage_count
            FROM query_audit_log
            WHERE 
                user_id = :user_id 
                AND timestamp > NOW() - INTERVAL ':days days'
                AND chosen_tables IS NOT NULL
                AND array_length(chosen_tables, 1) > 0
                AND (:space_id IS NULL OR space_id = CAST(:space_id AS uuid))
            GROUP BY table_name
            ORDER BY usage_count DESC
            LIMIT :limit
        """)

        result = db.execute(
            query,
            {
                "user_id": user_id,
                "space_id": space_id,
                "days": days,
                "limit": limit,
            },
        )

        profile = {}
        for row in result:
            profile[row.table_name] = row.usage_count

        log_event(
            "user_profiler_loaded",
            {
                "user_id": user_id,
                "space_id": space_id,
                "num_tables": len(profile),
                "top_table": list(profile.keys())[0] if profile else None,
            },
        )

        return profile

    except Exception as e:
        log_event(
            "user_profiler_error",
            {
                "user_id": user_id,
                "error": str(e)[:300],
            },
        )
        return {}


def format_profile_for_prompt(
    profile: Dict[str, int],
    max_tables: int = 5,
) -> str:
    """
    Format a user's table profile into a prompt-injectable string.

    Args:
        profile: Dict of table names to usage counts
        max_tables: Maximum tables to include in the prompt

    Returns:
        Formatted string for prompt injection, or empty string if no profile.

    Example:
        "USER PREFERENCE PROFILE:
        This user frequently accesses: invoices (25x), payments (10x), customers (5x).
        When the question is ambiguous, prefer these tables as defaults."
    """
    if not profile:
        return ""

    # Sort by usage count (should already be sorted, but ensure)
    sorted_tables = sorted(profile.items(), key=lambda x: x[1], reverse=True)
    top_tables = sorted_tables[:max_tables]

    table_list = ", ".join([f"{name} ({count}x)" for name, count in top_tables])

    return (
        f"\nUSER PREFERENCE PROFILE:\n"
        f"This user frequently accesses: {table_list}.\n"
        f"When the question is ambiguous, prefer these tables as defaults.\n"
    )


def get_user_recent_queries(
    db: Session,
    user_id: str,
    space_id: Optional[str] = None,
    limit: int = 5,
) -> List[Dict[str, str]]:
    """
    Get a user's recent queries for context.

    Args:
        db: Database session
        user_id: User ID
        space_id: Optional space ID filter
        limit: Number of recent queries to return

    Returns:
        List of dicts with question and chosen_tables
    """
    if not user_id:
        return []

    try:
        query = text("""
            SELECT 
                question,
                chosen_tables,
                timestamp
            FROM query_audit_log
            WHERE 
                user_id = :user_id
                AND has_error IS NOT TRUE
                AND (:space_id IS NULL OR space_id = CAST(:space_id AS uuid))
            ORDER BY timestamp DESC
            LIMIT :limit
        """)

        result = db.execute(
            query,
            {
                "user_id": user_id,
                "space_id": space_id,
                "limit": limit,
            },
        )

        return [
            {
                "question": row.question[:100] if row.question else "",
                "tables": row.chosen_tables or [],
            }
            for row in result
        ]

    except Exception as e:
        log_event(
            "user_profiler_recent_queries_error",
            {"user_id": user_id, "error": str(e)[:200]},
        )
        return []
