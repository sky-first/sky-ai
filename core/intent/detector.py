"""
Dashboard Intent Detection Module

Detects when user wants direct dashboard generation vs normal query response.
English-only, semantic pattern matching.
"""
from __future__ import annotations
import re
from typing import List, Tuple


class DashboardIntentDetector:
    """
    Detects dashboard generation intent from user questions.
    
    Uses semantic patterns (not just keywords) to identify when user wants
    a structured visual analytics output rather than a text answer.
    """
    
    def __init__(self):
        # Positive patterns: user wants dashboard
        self.dashboard_request_patterns = [
            # Direct creation requests (allow optional content between verb and dashboard)
            r'\b(create|build|generate|make|design)\s+(?:me\s+)?(?:a|an)?\s*\w*\s*dashboard',
            r'\bdashboard\s+(for|about|of|with|showing)',
            
            # Need/want expressions
            r'\b(need|want|would like)\s+(?:a|an)?\s*dashboard',
            r'\b(show|give)\s+me\s+(?:a|an)?\s*dashboard',
            
            # Visual analytics requests
            r'\bvisual\s+(overview|analytics|analysis)',
            r'\bKPI\s+dashboard',
            r'\banalytics\s+dashboard',
            
            # "I need X" patterns where X is dashboard-related
            r'\bneed\s+(?:a|an)?\s*(visual|analytics|KPI)',
            
            # Chart/visual requests that imply dashboard
            r'\b(show|display)\s+.*\s+in\s+(?:a|an)?\s*dashboard',
        ]
        
        # Negative patterns: NOT dashboard generation (false positives to avoid)
        self.not_dashboard_patterns = [
            # Questions about existing dashboards
            r"what'?s\s+(on|in)\s+(my|the)\s+dashboard",
            r'\bmy\s+dashboard\s+(is|shows|displays|has)',
            r'\bthe\s+dashboard\s+(is|shows|displays)',
            
            # Dashboard state/issues
            r'\bdashboard\s+(?:is\s+)?(empty|broken|slow|loading)',
            r'\bdashboard\s+(error|issue|problem)',
            
            # Navigation/UI questions
            r'\b(where|how)\s+.*dashboard',
            r'\b(open|close|view)\s+.*dashboard',
        ]
        
        # Compile all patterns for performance
        self.positive_regex = [re.compile(p, re.IGNORECASE) for p in self.dashboard_request_patterns]
        self.negative_regex = [re.compile(p, re.IGNORECASE) for p in self.not_dashboard_patterns]
    
    def detect(self, question: str) -> bool:
        """
        Returns True if user wants dashboard generation.
        
        Args:
            question: User's input question (English)
            
        Returns:
            True if dashboard generation intent detected
        """
        if not question or not question.strip():
            return False
        
        # Normalize text
        normalized = self._normalize(question)
        
        # Check for explicit rejections first (higher priority)
        if self._matches_negative_patterns(normalized):
            return False
        
        # Check for positive dashboard patterns
        return self._matches_positive_patterns(normalized)
    
    def _normalize(self, text: str) -> str:
        """
        Normalize text for pattern matching.
        
        - Lowercase
        - Strip extra whitespace
        - Remove special punctuation (but keep essential ones)
        """
        # Lowercase
        text = text.lower()
        
        # Remove multiple spaces
        text = re.sub(r'\s+', ' ', text)
        
        # Strip
        text = text.strip()
        
        return text
    
    def _matches_positive_patterns(self, normalized: str) -> bool:
        """Check if text matches any positive dashboard pattern"""
        for pattern in self.positive_regex:
            if pattern.search(normalized):
                return True
        return False
    
    def _matches_negative_patterns(self, normalized: str) -> bool:
        """Check if text matches any negative (rejection) pattern"""
        for pattern in self.negative_regex:
            if pattern.search(normalized):
                return True
        return False
    
    def get_matched_patterns(self, question: str) -> Tuple[List[str], List[str]]:
        """
        Debug helper: returns which patterns matched.
        
        Returns:
            (positive_matches, negative_matches)
        """
        normalized = self._normalize(question)
        
        positive = []
        for i, pattern in enumerate(self.positive_regex):
            if pattern.search(normalized):
                positive.append(self.dashboard_request_patterns[i])
        
        negative = []
        for i, pattern in enumerate(self.negative_regex):
            if pattern.search(normalized):
                negative.append(self.not_dashboard_patterns[i])
        
        return (positive, negative)
