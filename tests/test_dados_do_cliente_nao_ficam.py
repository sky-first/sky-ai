"""Dados do cliente não ficam em logs, checkpoints, Langfuse nem /pipeline.

Princípio (13/10/2026): nunca guardamos linhas do cliente. Cada teste fixa um
dos sítios onde a auditoria as encontrou (scratchpad auditoria-dados-do-cliente,
A2, A3, A10, A11, A12).
"""

from __future__ import annotations

import json
import logging
import sys
import types
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent


# ── Logs (A10, A11) ───────────────────────────────────────────────────────


def _capturar(caplog, evento, payload):
    from core.logging_utils import log_event

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="dataassistant"):
        log_event(evento, payload)
    linhas = [r.getMessage() for r in caplog.records if evento in r.getMessage()]
    assert linhas, "o evento não foi registado"
    return json.loads(linhas[-1])


def test_log_nao_leva_o_texto_da_resposta(caplog):
    obj = _capturar(
        caplog,
        "api_query_connection",
        {"answer_preview": "A Joana Silva faturou 1.200 €", "num_rows": 3},
    )
    assert "Joana" not in json.dumps(obj, ensure_ascii=False)
    assert obj["answer_preview"] == "<redacted:29 chars>"
    assert obj["num_rows"] == 3, "contagens continuam a passar"


def test_log_nao_leva_linhas_nem_amostras(caplog):
    obj = _capturar(
        caplog,
        "x_debug",
        {
            "data_sample": [{"nome": "Joana"}, {"nome": "Rui"}],
            "rows": 2,
            "values": ["BADAJOZ", "MÉRIDA"],
        },
    )
    texto = json.dumps(obj, ensure_ascii=False)
    assert "Joana" not in texto and "BADAJOZ" not in texto
    assert obj["data_sample"] == "<redacted:2 items>"
    assert obj["rows"] == 2


def test_literais_da_pergunta_nao_vao_para_o_log():
    """O bloco de literais traz valores reais das colunas. Regista-se só o
    tamanho — e a chave ``block`` deixou de existir no evento."""
    fonte = (RAIZ / "core" / "llm" / "specialist.py").read_text(encoding="utf-8")
    i = fonte.index('"specialist_question_literals"')
    trecho = fonte[i : i + 400]
    assert '"block"' not in trecho
    assert "literais_block[:" not in trecho


def test_sql_no_log_fica_sem_literais_de_texto(caplog):
    obj = _capturar(
        caplog,
        "x_sql",
        {"sql_preview": "SELECT * FROM t WHERE nome = 'Joana Silva' AND n > 3"},
    )
    assert obj["sql_preview"] == "SELECT * FROM t WHERE nome = '?' AND n > 3"


@pytest.mark.parametrize(
    "chave,valor",
    [
        ("conninfo_preview", "postgresql://sky:S3gr3d0@db.internal:5432/x"),
        ("dsn_preview", "databricks://token:dapiXYZ@host/db"),
        ("detalhe", "falhou postgresql://sky:S3gr3d0@db.internal:5432/x"),
    ],
)
def test_log_nunca_leva_credenciais(caplog, chave, valor):
    obj = _capturar(caplog, "x_dsn", {chave: valor})
    texto = json.dumps(obj)
    assert "S3gr3d0" not in texto and "dapiXYZ" not in texto


def test_nenhum_log_do_codigo_passa_um_dsn():
    """Na fonte: nenhum ``log_event`` volta a levar DSN/URL de base."""
    import re

    padrao = re.compile(
        r"log_event\([^)]*(dsn|conninfo|database_url|db_url)\s*[\[\),]", re.S
    )
    culpados = []
    for f in list((RAIZ / "core").rglob("*.py")) + list((RAIZ / "api").rglob("*.py")):
        if padrao.search(f.read_text(encoding="utf-8")):
            culpados.append(str(f.relative_to(RAIZ)))
    assert not culpados, f"log de DSN em: {culpados}"


# ── Checkpointer (A2, A11) ────────────────────────────────────────────────


def test_o_grafo_nao_tem_checkpointer_persistente():
    """O estado do grafo leva até 10.000 linhas; um PostgresSaver gravava-as
    para sempre na base da plataforma."""
    assert not (RAIZ / "core" / "agents" / "checkpoint_manager.py").exists()
    for f in list((RAIZ / "core").rglob("*.py")) + list((RAIZ / "api").rglob("*.py")):
        fonte = f.read_text(encoding="utf-8")
        assert "langgraph.checkpoint" not in fonte, f"checkpointer importado em {f}"
        assert "checkpointer=" not in fonte, f"checkpointer passado em {f}"


def test_run_agent_once_compila_sem_checkpointer(monkeypatch):
    from core.agents import generic_sql_agent as g

    compilados = []

    class _Grafo:
        def invoke(self, state, config=None):
            return {**state, "answer": "ok"}

    def _construir(**kwargs):
        compilados.append(kwargs)
        return _Grafo()

    monkeypatch.setattr(g, "build_generic_sql_graph", _construir)
    monkeypatch.setattr("core.clients.backend_client.get_backend_client", lambda: None)
    estado = g.run_agent_once(
        question="q",
        user_ctx=types.SimpleNamespace(user_id="u", space_id="s", crew_ids=[]),
        agent_config=types.SimpleNamespace(id="a", tables=[]),
        data_source=None,
        db_session_factory=None,
        embedding_provider=None,
        llm_orchestrator=None,
        llm_specialist=None,
        llm_formatter=None,
    )
    assert estado["answer"] == "ok"
    assert compilados and "checkpointer" not in compilados[0]


# ── /pipeline (A3) ───────────────────────────────────────────────────────


def test_o_endpoint_pipeline_ja_nao_existe():
    from api.main import app

    caminhos = {getattr(r, "path", "") for r in app.routes}
    assert not any(c.startswith("/pipeline") for c in caminhos)
    assert not (RAIZ / "api" / "routes" / "pipeline.py").exists()


# ── Langfuse (A12) ───────────────────────────────────────────────────────


def test_mascara_tira_as_linhas_onde_quer_que_aparecam():
    from core.privacidade.observabilidade import (
        LINHAS_OMITIDAS,
        embrulhar_linhas,
        mascarar,
    )

    linhas = embrulhar_linhas("nome | total\n---\nJoana | 1200")
    dados = {
        "output": linhas + "\n(1 row)",
        "messages": [["Pensamento", {"content": "Resultado: " + linhas}]],
    }
    mascarado = mascarar(dados)
    texto = json.dumps(mascarado, ensure_ascii=False)
    assert "Joana" not in texto
    assert LINHAS_OMITIDAS in texto
    assert "(1 row)" in texto, "o que não é linha fica"


def test_mascara_tira_um_bloco_cortado_a_meio():
    from core.privacidade.observabilidade import INICIO, mascarar

    assert "Joana" not in mascarar(f"x {INICIO}\nnome\n---\nJoana | 1")


def _langfuse_falso(monkeypatch, aceita_mask: bool):
    recebido = {}

    if aceita_mask:

        class CallbackHandler:
            def __init__(self, **kwargs):
                recebido.update(kwargs)

    else:

        class CallbackHandler:  # SDK antigo: sem `mask`
            def __init__(
                self,
                public_key=None,
                secret_key=None,
                host=None,
                trace_name=None,
                user_id=None,
                tags=None,
                metadata=None,
            ):
                recebido["criado"] = True

    pacote = types.ModuleType("langfuse")
    modulo = types.ModuleType("langfuse.callback")
    modulo.CallbackHandler = CallbackHandler
    monkeypatch.setitem(sys.modules, "langfuse", pacote)
    monkeypatch.setitem(sys.modules, "langfuse.callback", modulo)
    from config.settings import settings

    monkeypatch.setattr(settings, "langfuse_enabled", True)
    return recebido


def test_langfuse_liga_com_a_mascara(monkeypatch):
    from core.agents.full_context_agent import _get_langfuse_callback
    from core.privacidade.observabilidade import mascarar

    recebido = _langfuse_falso(monkeypatch, aceita_mask=True)
    cb = _get_langfuse_callback("a", "u", "s")
    assert cb is not None
    assert recebido.get("mask") is mascarar


def test_langfuse_sem_mascara_nao_liga(monkeypatch):
    """Falha fechado: um SDK que não aceita ``mask`` não envia nada."""
    from core.agents.full_context_agent import _get_langfuse_callback

    _langfuse_falso(monkeypatch, aceita_mask=False)
    assert _get_langfuse_callback("a", "u", "s") is None


def test_a_ferramenta_embrulha_as_linhas_que_devolve():
    fonte = (RAIZ / "core" / "agents" / "full_context_agent.py").read_text(
        encoding="utf-8"
    )
    assert 'preview = embrulhar_linhas("\\n".join([header, "---"] + lines))' in fonte
