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

# Languages the system supports. Adding a new language here is the only
# change needed at the i18n layer.
SUPPORTED_LANGUAGES = {"en", "pt"}

# Minimum confidence (0–1) for the gatekeeper detector to trust a result.
# Below this threshold the text is considered ambiguous and we don't block.
_CONFIDENCE_THRESHOLD = 0.50

# Minimum text length to attempt detection. Shorter texts are too ambiguous.
_MIN_TEXT_LENGTH = 8

# ---------------------------------------------------------------------------
# Lingua detectors — initialised once at import time (thread-safe, read-only).
#
# Two detectors, two jobs:
#   _DETECTOR_ALL      — knows all 75 languages. Used by detect_language() so
#                        the gatekeeper can identify clearly unsupported ones
#                        (FR/ES/DE). Low-confidence results fall back to "en"
#                        so jargon-heavy PT questions are never wrongly blocked.
#
#   _DETECTOR_BILINGUAL — knows only EN and PT. Used by resolve_language() to
#                        pick the response language. Always returns one of the
#                        two, even for short or jargon-mixed text, which fixes
#                        the code-switching false-positives langdetect had.
# ---------------------------------------------------------------------------
try:
    from lingua import Language, LanguageDetectorBuilder  # type: ignore

    _DETECTOR_ALL = (
        LanguageDetectorBuilder.from_all_languages()
        .with_minimum_relative_distance(0.0)
        .build()
    )

    _DETECTOR_BILINGUAL = LanguageDetectorBuilder.from_languages(
        Language.ENGLISH, Language.PORTUGUESE
    ).build()

    _LINGUA_AVAILABLE = True
except Exception:
    _DETECTOR_ALL = None
    _DETECTOR_BILINGUAL = None
    _LINGUA_AVAILABLE = False


def _lingua_lang_code(language) -> str:
    """Convert a lingua Language enum to a lowercase BCP-47 base tag."""
    if language is None:
        return "en"
    name = str(language)  # e.g. "Language.PORTUGUESE"
    base = name.split(".")[-1].lower()  # "portuguese"
    _MAP = {"portuguese": "pt", "english": "en"}
    return _MAP.get(base, base[:2])


def detect_language(text: str) -> str:
    """
    Detects the language of *text* (gatekeeper use).

    Returns the raw BCP-47 language code (e.g. "en", "pt", "es", "fr").
    Falls back to "en" when the text is too short or detection confidence
    is below the threshold — so jargon-heavy or short messages are never
    wrongly blocked.

    Uses lingua's all-language detector for high accuracy on unsupported
    languages (FR/ES/DE detected at 96-100% confidence).
    """
    if not text or len(text.strip()) < _MIN_TEXT_LENGTH:
        return "en"

    try:
        if _LINGUA_AVAILABLE and _DETECTOR_ALL is not None:
            values = _DETECTOR_ALL.compute_language_confidence_values(text)
            if not values:
                return "en"
            top = values[0]
            if top.value < _CONFIDENCE_THRESHOLD:
                return "en"
            return _lingua_lang_code(top.language)

        # Fallback: langdetect (kept as safety net if lingua unavailable)
        from langdetect import detect_langs  # type: ignore
        from langdetect import DetectorFactory

        DetectorFactory.seed = 0
        results = detect_langs(text)
        if not results or results[0].prob < 0.70:
            return "en"
        lang = results[0].lang
        return "pt" if lang.startswith("pt") else lang

    except Exception:
        return "en"


def _detect_bilingual(text: str) -> str:
    """
    Picks the response language (EN or PT) for a given text.

    Uses lingua's bilingual detector (trained only on EN+PT) so it always
    returns one of the two languages — even for short or jargon-mixed text.
    This fixes code-switching false-positives where langdetect would return
    'es' or 'fr' for valid PT business questions with English loanwords.
    """
    if not text or len(text.strip()) < _MIN_TEXT_LENGTH:
        return "en"

    try:
        if _LINGUA_AVAILABLE and _DETECTOR_BILINGUAL is not None:
            lang = _DETECTOR_BILINGUAL.detect_language_of(text)
            return _lingua_lang_code(lang)

        # Fallback to gatekeeper detector
        detected = detect_language(text)
        return detected if detected in SUPPORTED_LANGUAGES else "en"

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

    # Use the bilingual detector: always returns EN or PT, handles jargon well.
    detected = _detect_bilingual(question or "")
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

    # Step 1 — gatekeeper: use the all-language detector to check if the
    # question is *confidently* in an unsupported language (FR/ES/DE…).
    # Low-confidence results (jargon, loanwords) fall back to "en" in
    # detect_language(), so they are never wrongly blocked.
    raw = detect_language(question or "")
    if raw not in SUPPORTED_LANGUAGES:
        return True, "en"

    # Step 2 — response language: use the bilingual detector (EN+PT only).
    # It always picks one of the two, handling code-switching correctly.
    response_lang = _detect_bilingual(question or "")
    return False, response_lang


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
        detected = _detect_bilingual(content)
        if detected in SUPPORTED_LANGUAGES:
            return detected

    return None
