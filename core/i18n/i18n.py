# core/i18n/i18n.py
from __future__ import annotations

from typing import Dict, List
import logging

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
            # Correção: langdetect costuma confundir PT/ES/IT em frases curtas.
            # Aplicamos um pós-processamento simples por heurística de marcadores.
            if lang in {"pt", "es", "it"}:
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
