"""Aquecer no arranque o que o primeiro pedido pagava a frio.

Produção, 12/10/2026, primeiro pedido depois do deploy de cbb56743 (tenant
skyfirstlabs, ligação «Operaciones»): «Lista las 5 gasolineras con el gasóleo
A más barato en la tabla gasolineras_rota para la ruta Badajoz-Madrid» levou
82,6 s. Lido nos registos do pod com ``--timestamps``:

* 34,5 s sem uma linha e sem responder às sondas (``GET /docs`` parou de
  aparecer): o detector de línguas com as 75 línguas carrega os modelos no
  PRIMEIRO ``compute_language_confidence_values`` — 10,2 s medidos num
  portátil, mais no pod — e isto corre dentro do handler assíncrono, com o
  laço de eventos parado;
* 29,7 s dentro do orquestrador a descarregar (20 s, HuggingFace) e carregar
  o modelo de embeddings ``multilingual-e5-large`` (2,2 GB; a pasta é um
  ``emptyDir``, cada pod novo descarrega-o outra vez).

O pedido seguinte, já quente, levou 2,7 s no orquestrador. Nenhum destes
custos é do pedido: são do processo. Por isso pagam-se aqui, numa thread em
segundo plano lançada no arranque — sem atrasar o arranque nem a sonda de
prontidão, e sem partir nada se a rede falhar (o pedido carrega como antes).

Desliga-se com ``AI_WARMUP=0``; nunca corre dentro do pytest.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Dict, Optional

from core.logging_utils import log_event

_TEXTOS = (
    "Lista las 5 gasolineras más baratas en la ruta Badajoz-Madrid",
    "Qual foi a receita total por canal no último mês?",
    "Which store had the slowest service time last week?",
)

_lancado = False
_lancado_lock = threading.Lock()


def desligado() -> bool:
    if os.getenv("AI_WARMUP", "1").strip().lower() in ("0", "false", "no", "off"):
        return True
    return "pytest" in sys.modules


def _medir(nome: str, fn) -> Optional[float]:
    t0 = time.perf_counter()
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 — aquecer nunca parte o arranque
        log_event("warmup_failed", {"component": nome, "error": str(exc)[:300]})
        return None
    ms = (time.perf_counter() - t0) * 1000
    log_event("warmup_timing", {"component": nome, "ms": round(ms)})
    return ms


def _linguas() -> None:
    from core.i18n.i18n import detect_language, resolve_language

    for texto in _TEXTOS:
        detect_language(texto)
        resolve_language(texto)


def _embeddings() -> None:
    from core.llm.factory import create_embedding_provider
    from core.rag.embeddings import LocalEmbeddingProvider

    provider = create_embedding_provider()
    # Só o modelo em processo tem custo de arranque; os de rede são clientes.
    if isinstance(provider, LocalEmbeddingProvider):
        provider.embed([_TEXTOS[0]])


def aquecer() -> Dict[str, Optional[float]]:
    """Corre o aquecimento já (bloqueia). Devolve ``{componente: ms}``."""
    return {
        "language_detector": _medir("language_detector", _linguas),
        "embedding_model": _medir("embedding_model", _embeddings),
    }


def aquecer_em_segundo_plano() -> Optional[threading.Thread]:
    """Lança o aquecimento numa thread daemon (uma vez por processo)."""
    global _lancado
    if desligado():
        return None
    with _lancado_lock:
        if _lancado:
            return None
        _lancado = True
    t = threading.Thread(target=aquecer, name="aquecimento", daemon=True)
    t.start()
    return t
