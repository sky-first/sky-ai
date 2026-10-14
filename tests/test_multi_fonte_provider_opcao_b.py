# -*- coding: utf-8 -*-
"""Opção B (14/10/2026): Claude na Bedrock SÓ no caminho multi-fonte novo.

O portão das «Fontes do sistema» deu 0/20 com os modelos globais de produção
(bedrock-mantle: gpt-oss-120b + qwen3-coder-30b) e 20/20 com Claude. O Lucas
escolheu pôr Claude só nesse caminho. O que estes testes fixam (comportamento,
não código):

1. Sem ``MULTI_FONTE_PROVIDER``: igual a antes — nenhum fornecedor novo é
   construído, os nós usam os LLMs globais.
2. Com a config e a flag do cliente: fatias, merger (e correcção) e
   formatador do pedido multi-fonte vão para a Bedrock com os modelos do
   papel; o orquestrador fica no global salvo
   ``MULTI_FONTE_MODEL_ORCHESTRATOR``; perguntas de uma fonte não mudam.
3. Cliente fora da flag: tudo global, mesmo com a config.
4. Falha da Bedrock (limite esgotado, AccessDenied, 5xx): mensagem honesta
   na língua da pessoa, e o modelo global nunca é chamado em seu lugar.
5. Cada chamada fica registada com fornecedor, rota, papel e tokens.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")

SONNET = "eu.anthropic.claude-sonnet-4-6"
HAIKU = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"


# ── Peças falsas ─────────────────────────────────────────────────────────


class _ErroBedrock(Exception):
    """Imita ``botocore.exceptions.ClientError`` (tem ``.response``)."""

    def __init__(self, codigo, estado=400):
        super().__init__(f"An error occurred ({codigo}) when calling Converse")
        self.response = {
            "Error": {"Code": codigo, "Message": "x"},
            "ResponseMetadata": {"HTTPStatusCode": estado},
        }


class _ClienteConverse:
    """``bedrock-runtime`` falso: falha com os erros dados, depois responde."""

    def __init__(self, *erros, texto="SELECT 1"):
        self.erros = list(erros)
        self.chamadas = 0
        self.texto = texto
        self.meta = SimpleNamespace(region_name="eu-west-1")

    def converse(self, **_k):
        self.chamadas += 1
        if self.erros:
            raise self.erros.pop(0)
        return {
            "output": {
                "message": {"role": "assistant", "content": [{"text": self.texto}]}
            },
            "usage": {"inputTokens": 120, "outputTokens": 7, "totalTokens": 127},
            "stopReason": "end_turn",
            "metrics": {"latencyMs": 5},
        }


class _LLMGlobal:
    """O LLM global (mantle). Neste caminho NÃO pode ser chamado."""

    def __init__(self, nome):
        self.nome = nome
        self.chamadas = 0
        self._chat = None

    def invoke(self, _msgs, **_k):
        self.chamadas += 1
        return SimpleNamespace(content=f"-- TITLE: {self.nome}\nSELECT 1")

    def stream(self, _msgs):
        self.chamadas += 1
        yield "x"


@pytest.fixture
def bedrock_falsa(monkeypatch):
    """Substitui a construção do ``BedrockChatProvider``: o verdadeiro, com um
    cliente Converse falso. Devolve o registo {modelo: cliente}."""
    import core.llm.providers as prov

    real = prov.BedrockChatProvider
    registo: Dict[str, Any] = {"clientes": {}, "erros": {}, "construidos": []}
    monkeypatch.setattr(prov, "_dormir", lambda s: None)
    monkeypatch.setattr(prov, "_LIMITE_REPETICOES", 1)

    def construir(model, region="eu-west-1", temperature=0.0, **kw):
        p = real(model=model, region=region, temperature=temperature, **kw)
        cliente = _ClienteConverse(*registo["erros"].get(model, []))
        p._chat.client = cliente
        registo["clientes"].setdefault(model, []).append(cliente)
        registo["construidos"].append(model)
        return p

    monkeypatch.setattr(prov, "BedrockChatProvider", construir)
    return registo


@pytest.fixture
def config_b(monkeypatch):
    """MULTI_FONTE_PROVIDER=bedrock (modelos por omissão) e flag no sandbox."""
    from config.settings import settings

    monkeypatch.setattr(settings, "multi_fonte_provider", "bedrock")
    for papel in ("orchestrator", "specialist", "merger", "formatter"):
        monkeypatch.setattr(settings, f"multi_fonte_model_{papel}", None)
    monkeypatch.delenv("MULTI_FONTE_POR_LIGACAO", raising=False)
    monkeypatch.setenv("MULTI_FONTE_POR_LIGACAO_TENANTS", "sandbox")
    return settings


@pytest.fixture
def no_sandbox():
    from uuid import uuid4

    from core.tenant_context import (
        TenantContext,
        reset_current_tenant,
        set_current_tenant,
    )

    tok = set_current_tenant(
        TenantContext(slug="sandbox", id=uuid4(), tier="pro", display_name="S")
    )
    yield
    reset_current_tenant(tok)


@pytest.fixture(scope="module")
def amb():
    from scripts.portao_fontes.fixtures import Ambiente

    return Ambiente()


def _grafo(amb):
    from core.agents.generic_sql_agent import build_generic_sql_graph

    globais = {
        "orq": _LLMGlobal("orq"),
        "esp": _LLMGlobal("esp"),
        "fmt": _LLMGlobal("fmt"),
    }
    app = build_generic_sql_graph(
        amb.config,
        amb.fonte_cliente,
        lambda: SimpleNamespace(close=lambda: None),
        None,
        globais["orq"],
        globais["esp"],
        globais["fmt"],
        dispatch_map=amb.dispatch_map,
    )

    def no(nome):
        return app.builder.nodes[nome].runnable.func

    return no, globais


def _estado_multi(**extra):
    st = {
        "question": "¿Cuánto gasóleo en Badajoz–Madrid y a qué precio medio?",
        "detected_language": "es",
        "locale": "es",
        "chat_history": [],
        "retrieval_context": [],
        "is_multi_source": True,
        "chosen_tables": ["trips", "gasoleo_historico_diario"],
        "chosen_tables_physical": ["ops.trips", "mundo.gasoleo_historico_diario"],
    }
    st.update(extra)
    return st


@pytest.fixture
def fatias_falsas(monkeypatch):
    """``executar_fatias`` que chama o LLM UMA vez por ligação (como o real:
    erros da fatia viram ``failed_slices``) e guarda o LLM recebido."""
    import core.llm.multi_fonte as mf

    visto: Dict[str, Any] = {}

    def falsa(state, cfg, tabelas, dispatch_map, data_source, llm, run_specialist):
        visto["llm"] = llm
        ok, falhas = [], []
        for t in ("trips", "gasoleo_historico_diario"):
            try:
                llm.invoke([{"role": "user", "content": f"SQL para {t}"}])
                ok.append({"table": t, "data": [{"k": 1, t: 2}], "sql": "SELECT 1"})
            except Exception as e:  # noqa: BLE001
                falhas.append({"table": t, "reason": str(e)[:300]})
        return ok, [], falhas

    monkeypatch.setattr(mf, "executar_fatias", falsa)
    return visto


# ── 1. Sem config: igual a antes ─────────────────────────────────────────


def test_sem_config_nao_ha_fornecedor_multi_fonte(monkeypatch):
    from config.settings import settings
    from core.llm.fornecedor_multi_fonte import criar_llm, fornecedor_configurado

    monkeypatch.setattr(settings, "multi_fonte_provider", None)
    assert fornecedor_configurado() is None
    assert criar_llm("specialist") is None
    monkeypatch.setattr(settings, "multi_fonte_provider", "  ")
    assert fornecedor_configurado() is None
    # valor desconhecido: ignorado (e registado), nunca meio-ligado
    monkeypatch.setattr(settings, "multi_fonte_provider", "anthropic-direct")
    assert fornecedor_configurado() is None


def test_sem_config_o_caminho_multi_fonte_usa_os_globais(
    monkeypatch, amb, bedrock_falsa, fatias_falsas, no_sandbox
):
    from config.settings import settings
    import core.llm.merger as merger_mod

    monkeypatch.setattr(settings, "multi_fonte_provider", None)
    monkeypatch.setenv("MULTI_FONTE_POR_LIGACAO_TENANTS", "sandbox")
    no, g = _grafo(amb)

    st = no("parallel_specialist")(_estado_multi())
    assert fatias_falsas["llm"] is g["esp"]
    assert not st.get("multi_fonte_provider")

    usado = {}
    monkeypatch.setattr(
        merger_mod, "run_merger", lambda s, c, llm: usado.setdefault("llm", llm) and s
    )
    no("merger")(st)
    assert usado["llm"] is g["esp"]  # #285: no caminho novo, o especialista
    assert bedrock_falsa["construidos"] == []


# ── 2. Com config + flag: o pedido multi-fonte inteiro na Bedrock ────────


def test_fatias_merger_e_formatador_vao_para_a_bedrock(
    monkeypatch, amb, bedrock_falsa, fatias_falsas, config_b, no_sandbox
):
    import core.llm.formatter as fmt_mod
    import core.llm.merger as merger_mod

    no, g = _grafo(amb)
    st = no("parallel_specialist")(_estado_multi())

    llm_esp = fatias_falsas["llm"]
    assert llm_esp.provider == "bedrock" and llm_esp.modelo == SONNET
    assert st["multi_fonte_provider"] == "bedrock"
    assert len(st["partial_results"]) == 2

    usado: Dict[str, Any] = {}

    def merger_falso(s, c, llm):
        usado["merger"] = llm
        llm.invoke([{"role": "user", "content": "junta"}])
        return {**s, "data": [{"total": 3}], "sql": "SELECT 3"}

    monkeypatch.setattr(merger_mod, "run_merger", merger_falso)
    st = no("merger")(st)
    assert usado["merger"].modelo == SONNET and usado["merger"].papel == "merger"

    def formatter_falso(state, agent_config, llm):
        usado["formatter"] = llm
        llm.invoke([{"role": "user", "content": "explica"}])
        return {**state, "answer": "Fueron 3."}

    monkeypatch.setattr(fmt_mod, "run_formatter", formatter_falso)
    st = no("formatter")(st)
    assert usado["formatter"].modelo == HAIKU
    assert st["answer"] == "Fueron 3."
    # nenhum LLM global foi chamado neste pedido
    assert [x.chamadas for x in g.values()] == [0, 0, 0]
    assert sorted(set(bedrock_falsa["construidos"])) == [HAIKU, SONNET]


def test_modelos_explicitos_por_papel(
    monkeypatch, amb, bedrock_falsa, fatias_falsas, config_b, no_sandbox
):
    monkeypatch.setattr(config_b, "multi_fonte_model_specialist", "eu.x.esp")
    no, _ = _grafo(amb)
    no("parallel_specialist")(_estado_multi())
    assert fatias_falsas["llm"].modelo == "eu.x.esp"


def test_orquestrador_fica_global_sem_modelo_proprio(
    monkeypatch, amb, bedrock_falsa, config_b, no_sandbox
):
    import core.llm.orchestrator as orq_mod

    usado = {}
    monkeypatch.setattr(
        orq_mod,
        "run_orchestrator",
        lambda state, agent_config, llm, db, embedding_provider: usado.setdefault(
            "llm", llm
        )
        and dict(state),
    )
    no, g = _grafo(amb)
    no("orchestrator")({"question": "x", "detected_language": "es"})
    assert usado["llm"] is g["orq"]
    assert bedrock_falsa["construidos"] == []


def test_orquestrador_proprio_com_multi_fonte_model_orchestrator(
    monkeypatch, amb, bedrock_falsa, config_b, no_sandbox
):
    import core.llm.orchestrator as orq_mod

    monkeypatch.setattr(config_b, "multi_fonte_model_orchestrator", HAIKU)
    usado = {}

    def orq(state, agent_config, llm, db, embedding_provider):
        usado["llm"] = llm
        return dict(state)

    monkeypatch.setattr(orq_mod, "run_orchestrator", orq)
    no, g = _grafo(amb)
    no("orchestrator")({"question": "x", "detected_language": "es"})
    assert usado["llm"].modelo == HAIKU and usado["llm"].papel == "orchestrator"
    # o ReAct fala com o ``_chat``: o embrulho expõe-no
    assert usado["llm"]._chat is not None


def test_pergunta_de_uma_fonte_continua_no_global(
    monkeypatch, amb, bedrock_falsa, config_b, no_sandbox
):
    import core.llm.formatter as fmt_mod
    import core.llm.specialist as spec_mod

    usado = {}

    def spec(state, agent_config, data_source, llm):
        usado["esp"] = llm
        return {**state, "data": [{"n": 1}]}

    def fmt(state, agent_config, llm):
        usado["fmt"] = llm
        return {**state, "answer": "1"}

    monkeypatch.setattr(spec_mod, "run_specialist", spec)
    monkeypatch.setattr(fmt_mod, "run_formatter", fmt)
    monkeypatch.setattr(
        "core.llm.analysis_context_generator.generate_and_save_analysis_context",
        lambda *a, **k: None,
    )
    no, g = _grafo(amb)
    st = {
        "question": "¿Cuántos viajes?",
        "detected_language": "es",
        "chosen_table": "trips",
        "chosen_tables": ["trips"],
    }
    st = no("specialist")(st)
    no("formatter")(st)
    assert usado["esp"] is g["esp"] and usado["fmt"] is g["fmt"]
    assert bedrock_falsa["construidos"] == []


# ── 3. Cliente fora da flag ──────────────────────────────────────────────


def test_cliente_fora_da_flag_fica_todo_no_global(
    monkeypatch, amb, bedrock_falsa, config_b
):
    import core.llm.merger as merger_mod

    visto = {}

    def por_tabela(state, cfg, tabelas, dm, ds, llm, rs, **_k):
        visto["llm"] = llm
        return [], []

    monkeypatch.setattr(merger_mod, "executar_fatias_por_tabela", por_tabela)
    # sem cliente no contexto (o de omissão não está em _TENANTS)
    no, g = _grafo(amb)
    st = no("parallel_specialist")(_estado_multi())
    assert visto["llm"] is g["esp"]
    assert not st.get("multi_fonte_provider")
    assert bedrock_falsa["construidos"] == []


# ── 4. Falha honesta, nunca o qwen ───────────────────────────────────────


@pytest.mark.parametrize(
    "erro,chave",
    [
        (_ErroBedrock("ThrottlingException", 429), "MULTI_SOURCE_MODEL_BUSY"),
        (_ErroBedrock("ServiceUnavailableException", 503), "MULTI_SOURCE_MODEL_BUSY"),
        (_ErroBedrock("AccessDeniedException", 403), "MULTI_SOURCE_MODEL_DENIED"),
    ],
)
def test_falha_da_bedrock_nas_fatias_da_resposta_honesta(
    monkeypatch, amb, bedrock_falsa, fatias_falsas, config_b, no_sandbox, erro, chave
):
    import core.llm.merger as merger_mod
    from core.i18n.i18n import get_message

    # todas as tentativas falham (limite: a 1.ª + 1 repetição)
    bedrock_falsa["erros"][SONNET] = [erro, erro, erro, erro]
    chamado = {"merger": 0}
    monkeypatch.setattr(
        merger_mod,
        "run_merger",
        lambda s, c, llm: chamado.__setitem__("merger", 1) or s,
    )
    no, g = _grafo(amb)
    st = no("parallel_specialist")(_estado_multi())
    assert st["merge_failure"]["kind"] == "model_unavailable"
    assert st["data"] == [] and st["partial_results"] == []
    assert st["falhas_modelo_multi_fonte"]

    st = no("merger")(st)
    assert chamado["merger"] == 0  # não se junta meia pergunta

    st = no("formatter")(st)
    assert st["answer"] == get_message(chave, "es")
    # o modelo global nunca respondeu em vez da Bedrock
    assert [x.chamadas for x in g.values()] == [0, 0, 0]


def test_falha_so_no_formatador_mantem_os_dados_e_diz_porque(
    monkeypatch, amb, bedrock_falsa, config_b, no_sandbox
):
    from core.i18n.i18n import get_message

    bedrock_falsa["erros"][HAIKU] = [_ErroBedrock("ThrottlingException", 429)] * 4
    no, g = _grafo(amb)
    st = _estado_multi(
        multi_fonte_provider="bedrock",
        multi_fonte_por_ligacao=True,
        data=[{"origin": "Badajoz", "litros": 3191.81}],
        sql="SELECT 1",
    )
    st = no("formatter")(st)
    assert st["data"] == [{"origin": "Badajoz", "litros": 3191.81}]
    assert st["answer"] == get_message("MULTI_SOURCE_MODEL_BUSY", "es")
    assert g["fmt"].chamadas == 0


def test_falha_no_merger_da_resposta_honesta(
    monkeypatch, amb, bedrock_falsa, config_b, no_sandbox
):
    from core.i18n.i18n import get_message

    bedrock_falsa["erros"][SONNET] = [_ErroBedrock("InternalServerException", 500)]
    no, g = _grafo(amb)
    st = _estado_multi(
        multi_fonte_provider="bedrock",
        multi_fonte_por_ligacao=True,
        partial_results=[
            {"table": "trips", "data": [{"d": "2026-09-01", "l": 1}], "sql": "x"},
            {"table": "gasoleo", "data": [{"d": "2026-09-01", "p": 2}], "sql": "y"},
        ],
        failed_slices=[],
    )
    st = no("merger")(st)
    assert st["merge_failure"]["kind"] == "model_unavailable"
    st = no("formatter")(st)
    assert st["answer"] == get_message("MULTI_SOURCE_MODEL_BUSY", "es")
    assert [x.chamadas for x in g.values()] == [0, 0, 0]


def test_orquestrador_proprio_que_falha_responde_e_acaba(
    monkeypatch, amb, bedrock_falsa, config_b, no_sandbox
):
    import core.llm.orchestrator as orq_mod
    from core.i18n.i18n import get_message

    monkeypatch.setattr(config_b, "multi_fonte_model_orchestrator", HAIKU)
    bedrock_falsa["erros"][HAIKU] = [_ErroBedrock("AccessDeniedException", 403)]

    def orq(state, agent_config, llm, db, embedding_provider):
        try:
            llm.invoke([{"role": "user", "content": "x"}])
        except Exception:  # o orquestrador real engole e responde algo
            return {**state, "answer": "error"}
        return dict(state)

    monkeypatch.setattr(orq_mod, "run_orchestrator", orq)
    no, _ = _grafo(amb)
    st = no("orchestrator")({"question": "x", "detected_language": "pt"})
    assert st["answer"] == get_message("MULTI_SOURCE_MODEL_DENIED", "pt")
    assert not st.get("chosen_tables")


@pytest.mark.parametrize(
    "erro,tipo",
    [
        (_ErroBedrock("ThrottlingException", 400), "limite"),
        (_ErroBedrock("TooManyRequestsException", 429), "limite"),
        (_ErroBedrock("AccessDeniedException", 403), "acesso"),
        (_ErroBedrock("ExpiredTokenException", 400), "acesso"),
        (_ErroBedrock("ServiceUnavailableException", 503), "servidor"),
        (_ErroBedrock("InternalServerException", 500), "servidor"),
        (_ErroBedrock("Desconhecido", 502), "servidor"),
        (ValueError("outra coisa"), "outro"),
    ],
)
def test_classificar_falha(erro, tipo):
    from core.llm.fornecedor_multi_fonte import classificar_falha

    assert classificar_falha(erro) == tipo


def test_classificar_falha_embrulhada():
    from core.llm.fornecedor_multi_fonte import classificar_falha

    try:
        try:
            raise _ErroBedrock("ThrottlingException")
        except Exception as e:
            raise RuntimeError("langchain embrulhou") from e
    except Exception as fora:
        assert classificar_falha(fora) == "limite"


# ── 5. Registo: fornecedor, rota, papel e tokens por chamada ─────────────


def test_cada_chamada_regista_fornecedor_rota_papel_e_tokens(
    monkeypatch, bedrock_falsa, config_b
):
    import latency_timing
    from core.llm.fornecedor_multi_fonte import criar_llm

    eventos: List[Dict[str, Any]] = []
    real = latency_timing.registar_tempo

    def gravar(evento, ms, **campos):
        if evento == "llm_call_timing":
            eventos.append(campos)
        return real(evento, ms, **campos)

    monkeypatch.setattr(latency_timing, "registar_tempo", gravar)
    acc = latency_timing.iniciar_pedido()
    llm = criar_llm("merger")
    llm.invoke([{"role": "user", "content": "junta"}])

    (ev,) = eventos
    assert ev["provider"] == "bedrock"
    assert ev["rota"] == "multi_fonte"
    assert ev["papel"] == "merger"
    assert ev["model"] == SONNET
    assert ev["input_tokens"] == 120 and ev["output_tokens"] == 7
    # e o resumo do pedido soma por rota/fornecedor/modelo
    resumo = latency_timing.resumo_do_pedido()
    assert resumo["llm_tokens"][f"multi_fonte|bedrock|{SONNET}"] == {
        "calls": 1,
        "input_tokens": 120,
        "output_tokens": 7,
    }
    assert acc["llm"][0]["rota"] == "multi_fonte"


def test_chamada_global_fica_com_rota_global(monkeypatch):
    import core.llm.providers as prov
    import latency_timing

    eventos: List[Dict[str, Any]] = []
    monkeypatch.setattr(
        latency_timing,
        "registar_tempo",
        lambda evento, ms, **c: eventos.append(c),
    )
    p = prov.BedrockChatProvider(model=HAIKU)
    p._chat.client = _ClienteConverse(texto="ok")
    p.invoke([{"role": "user", "content": "x"}])
    assert eventos[0]["rota"] == "global" and "papel" not in eventos[0]
    assert eventos[0]["provider"] == "bedrock"


def test_service_unavailable_transitorio_repete_e_passa(monkeypatch):
    """Medido no portão de 14/10: o Haiku deu ServiceUnavailableException
    depois das repetições do botocore. Repete-se com espera, como o limite."""
    import core.llm.providers as prov

    esperas: List[float] = []
    monkeypatch.setattr(prov, "_dormir", lambda s: esperas.append(s))
    p = prov.BedrockChatProvider(model=HAIKU)
    cliente = _ClienteConverse(
        _ErroBedrock("ServiceUnavailableException", 503), texto="ok"
    )
    p._chat.client = cliente
    assert p.invoke([{"role": "user", "content": "x"}]).content == "ok"
    assert cliente.chamadas == 2 and len(esperas) == 1
