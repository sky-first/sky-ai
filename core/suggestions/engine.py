# core/suggestions/engine.py

from typing import List, Optional
import random
from core.suggestions.seeds import SUGGESTION_SEEDS, GENERIC_TEMPLATES


class SuggestionEngine:
    """
    Engine to generate smart follow-up suggestions with ZERO LLM cost.
    Uses static seeds (Knowledge Base) simulating historical successful queries.
    """

    @staticmethod
    def get_suggestions(
        tables: List[str], role: str = "user", max_suggestions: int = 3
    ) -> List[str]:
        """
        Get suggestions based on table context and user role.

        Priority Logic:
        1. Look for specific role suggestions for the main table
        2. Look for default suggestions for the main table
        3. Fallback to generic templates
        """
        if not tables:
            return []

        # Focus on the first/main table for now to keep it simple
        main_table = tables[0].lower()

        # Normalize role for lookup
        # Map specific system roles to seed roles
        role_map = {
            "admin": "admin",
            "commander": "commander",
            "navigator": "navigator",
            "explorer": "navigator",  # Explorer sees navigator options
            "guest": "default",
        }
        mapped_role = role_map.get(role, "default")

        candidates = []

        # 1. Try to find table in Knowledge Base
        if main_table in SUGGESTION_SEEDS:
            table_seeds = SUGGESTION_SEEDS[main_table]

            # 1a. Try specific role
            if mapped_role in table_seeds:
                candidates.extend(table_seeds[mapped_role])

            # 1b. Add defaults if we need more variety or didn't find specific ones
            if "default" in table_seeds:
                candidates.extend(table_seeds["default"])

        # 2. If no candidates found (unknown table), use templates
        if not candidates:
            # Generate generic questions
            cleaned_table_name = main_table.replace("_", " ").title()
            candidates = [
                tmpl.format(table=cleaned_table_name) for tmpl in GENERIC_TEMPLATES
            ]

        # 3. Validation & Random Selection
        # Deduplicate while preserving order
        unique_candidates = list(dict.fromkeys(candidates))

        # Shuffle to give variety if called multiple times
        if len(unique_candidates) > max_suggestions:
            return random.sample(unique_candidates, max_suggestions)

        return unique_candidates[:max_suggestions]


# Singleton instance for easy import
suggestion_engine = SuggestionEngine()
