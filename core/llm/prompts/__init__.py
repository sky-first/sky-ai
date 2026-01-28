"""
Prompt Engineering for CPU-Optimized LLM Agents

This module provides prompt builders optimized for small CPU-based models (7B-8B parameters).

Key principles for CPU models:
- Explicit, structured instructions (no "intuition")
- Bullet-point rules (easier to follow)
- Constrained outputs (reduce hallucination)
- Minimal tokens (respect 4096 context window)
"""

from .orchestrator_prompts import build_orchestrator_prompt
from .specialist_prompts import build_specialist_prompt
from .formatter_prompts import build_formatter_prompt

__all__ = [
    "build_orchestrator_prompt",
    "build_specialist_prompt",
    "build_formatter_prompt",
]
