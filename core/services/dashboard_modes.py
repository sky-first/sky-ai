
from typing import Dict, List, Any

MODE_CONFIG: Dict[str, Dict[str, Any]] = {
    "textual": {
        "max_charts": 3,
        "min_charts": 1,
        "include_sections": ["verdict", "descriptive", "diagnostic", "predictive", "prescriptive"],
        "max_text": {
            "verdict": 200,
            "diagnostic": 600,  # High text allowance
            "predictive": 400,
            "prescriptive": 400,
            "execution": 400
        },
        "llm": {
            "max_tokens": 1200,
            "temperature": 0.2
        },
        "description": "Unified Insight Widget: A complete narrative report with embedded metrics and essential charts."
    },
    "visual": {
        "max_charts": 8,
        "min_charts": 5,
        "include_sections": ["verdict", "descriptive"],
        "max_text": {
            "verdict": 100,
            "diagnostic": 150  # Minimal text
        },
        "llm": {
            "max_tokens": 600,
            "temperature": 0.2
        },
        "description": "Chart-heavy dashboard with minimal text."
    },
    "mix": {
        "max_charts": 6,
        "min_charts": 4,
        "include_sections": ["verdict", "descriptive", "diagnostic", "predictive", "prescriptive", "execution"],
        "max_text": {
            "verdict": 150,
            "diagnostic": 400,
            "predictive": 250,
            "prescriptive": 250,
            "execution": 250
        },
        "llm": {
            "max_tokens": 800,
            "temperature": 0.2
        },
        "description": "Balanced dashboard with insights and visualizations."
    }
}

VALID_MODES = set(MODE_CONFIG.keys())

def validate_mode(mode: str) -> str:
    """Validate and normalize dashboard generation mode"""
    if not mode:
        return "mix"
    mode = mode.lower().strip()
    return mode if mode in VALID_MODES else "mix"
