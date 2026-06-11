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
