# core/i18n/i18n.py
from __future__ import annotations

from typing import Dict, List, Any
import logging

# Centralized messages dictionary - ENGLISH ONLY
MESSAGES: Dict[str, Dict[str, str]] = {
    "SECURITY_BLOCKED": {
        "en": "I can't help with that request. Please rephrase your question about your data or contact an administrator."
    },
    "PII_BLOCKED": {
        "en": "I cannot process sensitive personal information. Please rephrase your question without including personal data."
    },
    "TECHNICAL_ERROR": {
        "en": "There was a technical error while querying the database."
    },
    "NO_DATA_FOUND": {
        "en": "Sorry, I couldn't find any data about {topic}. Please try rephrasing."
    },
    "NO_DATA_GENERIC": {
        "en": "Sorry, I couldn't find any data to answer this question. Please try rephrasing."
    }
}


def get_message(key: str, lang: str = "en", **kwargs: Any) -> str:
    """
    Returns a translated and formatted message.
    ALWAYS returns English, ignoring the 'lang' parameter.
    """
    # Force English
    lang = "en"
    
    # Get message
    msg_dict = MESSAGES.get(key, MESSAGES.get("TECHNICAL_ERROR"))
    msg = msg_dict.get("en", "An unexpected error occurred.")
    
    # Format if kwargs exist
    if kwargs:
        try:
            return msg.format(**kwargs)
        except Exception:
            return msg
    
    return msg


logger = logging.getLogger("dataassistant.i18n")


def detect_language(text: str) -> str:
    """
    Detects language of user text.
    ALWAYS returns 'en' as per strict project requirement.
    """
    return "en"
