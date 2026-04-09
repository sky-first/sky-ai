"""
Context Architecture for LLM Agents

This module provides structured context management for CPU-optimized LLM inference.
Supports multi-layer RAG, token-aware truncation, and provider-agnostic serialization.
"""

from .models import (
    UserContext,
    CrewContext,
    QueryContext,
    DataContext,
    HistoricalContext,
    ContextBundle,
)
from .builder import build_context_bundle
from .serializers import serialize_for_prompt

__all__ = [
    "UserContext",
    "CrewContext",
    "QueryContext",
    "DataContext",
    "HistoricalContext",
    "ContextBundle",
    "build_context_bundle",
    "serialize_for_prompt",
]
