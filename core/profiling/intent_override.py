"""
User Intent Override Logic

Allows explicit user filters to override dataset size constraints.
Example: "failed payments" should allow WHERE status = 'failed' even on TINY datasets.
"""
from __future__ import annotations
from typing import Optional, Dict, List
import re


class IntentOverride:
    """
    Detects explicit user intent for filters in the query goal.
    
    When a user explicitly mentions a filter (e.g., "failed payments", "approved orders"),
    we should honor that filter even if dataset size normally prohibits it.
    
    This prevents over-aggressive safety measures from blocking legitimate queries.
    """
    
    # Patterns that indicate explicit filter intent
    FILTER_INTENT_PATTERNS = [
        # Status-based filters
        r'\b(failed|succeeded|pending|approved|rejected|cancelled|completed|active|inactive)\s+(payments|orders|transactions|requests|items)',
        r'\b(payments|orders|transactions|requests|items)\s+that\s+(failed|succeeded|are\s+pending|were\s+approved)',
        
        # Amount/value filters
        r'\b(high|low|large|small|expensive|cheap)\s+(value|amount|price|cost)',
        r'\b(over|under|above|below|exceeding)\s+\$?\d+',
        
        # Time-based filters (explicit periods)
        r'\b(last|past|recent|latest)\s+\w+',  # Generic: recent/last + any word
        r'\bin\s+(january|february|march|april|may|june|july|august|september|october|november|december)',
        r'\b(in|from)\s+\d{4}',  # Year (in 2024, from 2024)
        r'\bthis\s+(week|month|quarter|year)',
        
        # Category/type filters
        r'\b(type|category|kind|class)\s+of\s+\w+',
        r'\bfor\s+(customers|users|products|regions?)\s+in\s+\w+',
        
        # Explicit WHERE-like language
        r'\bwhere\s+\w+\s+(is|equals?|=)',
        r'\bwith\s+\w+\s+(of|=|equals?)',
    ]
    
    def __init__(self):
        self.compiled_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.FILTER_INTENT_PATTERNS
        ]
    
    def detect_filter_intent(self, goal: str) -> bool:
        """
        Check if the goal contains explicit filter intent.
        
        Args:
            goal: User's goal/question
            
        Returns:
            True if explicit filter detected, False otherwise
        """
        if not goal:
            return False
        
        normalized = goal.lower().strip()
        
        # Check all patterns
        for pattern in self.compiled_patterns:
            if pattern.search(normalized):
                return True
        
        return False
    
    def extract_filter_hints(self, goal: str) -> List[str]:
        """
        Extract specific filter hints from the goal.
        
        Returns list of matched filter patterns for logging/debugging.
        
        Args:
            goal: User's goal/question
            
        Returns:
            List of matched filter pattern descriptions
        """
        if not goal:
            return []
        
        normalized = goal.lower().strip()
        hints = []
        
        for i, pattern in enumerate(self.compiled_patterns):
            match = pattern.search(normalized)
            if match:
                hints.append(f"Pattern {i+1}: '{match.group()}'")
        
        return hints
    
    def should_allow_filters(
        self,
        goal: str,
        dataset_size: str,
        base_constraints: Dict
    ) -> tuple[bool, Optional[str]]:
        """
        Determine if filters should be allowed despite dataset size constraints.
        
        Args:
            goal: User's goal/question
            dataset_size: Size category (tiny/small/medium/large/huge)
            base_constraints: Base constraints from ConstraintGenerator
            
        Returns:
            Tuple of (should_allow, reason)
        """
        # If dataset is medium+ or no constraints, always allow
        if dataset_size in ["medium", "large", "huge"]:
            return (True, "Dataset size permits filters")
        
        # If no base restrictions, allow
        max_filter_complexity = base_constraints.get("max_filter_complexity", 10)
        if max_filter_complexity >= 2:
            return (True, "Base constraints allow filters")
        
        # Check for explicit filter intent
        has_intent = self.detect_filter_intent(goal)
        
        if has_intent:
            hints = self.extract_filter_hints(goal)
            reason = f"User explicit intent detected: {', '.join(hints[:2])}"
            return (True, reason)
        
        # No override, use base constraints
        return (False, "No explicit filter intent detected")
