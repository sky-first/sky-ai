# core/i18n/i18n.py
from __future__ import annotations

from typing import Dict, List, Any, Optional
import logging

MESSAGES: Dict[str, Dict[str, str]] = {
    "SECURITY_BLOCKED": {
        "en": "I can't help with that request. Please rephrase your question about your data or contact an administrator.",
        "pt": "Não consigo ajudar com esse pedido. Reformule a pergunta sobre os seus dados, ou fale com um administrador.",
        "es": "No puedo ayudar con esa solicitud. Reformule su pregunta sobre sus datos o hable con un administrador.",
    },
    "PII_BLOCKED": {
        "en": "I cannot process sensitive personal information. Please rephrase your question without including personal data.",
        "pt": "Não consigo tratar dados pessoais sensíveis. Reformule a pergunta sem os incluir.",
        "es": "No puedo procesar información personal sensible. Reformule su pregunta sin incluir datos personales.",
    },
    # Every call site for this key is an exception handler — the pipeline
    # broke. The old copy claimed "no data / outside your Space or Crew's
    # access", which sent everyone investigating permissions and datasets
    # while the real cause was an unhandled TypeError. Say what happened:
    # a failure the user cannot fix by rephrasing. Genuine empty results use
    # NO_DATA_FOUND / NO_DATA_GENERIC.
    "TECHNICAL_ERROR": {
        "en": "Something went wrong on our side while answering this question — it isn't a problem with your data or your access. The error has been logged. Please try again, and tell your administrator if it keeps happening.",
        "pt": "Algo correu mal do nosso lado ao responder a esta pergunta — não é problema dos seus dados nem do seu acesso. O erro ficou registado. Tente de novo e avise um administrador se continuar.",
        "es": "Algo falló de nuestro lado al responder a esta pregunta — no es un problema de sus datos ni de su acceso. El error quedó registrado. Inténtelo de nuevo y avise a su administrador si continúa.",
    },
    "NO_DATA_FOUND": {
        "en": "Sorry, I couldn't find any data about {topic}. Please try rephrasing.",
        "pt": "Não encontrei dados sobre {topic}. Experimente perguntar de outra maneira.",
        "es": "No encontré datos sobre {topic}. Pruebe a reformular la pregunta.",
    },
    "NO_DATA_GENERIC": {
        "en": "Sorry, I couldn't find any data to answer this question. Please try rephrasing.",
        "pt": "Não encontrei dados para responder a esta pergunta. Experimente perguntar de outra maneira.",
        "es": "No encontré datos para responder a esta pregunta. Pruebe a reformular.",
    },
    # ── As que estavam cravadas nos ficheiros ───────────────────────────
    #
    # Estavam escritas como `if lang == "pt": ... else: <inglês>`, em quinze
    # sítios. O espanhol caía sempre no inglês — interface em espanhol,
    # respostas em inglês, que é pior do que não ter espanhol porque parece
    # que funciona até se ler a resposta.
    #
    # É exactamente o defeito que o `lingua_da_resposta.py` avisa no seu
    # cabeçalho, e aconteceu à mesma: a REGRA estava centralizada, as
    # FRASES não.
    "OUT_OF_SCOPE": {
        "en": "I answer questions about your business data — orders, customers, revenue, products and the other metrics you have connected. That one falls outside it. What would you like to know about your data?",
        "pt": "Respondo a perguntas sobre os dados do seu negócio — encomendas, clientes, receita, produtos e as outras métricas que ligou. Essa fica de fora. O que gostaria de saber sobre os seus dados?",
        "es": "Respondo a preguntas sobre los datos de su negocio — pedidos, clientes, ingresos, productos y las demás métricas que haya conectado. Esa queda fuera. ¿Qué le gustaría saber sobre sus datos?",
    },
    "CATALOG_REFUSED": {
        "en": "I can't help with that request. Please rephrase your question about your data.",
        "pt": "Não consigo ajudar com esse pedido. Reformule a pergunta sobre os seus dados.",
        "es": "No puedo ayudar con esa petición. Reformule la pregunta sobre sus datos.",
    },
    "WHICH_TABLE": {
        "en": "Which table do you want to inspect? For example: `what columns are in [table_name]?`",
        "pt": "Que tabela quer ver? Por exemplo: `que colunas tem a [nome_da_tabela]?`",
        "es": "¿Qué tabla quiere ver? Por ejemplo: `¿qué columnas tiene [nombre_de_tabla]?`",
    },
    "NO_RELEVANT_TABLES": {
        "en": "I couldn't find any table that answers that. Try naming the metric or the area you mean.",
        "pt": "Não encontrei nenhuma tabela que responda a isso. Experimente dizer a métrica ou a área que tem em mente.",
        "es": "No encontré ninguna tabla que responda a eso. Pruebe a decir la métrica o el área que tiene en mente.",
    },
    "NOT_ENOUGH_DATA": {
        "en": "I don't have enough data to answer this question.",
        "pt": "Não tenho dados suficientes para responder a esta pergunta.",
        "es": "No tengo datos suficientes para responder a esta pregunta.",
    },
    "SUGGESTION_LABEL": {
        "en": "Suggestion",
        "pt": "Sugestão",
        "es": "Sugerencia",
    },
    # ── Períodos ────────────────────────────────────────────────────────
    "PERIOD_FALLBACK": {
        "en": "No data for **{pedido}**. The most recent period with data is **{usado}** — here is what it shows:",
        "pt": "Não há dados de **{pedido}**. O período mais recente com dados é **{usado}** — é o que se segue:",
        "es": "No hay datos de **{pedido}**. El periodo más reciente con datos es **{usado}** — esto es lo que muestra:",
    },
    "PERIOD_STALE": {
        "en": "Your data goes up to **{ate}** (a gap of about {meses} months). There is nothing more recent. Would you like to see the period up to {ate}?",
        "pt": "Os seus dados vão até **{ate}** (uma lacuna de cerca de {meses} meses). Não há nada mais recente. Quer ver o período até {ate}?",
        "es": "Sus datos llegan hasta **{ate}** (un hueco de unos {meses} meses). No hay nada más reciente. ¿Quiere ver el periodo hasta {ate}?",
    },
    "PERIOD_SOURCE_EMPTY": {
        "en": "There is no data in this source yet.",
        "pt": "Esta fonte ainda não tem dados nenhuns.",
        "es": "Esta fuente todavía no tiene datos.",
    },
    "PERIOD_OUT_OF_RANGE": {
        "en": "No data for that period. The range available is **{de}** to **{ate}**.",
        "pt": "Não há dados nesse intervalo. O período disponível vai de **{de}** a **{ate}**.",
        "es": "No hay datos en ese intervalo. El periodo disponible va de **{de}** a **{ate}**.",
    },
}


def get_message(key: str, lang: str = "en", **kwargs: Any) -> str:
    """A mensagem traduzida, em EN, PT ou ES (recorre ao EN)."""
    resolved = lang if lang in SUPPORTED_LANGUAGES else "en"

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
SUPPORTED_LANGUAGES = {"en", "pt", "es"}

# Minimum confidence (0–1) for the gatekeeper detector to trust a result.
# Below this threshold the text is considered ambiguous and we don't block.
_CONFIDENCE_THRESHOLD = 0.50

# Minimum text length to attempt detection. Shorter texts are too ambiguous.
_MIN_TEXT_LENGTH = 8

# A confiança que o espanhol tem de ter para ganhar ao português.
#
# Ver `_detect_lingua_da_resposta` para a medição que fixou este número. Em
# resumo: o espanhol a sério mede-se entre 0,76 e 0,999; o português com
# jargão inglês empata a três à volta de 0,35. 0,60 fica no vazio entre os
# dois, longe de ambos.
_CONFIANCA_MINIMA_ES = 0.60

# ---------------------------------------------------------------------------
# Lingua detectors — initialised once at import time (thread-safe, read-only).
#
# Two detectors, two jobs:
#   _DETECTOR_ALL      — knows all 75 languages. Used by detect_language() so
#                        the gatekeeper can identify clearly unsupported ones
#                        (FR/ES/DE). Low-confidence results fall back to "en"
#                        so jargon-heavy PT questions are never wrongly blocked.
#
#   _DETECTOR_RESPOSTA — knows EN, PT and ES. Used by resolve_language() to
#                        pick the response language. Always returns one of the
#                        three, even for short or jargon-mixed text, which
#                        fixes the code-switching false-positives langdetect
#                        had.
# ---------------------------------------------------------------------------
try:
    from lingua import Language, LanguageDetectorBuilder  # type: ignore

    _DETECTOR_ALL = (
        LanguageDetectorBuilder.from_all_languages()
        .with_minimum_relative_distance(0.0)
        .build()
    )

    # Tres linguas, nao duas.
    #
    # Chamava-se BILINGUAL e conhecia EN+PT. Acrescentar "es" ao
    # SUPPORTED_LANGUAGES sem lhe tocar dava o defeito silencioso: uma
    # pergunta em espanhol, sem locale fixado, era classificada como PT ou
    # EN — nunca ES — e respondia-se na lingua errada com toda a confianca.
    # A app tem hoje um modo "segue a sua pergunta" que depende disto.
    _DETECTOR_RESPOSTA = LanguageDetectorBuilder.from_languages(
        Language.ENGLISH, Language.PORTUGUESE, Language.SPANISH
    ).build()

    _LINGUA_AVAILABLE = True
except Exception:
    _DETECTOR_ALL = None
    _DETECTOR_RESPOSTA = None
    _LINGUA_AVAILABLE = False


def _lingua_lang_code(language) -> str:
    """Convert a lingua Language enum to a lowercase BCP-47 base tag."""
    if language is None:
        return "en"
    name = str(language)  # e.g. "Language.PORTUGUESE"
    base = name.split(".")[-1].lower()  # "portuguese"
    # O recurso `base[:2]` acerta em muitas linguas por acidente e falha
    # exactamente nesta: "spanish"[:2] e "sp", que nao existe em lado
    # nenhum — e "sp" not in SUPPORTED_LANGUAGES fazia o espanhol cair em
    # ingles sem deixar rasto.
    _MAP = {"portuguese": "pt", "english": "en", "spanish": "es"}
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


def _detect_lingua_da_resposta(text: str) -> str:
    """
    Picks the response language (EN, PT or ES) for a given text.

    Uses lingua's three-language detector so it always returns one of the
    three — even for short or jargon-mixed text. This fixes code-switching
    false-positives where langdetect would return 'fr' for valid PT
    business questions with English loanwords.

    ── O espanhol precisa de mais prova do que as outras duas ────────────

    Português e espanhol são línguas irmãs, e o jargão inglês do dia-a-dia
    empurra o detector para o espanhol sem que a frase tenha nada de
    espanhol. Medido:

        "qual o win rate do time de sales no último quarter?"
            ES 0,351 · PT 0,327 · EN 0,322

    Isso não é uma detecção, é um empate a três — e com o empate a decidir
    ganhava o espanhol. Uma pergunta portuguesa respondida em espanhol à
    frente de um cliente é dos erros mais caros que a app pode cometer, e
    Portugal é o mercado principal.

    Por isso o espanhol só ganha acima de `_CONFIANCA_MINIMA_ES`. Abaixo
    disso escolhe-se o melhor entre PT e EN — que é o que o detector de
    duas línguas fazia antes de o espanhol existir.

    O espanhol a sério passa com folga: as frases espanholas medidas dão
    entre 0,76 e 0,999.
    """
    if not text or len(text.strip()) < _MIN_TEXT_LENGTH:
        return "en"

    try:
        if _LINGUA_AVAILABLE and _DETECTOR_RESPOSTA is not None:
            valores = _DETECTOR_RESPOSTA.compute_language_confidence_values(text)
            if not valores:
                return "en"
            escolha = _lingua_lang_code(valores[0].language)
            if escolha == "es" and valores[0].value < _CONFIANCA_MINIMA_ES:
                for v in valores[1:]:
                    codigo = _lingua_lang_code(v.language)
                    if codigo in ("pt", "en"):
                        return codigo
                return "pt"
            return escolha

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
    Single source of truth for the *response* language (always EN, PT or ES).

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

    # O detector da resposta: devolve sempre EN, PT ou ES, e aguenta jargão.
    detected = _detect_lingua_da_resposta(question or "")
    if detected in SUPPORTED_LANGUAGES:
        return detected

    return fallback if fallback in SUPPORTED_LANGUAGES else "en"


def unsupported_language_message() -> str:
    """
    Message shown when a question is in an unsupported language.

    Since we don't know the user's language (it's unsupported), we surface the
    notice in ALL supported languages so it's actionable either way.
    """
    return (
        "I'm sorry, but I currently only support English, Portuguese and "
        "Spanish. Please rephrase your question in one of those languages."
        "\n\n"
        "Desculpe, mas de momento só suporto inglês, português e espanhol. "
        "Reformule a sua pergunta numa dessas línguas."
        "\n\n"
        "Lo siento, pero por ahora solo admito inglés, portugués y español. "
        "Reformule su pregunta en uno de esos idiomas."
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
    response_lang = _detect_lingua_da_resposta(question or "")
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
        detected = _detect_lingua_da_resposta(content)
        if detected in SUPPORTED_LANGUAGES:
            return detected

    return None
