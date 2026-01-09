# core/i18n/i18n.py
from __future__ import annotations

from typing import Dict, List, Any
import logging

# Dicionário centralizado de mensagens para o usuário
# Suporta chaves para diferentes categorias de resposta
MESSAGES: Dict[str, Dict[str, str]] = {
    "SECURITY_BLOCKED": {
        "pt": "Não posso ajudar com esse tipo de solicitação. Reformule sua pergunta sobre os seus dados ou contacte um administrador.",
        "es": "No puedo ayudar con esa solicitud. Reformula tu pregunta sobre tus datos o contacta a un administrador.",
        "en": "I can't help with that request. Please rephrase your question about your data or contact an administrator."
    },
    "PII_BLOCKED": {
        "pt": "Não posso processar informações pessoais sensíveis. Por favor, reformule sua pergunta sem incluir dados pessoais.",
        "es": "No puedo procesar información personal sensible. Por favor, reformula tu pregunta sin incluir datos personales.",
        "en": "I cannot process sensitive personal information. Please rephrase your question without including personal data."
    },
    "TECHNICAL_ERROR": {
        "pt": "Houve um erro técnico ao consultar a base de dados.",
        "es": "Hubo un error técnico al consultar la base de datos.",
        "en": "There was a technical error while querying the database."
    },
    "NO_DATA_FOUND": {
        "pt": "Desculpe, não encontrei dados sobre {topic}. Tente reformular.",
        "es": "Lo siento, no encontré datos sobre {topic}. Intenta reformular.",
        "en": "Sorry, I couldn't find any data about {topic}. Please try rephrasing."
    },
    "NO_DATA_GENERIC": {
        "pt": "Desculpe, não encontrei dados para responder a essa pergunta. Tente reformular.",
        "es": "Lo siento, no encontré datos para responder a esa pregunta. Intenta reformular.",
        "en": "Sorry, I couldn't find any data to answer this question. Please try rephrasing."
    }
}


def get_message(key: str, lang: str = "en", **kwargs: Any) -> str:
    """
    Retorna uma mensagem traduzida e formatada.
    """
    # Normaliza lang
    lang = (lang or "en").split("-")[0].lower()
    if lang not in ["pt", "es", "en"]:
        lang = "en"
    
    # Busca a mensagem
    msg_dict = MESSAGES.get(key, MESSAGES.get("TECHNICAL_ERROR"))
    msg = msg_dict.get(lang, msg_dict.get("en", ""))
    
    # Formata se houver kwargs
    if kwargs:
        try:
            return msg.format(**kwargs)
        except Exception:
            return msg
    
    return msg


try:
    from langdetect import detect, DetectorFactory  # type: ignore

    DetectorFactory.seed = 0
    LANGDETECT_AVAILABLE = True
except ImportError:
    LANGDETECT_AVAILABLE = False

logger = logging.getLogger("dataassistant.i18n")


def _heuristic_detect(text: str) -> str:
    """
    Detecção bem simples baseada em palavras-chave.
    Só para fallback quando langdetect não estiver disponível.
    """
    text_lower = text.lower()

    language_indicators: Dict[str, List[str]] = {
        "en": ["what", "how", "when", "where", "which", "who", "why", "total", "revenue", "customer", "invoice"],
        "pt": ["qual", "quais", "quanto", "como", "quando", "onde", "faturamento", "receita", "cliente", "fatura"],
        "es": ["qué", "cuál", "cuánto", "cómo", "cuándo", "dónde", "facturación", "ingresos", "cliente", "factura"],
        "fr": ["quel", "quelle", "combien", "comment", "quand", "où", "revenu", "facture", "client"],
    }

    scores: Dict[str, int] = {lang: 0 for lang in language_indicators.keys()}

    for lang, indicators in language_indicators.items():
        scores[lang] = sum(1 for w in indicators if w in text_lower)

    best_lang = max(scores, key=scores.get)
    if scores[best_lang] == 0:
        return "en"
    return best_lang


def detect_language(text: str) -> str:
    """
    Detecta idioma do texto do usuário.
    - Tenta usar langdetect se estiver instalado
    - Senão, cai na heurística simples
    """
    if not text or not isinstance(text, str) or len(text.strip()) < 3:
        return "en"

    if LANGDETECT_AVAILABLE:
        try:
            detected = detect(text)
            # Normaliza códigos tipo "pt-BR" -> "pt"
            lang = detected.split("-")[0].lower()
            # Correção: langdetect costuma confundir PT/ES em frases curtas.
            # Aplicamos um pós-processamento simples por heurística de marcadores.
            if lang in {"pt", "es"}:
                tl = text.lower()
                pt_markers = [
                    "você",
                    "vocês",
                    "não",
                    "ção",
                    "ções",
                    "quais",
                    "qual",
                    "quantos",
                    "quanto",
                    "tabela",
                    "tabelas",
                    "dados",
                    "colunas",
                    "dentro",
                    "temos",
                    "fatura",
                    "cliente",
                ]
                es_markers = [
                    "usted",
                    "ustedes",
                    "qué",
                    "cuál",
                    "cuáles",
                    "cuánto",
                    "cuántos",
                    "cómo",
                    "dónde",
                    "factura",
                    "facturación",
                    "ingresos",
                ]
                pt_score = sum(1 for m in pt_markers if m in tl)
                es_score = sum(1 for m in es_markers if m in tl)

                # Se houver sinais fortes de PT, force PT; idem para ES.
                if pt_score > es_score:
                    return "pt"
                if es_score > pt_score:
                    return "es"

            return lang
        except Exception as e:
            logger.warning("langdetect failed: %s", e)

    # Fallback heurístico
    return _heuristic_detect(text)
