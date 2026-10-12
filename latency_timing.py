"""
latency_timing.py
=================

Instrumentação leve de latência para o pipeline da IA (LangGraph).

OBJETIVO: descobrir ONDE os 10-20s da resposta estão sendo gastos, antes de
otimizar qualquer coisa. Isto NÃO é observabilidade de produção — é um
instrumento de investigação pontual. Plugar, rodar ~15-20 perguntas, analisar,
e (provavelmente) remover depois.

Não depende de nada externo: só stdlib. Não precisa instalar nada.

COMO USAR (resumo — detalhes no guia):
    1. Decore cada nó do grafo com @timed("nome_do_no").
    2. Envolva as chamadas de LLM e de BigQuery com `with timed_span(...)`,
       para separar tempo de REDE do tempo do SEU código.
    3. No início de cada request, chame new_trace() para agrupar os spans.
    4. Garanta que o log está sendo escrito num arquivo (setup_file_logging).
    5. Rode as perguntas e analise com analyze_latency.py.
"""

import time
import uuid
import logging
import functools
import asyncio
import contextvars

# ---------------------------------------------------------------------------
# Logger dedicado. Por padrão não escreve em lugar nenhum até você configurar.
# ---------------------------------------------------------------------------
logger = logging.getLogger("latency")
logger.setLevel(logging.INFO)


def setup_file_logging(path: str = "latency.log") -> None:
    """Faz os timings irem para um arquivo. Chame uma vez no boot da aplicação.

    Se você já tem logging configurado no projeto, pode pular isto — só
    garanta que mensagens INFO do logger 'latency' chegam a algum lugar
    que você consiga ler depois (arquivo, stdout, etc.).
    """
    handler = logging.FileHandler(path)
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(handler)


# ---------------------------------------------------------------------------
# trace_id por request. Usa contextvars para funcionar mesmo com async/await
# (cada request carrega seu próprio id sem vazar para outro request concorrente).
# ---------------------------------------------------------------------------
_trace_id: contextvars.ContextVar = contextvars.ContextVar("trace_id", default="-")


def new_trace(trace_id: str | None = None) -> str:
    """Inicia um novo trace. Chame no PONTO DE ENTRADA de cada request da IA
    (ex.: logo no começo do handler que recebe a pergunta do usuário).
    Se você já tem um request_id/conversation_id, passe-o aqui para correlacionar.
    """
    tid = trace_id or uuid.uuid4().hex[:8]
    _trace_id.set(tid)
    iniciar_pedido()
    return tid


def _emit(kind: str, name: str, node: str | None, duration_ms: float) -> None:
    """Escreve uma linha de timing parseável pelo analyze_latency.py.
    Formato fixo — NÃO altere sem atualizar o parser.
    """
    node_part = f" node={node}" if node else ""
    logger.info(
        f"LAT trace={_trace_id.get()} kind={kind} name={name}{node_part} "
        f"duration_ms={duration_ms:.1f}"
    )
    # Os nós do grafo também vão para os registos do pod (``node_timing``) e
    # para o resumo do pedido. As linhas LAT acima só chegam a /tmp/latency.log
    # — foi por isso que a 12/10 os 80 s não tinham dono nos registos.
    if kind == "node":
        registar_tempo("node_timing", duration_ms, etapa=name, node=name)


# ---------------------------------------------------------------------------
# @timed — decorator para NÓS do grafo. Detecta sync vs async sozinho.
# IMPORTANTE: para funções async, ele mede o await completo (a execução real),
# não a criação da coroutine. Se você usasse um decorator sync numa função
# async, mediria ~0ms (erro clássico).
# ---------------------------------------------------------------------------
def timed(node_name: str):
    def decorator(fn):
        if asyncio.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def awrapper(*args, **kwargs):
                start = time.perf_counter()
                try:
                    return await fn(*args, **kwargs)
                finally:
                    _emit("node", node_name, None, (time.perf_counter() - start) * 1000)
            return awrapper

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                _emit("node", node_name, None, (time.perf_counter() - start) * 1000)
        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# timed_span — context manager para medir um TRECHO dentro de um nó.
# Use para isolar a chamada de LLM e a query do BigQuery do resto do código,
# porque é quase sempre aí que o tempo está (rede), não no seu Python.
# Funciona com `with` (sync) e `async with` (async).
#
#   with timed_span("llm_call", node="gerar_sql"):
#       resp = client.messages.create(...)
#
#   async with timed_span("bigquery", node="executar_query"):
#       rows = await run_query(sql)
# ---------------------------------------------------------------------------
class timed_span:
    def __init__(self, name: str, node: str | None = None):
        self.name = name
        self.node = node
        self.start = 0.0

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, *exc):
        _emit("span", self.name, self.node, (time.perf_counter() - self.start) * 1000)
        return False  # nao engole excecoes

    async def __aenter__(self):
        self.start = time.perf_counter()
        return self

    async def __aexit__(self, *exc):
        _emit("span", self.name, self.node, (time.perf_counter() - self.start) * 1000)
        return False


# ---------------------------------------------------------------------------
# Tempos por pedido, nos registos do pod (12/10/2026)
# ---------------------------------------------------------------------------
#
# «Lista las 5 gasolineras … Badajoz-Madrid» levou 82,6 s e os registos só
# explicavam ~2 s: os nós do grafo escreviam para /tmp/latency.log, as
# chamadas ao modelo não diziam quanto tinham demorado e nada somava o pedido.
# Lido com --timestamps, os 80 s eram três arranques a frio no primeiro pedido
# depois do deploy: o detector de línguas (34 s, com o laço de eventos parado),
# a descarga e carga do modelo de embeddings (30 s, dentro do orquestrador) e
# duas chamadas do orquestrador ReAct ao gpt-oss (12 s).
#
# Agora cada etapa escreve ``<etapa>_timing`` com ``ms`` e o pedido fecha com
# ``query_total_timing``: o total, as etapas de topo (somam o total, menos o
# que fica em ``unaccounted_ms``) e o detalhe (chamadas ao modelo, embeddings,
# cargas de modelos) — que é parte das etapas, não se soma a elas.

_pedido: contextvars.ContextVar = contextvars.ContextVar("pedido_tempos", default=None)


def iniciar_pedido() -> dict:
    """Abre o acumulador do pedido. O dict é partilhado por referência com as
    threads que copiam o contexto (``asyncio.to_thread``, nós do LangGraph)."""
    acc = {
        "inicio": time.perf_counter(),
        "etapas": {},
        "detalhe": {},
        "llm_calls": 0,
        "llm_ms": 0.0,
        "llm": [],
    }
    _pedido.set(acc)
    return acc


def _log_event(evento: str, campos: dict) -> None:
    try:
        from core.logging_utils import log_event

        log_event(evento, campos)
    except Exception:  # nunca partir um pedido por causa de um registo
        pass


def registar_tempo(
    evento: str,
    ms: float,
    etapa: str | None = None,
    detalhe: str | None = None,
    **campos,
) -> None:
    """Escreve ``evento`` com ``ms`` e soma-o ao pedido em curso.

    ``etapa``: uma etapa de TOPO do pedido (somam o total).
    ``detalhe``: algo que acontece DENTRO de uma etapa (uma chamada ao
    modelo, um embedding) — conta-se à parte.
    """
    ms = float(ms)
    payload = {"ms": round(ms), "trace": _trace_id.get()}
    payload.update(campos)
    _log_event(evento, payload)
    acc = _pedido.get()
    if acc is None:
        return
    try:
        if etapa:
            acc["etapas"][etapa] = acc["etapas"].get(etapa, 0.0) + ms
        if detalhe:
            acc["detalhe"][detalhe] = acc["detalhe"].get(detalhe, 0.0) + ms
        if evento == "llm_call_timing":
            acc["llm_calls"] += 1
            acc["llm_ms"] += ms
            if len(acc["llm"]) < 20:
                acc["llm"].append(
                    {
                        "caller": campos.get("caller"),
                        "model": campos.get("model"),
                        "ms": round(ms),
                    }
                )
    except Exception:
        pass


class medir:
    """``with medir("rag_timing", etapa="rag"):`` — mede e regista."""

    def __init__(self, evento: str, etapa: str | None = None, detalhe: str | None = None, **campos):
        self.evento = evento
        self.etapa = etapa
        self.detalhe = detalhe
        self.campos = campos
        self.inicio = 0.0

    def __enter__(self):
        self.inicio = time.perf_counter()
        return self

    def __exit__(self, exc_type, *exc):
        campos = dict(self.campos)
        if exc_type is not None:
            campos["ok"] = False
        registar_tempo(
            self.evento,
            (time.perf_counter() - self.inicio) * 1000,
            etapa=self.etapa,
            detalhe=self.detalhe,
            **campos,
        )
        return False


def resumo_do_pedido() -> dict | None:
    """O resumo do pedido em curso (ou None fora de um pedido)."""
    acc = _pedido.get()
    if acc is None:
        return None
    total = (time.perf_counter() - acc["inicio"]) * 1000
    etapas = {k: round(v) for k, v in sorted(acc["etapas"].items(), key=lambda kv: -kv[1])}
    contado = sum(acc["etapas"].values())
    return {
        "total_ms": round(total),
        "breakdown_ms": etapas,
        "unaccounted_ms": round(max(0.0, total - contado)),
        "detail_ms": {k: round(v) for k, v in sorted(acc["detalhe"].items(), key=lambda kv: -kv[1])},
        "llm_calls": acc["llm_calls"],
        "llm_ms": round(acc["llm_ms"]),
        "llm": list(acc["llm"]),
    }


def fechar_pedido(**campos) -> dict | None:
    """Escreve ``query_total_timing`` com o resumo do pedido."""
    resumo = resumo_do_pedido()
    if resumo is None:
        return None
    payload = {"trace": _trace_id.get()}
    payload.update(campos)
    payload.update(resumo)
    _log_event("query_total_timing", payload)
    return resumo


def quem_chamou(ignorar: tuple = ()) -> str:
    """``módulo.função`` do primeiro quadro fora dos fornecedores de LLM e
    das bibliotecas — para cada ``llm_call_timing`` dizer de onde veio."""
    import sys

    ignorados = (
        "providers.py",
        "latency_timing",
        "site-packages",
        "contextlib",
    ) + tuple(ignorar)
    f = sys._getframe(1)
    while f is not None:
        nome = f.f_code.co_filename
        if not any(i in nome for i in ignorados):
            mod = f.f_globals.get("__name__", "?")
            return f"{mod}.{f.f_code.co_name}"
        f = f.f_back
    return "?"
