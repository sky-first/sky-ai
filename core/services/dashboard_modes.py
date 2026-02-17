
from typing import Dict, List, Any

MODE_CONFIG: Dict[str, Dict[str, Any]] = {
    "textual": {
        "max_charts": 2,
        "min_charts": 1,
        "include_sections": ["verdict", "descriptive", "diagnostic", "predictive", "prescriptive"],
        "max_text": {
            "verdict": 300,
            "diagnostic": 800,
            "predictive": 500,
            "prescriptive": 500
        },
        "llm": {
            "max_tokens": 1500,
            "temperature": 0.1
        },
        "description": "Unified Insight Widget: A complete narrative report with embedded metrics and essential charts."
    },
    "visual": {
        "max_charts": 8,
        "min_charts": 3,
        "include_sections": ["verdict", "descriptive"],
        "max_text": {
            "verdict": 150,
            "diagnostic": 200
        },
        "llm": {
            "max_tokens": 1200,
            "temperature": 0.1
        },
        "description": "Chart-heavy dashboard with minimal text."
    },
    "mix": {
        "max_charts": 6,
        "min_charts": 2,
        "include_sections": ["verdict", "descriptive", "diagnostic", "predictive", "prescriptive"],
        "max_text": {
            "verdict": 200,
            "diagnostic": 500,
            "predictive": 300,
            "prescriptive": 300
        },
        "llm": {
            "max_tokens": 1500,
            "temperature": 0.1
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
