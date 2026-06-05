# core/i18n/i18n.py
from __future__ import annotations

from typing import Dict, List, Any, Optional
import logging

MESSAGES: Dict[str, Dict[str, str]] = {
    "SECURITY_BLOCKED": {
        "en": "I can't help with that request. Please rephrase your question about your data or contact an administrator.",
        "pt": "Não posso ajudar com essa solicitação. Por favor, reformule sua pergunta sobre seus dados ou entre em contato com um administrador.",
    },
    "PII_BLOCKED": {
        "en": "I cannot process sensitive personal information. Please rephrase your question without including personal data.",
        "pt": "Não consigo processar informações pessoais sensíveis. Por favor, reformule sua pergunta sem incluir dados pessoais.",
    },
    "TECHNICAL_ERROR": {
        "en": "I couldn't find any data to answer this question. This usually happens if the data is outside your Space or Crew's authorized access.",
        "pt": "Não encontrei dados para responder esta pergunta. Isso geralmente acontece quando os dados estão fora do acesso autorizado do seu Space ou Crew.",
    },
    "NO_DATA_FOUND": {
        "en": "Sorry, I couldn't find any data about {topic}. Please try rephrasing.",
        "pt": "Desculpe, não encontrei dados sobre {topic}. Tente reformular a pergunta.",
    },
    "NO_DATA_GENERIC": {
        "en": "Sorry, I couldn't find any data to answer this question. Please try rephrasing.",
        "pt": "Desculpe, não encontrei dados para responder esta pergunta. Tente reformular.",
    },
}


def get_message(key: str, lang: str = "en", **kwargs: Any) -> str:
    """Returns a translated and formatted message for EN or PT (falls back to EN)."""
    resolved = lang if lang in ("en", "pt") else "en"

    msg_dict = MESSAGES.get(key, MESSAGES.get("TECHNICAL_ERROR", {}))
    msg = msg_dict.get(resolved) or msg_dict.get("en", "An unexpected error occurred.")

    if kwargs:
        try:
            return msg.format(**kwargs)
        except Exception:
            return msg

    return msg


logger = logging.getLogger("dataassistant.i18n")

# Languages the system supports. Any detected language outside this set
# falls back to "en". Adding a new language here is the only change needed.
SUPPORTED_LANGUAGES = {"en", "pt"}

# Minimum confidence from langdetect to trust the result. Below this
# threshold (or for texts too short to be reliable) we fall back to "en".
_CONFIDENCE_THRESHOLD = 0.70
_MIN_TEXT_LENGTH = 8


def detect_language(text: str) -> str:
    """
    Detects the language of *text* using langdetect (55+ languages).

    Returns the raw BCP-47 language code (e.g. "en", "pt", "es", "fr").
    Falls back to "en" only when the text is too short or confidence is low.
    Unsupported languages are returned as-is so gatekeepers can block them
    with an explicit message instead of silently answering in English.
    """
    if not text or len(text.strip()) < _MIN_TEXT_LENGTH:
        return "en"

    try:
        from langdetect import detect_langs, LangDetectException  # type: ignore

        results = detect_langs(text)
        if not results:
            return "en"

        top = results[0]
        lang = top.lang  # e.g. "pt", "en", "es", "fr" …

        if top.prob < _CONFIDENCE_THRESHOLD:
            return "en"

        # Normalise pt-br / pt-pt → "pt"
        if lang.startswith("pt"):
            return "pt"

        # Return the real detected code — callers decide whether to support it.
        # Unsupported languages are NOT silently remapped to "en" here so that
        # gatekeepers can surface a proper "language not supported" message.
        return lang

    except Exception:
        return "en"


def _normalize_lang_code(code: str) -> str:
    """
    Normalises a BCP-47 / locale code to its base language subtag.

    "pt-BR" -> "pt", "en_US" -> "en", "PT" -> "pt". Returns "" for empty
    input so callers can treat it as "no signal".
    """
    if not code:
        return ""
    return code.strip().lower().replace("_", "-").split("-")[0]


def resolve_language(
    question: str = "",
    *,
    locale: Optional[str] = None,
    thread_language: Optional[str] = None,
    fallback: str = "en",
) -> str:
    """
    Single source of truth for the *response* language (always EN or PT).

    Priority chain (first supported signal wins):
        1. ``locale``          — explicit user/platform preference (deterministic)
        2. ``thread_language`` — language already established in the conversation
                                 (keeps a thread "sticky" so short follow-ups like
                                 "sim" / "ok" don't flip the language)
        3. ``detect_language`` — statistical detection from the question text
        4. ``fallback``        — "en" when nothing else is trustworthy

    Unlike :func:`detect_language` (which returns the raw detected code so the
    gatekeeper can spot unsupported languages), this function ALWAYS returns a
    supported code, because its job is to pick the language we answer in.
    """
    for signal in (locale, thread_language):
        norm = _normalize_lang_code(signal or "")
        if norm in SUPPORTED_LANGUAGES:
            return norm

    detected = detect_language(question or "")
    if detected in SUPPORTED_LANGUAGES:
        return detected

    return fallback if fallback in SUPPORTED_LANGUAGES else "en"


def unsupported_language_message() -> str:
    """
    Bilingual message shown when a question is in an unsupported language.

    Since we don't know the user's language (it's unsupported), we surface the
    notice in BOTH supported languages so it's actionable either way.
    """
    return (
        "I'm sorry, but I currently only support English and Portuguese. "
        "Please rephrase your question in one of those languages.\n\n"
        "Desculpe, mas no momento só dou suporte a inglês e português. "
        "Por favor, reformule sua pergunta em um desses idiomas."
    )


def language_decision(
    question: str = "",
    *,
    locale: Optional[str] = None,
    thread_language: Optional[str] = None,
) -> "tuple[bool, str]":
    """
    Decide whether to block (unsupported language) and which language to answer in.

    Returns ``(blocked, language)``.

    We block ONLY when there is no trustworthy signal — no explicit ``locale`` and
    no established ``thread_language`` — AND the question is confidently in an
    unsupported language. An explicit locale or an ongoing EN/PT conversation
    always wins over a noisy detection: that's what stops valid short or
    jargon-heavy questions inside an EN/PT thread from being wrongly rejected.

    Note: :func:`detect_language` already falls back to "en" for short /
    low-confidence text, so reaching an unsupported code here means the detector
    was confident enough to trust the rejection.
    """
    for signal in (locale, thread_language):
        norm = _normalize_lang_code(signal or "")
        if norm in SUPPORTED_LANGUAGES:
            return False, norm

    detected = detect_language(question or "")
    if detected in SUPPORTED_LANGUAGES:
        return False, detected

    return True, "en"


def thread_language_from_history(
    chat_history: Optional[List[Dict[str, str]]],
) -> Optional[str]:
    """
    Derive the "sticky" language of a conversation from its history.

    Scans prior messages in chronological order and returns the language of the
    first *user* message long enough to be detected reliably. This makes a thread
    stable: once the conversation has established a language, short follow-ups
    ("sim", "ok", "and last year?") inherit it instead of being re-detected from
    scratch (which is what caused PT threads to flip to EN).

    Returns None when there is no history or no message reliable enough — callers
    then fall back to detecting the current question.
    """
    if not chat_history:
        return None

    for msg in chat_history:
        if (msg or {}).get("role") != "user":
            continue
        content = (msg.get("content") or "").strip()
        if len(content) < _MIN_TEXT_LENGTH:
            continue
        detected = detect_language(content)
        if detected in SUPPORTED_LANGUAGES:
            return detected

    return None
