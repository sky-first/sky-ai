from typing import Dict, Tuple, Optional
from core.contracts.analysis_context import AnalysisContext
from core.logging_utils import log_event


class AnalysisSessionStore:
    """
    In-memory store for AnalysisContexts, keyed by (user_id, connection_id).
    This acts as the short-term memory bridge between Chat interactions and Dashboard generation.
    """

    # Storage structure: {(user_id, connection_id): AnalysisContext}
    _store: Dict[Tuple[str, str], AnalysisContext] = {}

    @classmethod
    def save(cls, user_id: str, connection_id: str, context: AnalysisContext):
        """
        Saves the analysis context for a specific user and connection scope.
        """
        key = (user_id, connection_id)
        cls._store[key] = context
        log_event(
            "analysis_context_saved",
            {
                "user_id": user_id,
                "connection_id": connection_id,
                "context_version": context.version,
            },
        )

    @classmethod
    def get(cls, user_id: str, connection_id: str) -> Optional[AnalysisContext]:
        """
        Retrieves the analysis context. Returns None if not found.
        """
        key = (user_id, connection_id)
        return cls._store.get(key)

    @classmethod
    def clear(cls, user_id: str, connection_id: str):
        """
        Clears the context after consumption (optional, depending on UX flow).
        """
        key = (user_id, connection_id)
        if key in cls._store:
            del cls._store[key]
