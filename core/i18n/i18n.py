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
        "en": "I couldn't find any data to answer this question. This usually happens if the data is outside your Space or Crew's authorized access."
    },
    "NO_DATA_FOUND": {
        "en": "Sorry, I couldn't find any data about {topic}. Please try rephrasing."
    },
    "NO_DATA_GENERIC": {
        "en": "Sorry, I couldn't find any data to answer this question. Please try rephrasing."
    },
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
    Detects language using simple stopword heuristics.
    Supports EN, PT, ES. Defaults to 'en' if uncertain or short.
    """
    if not text or len(text) < 5:
        return "en"

    text = text.lower()

    # Common stopwords
    stops_pt = {
        " o ",
        " a ",
        " os ",
        " as ",
        " um ",
        " uma ",
        " de ",
        " da ",
        " do ",
        " em ",
        " que ",
        " é ",
        " com ",
        " para ",
        " por ",
        " qual ",
        " quem ",
        " como ",
    }
    stops_es = {
        " el ",
        " la ",
        " los ",
        " las ",
        " un ",
        " una ",
        " de ",
        " del ",
        " en ",
        " que ",
        " es ",
        " con ",
        " para ",
        " por ",
        " cual ",
        " quien ",
        " como ",
    }
    stops_en = {
        " the ",
        " a ",
        " an ",
        " of ",
        " in ",
        " on ",
        " and ",
        " is ",
        " are ",
        " with ",
        " for ",
        " to ",
        " from ",
        " what ",
        " who ",
        " how ",
        " which ",
    }

    # Pad text to match word boundaries
    padded = f" {text} "

    # Count matches
    count_pt = sum(1 for w in stops_pt if w in padded)
    count_es = sum(1 for w in stops_es if w in padded)
    count_en = sum(1 for w in stops_en if w in padded)

    # If explicitly English words are found, favor English
    if count_en > 0 and count_en >= count_pt and count_en >= count_es:
        return "en"

    # Heuristic decision
    if count_pt > count_en and count_pt > count_es:
        return "pt"
    if count_es > count_en and count_es > count_pt:
        return "es"

    # If mixed or unsure, default to checking specific stronger signals
    if any(
        x in padded
        for x in [
            " monthly ",
            " revenue ",
            " performance ",
            " dashboard ",
            " show ",
            " list ",
            " count ",
        ]
    ):
        return "en"

    return "en"
