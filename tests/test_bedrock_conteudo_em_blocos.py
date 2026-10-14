"""14/10/2026 — sky-ai com Claude pela Bedrock Converse (``AI_PROVIDER=bedrock``).

A primeira pergunta do portão das fontes rebentou no orquestrador:
``AttributeError: 'list' object has no attribute 'splitlines'``. Com a
Converse, o ``.content`` de uma mensagem é uma LISTA de blocos sempre que a
resposta traz mais do que um texto — raciocínio (``reasoning_content``),
``tool_use`` ou vários blocos de texto. Com o OpenAI (produção) é sempre
``str``, por isso nunca se viu.

E as quotas do Claude na conta de produção são 10 pedidos/min por modelo: à
segunda pergunta seguida, ``ThrottlingException``.

Modelos falsos que respondem como a Converse responde; o que se testa é o
comportamento do pipeline — escolhe a tabela, corre o SQL, junta as fatias,
escreve a resposta — e que o raciocínio do modelo nunca passa por resposta.
"""

from __future__ import annotations

import pathlib
import re
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from core.agents.generic_sql_agent import AgentConfig

RACIOCINIO = (
    "Hmm, could this be OUT_OF_SCOPE? No. IMPOSSIBLE is not right either. "
    "SELECT * FROM segredo"
)


def _em_blocos(texto: str) -> list:
    """O ``.content`` que a Converse devolve com raciocínio ligado."""
    return [
        {
            "type": "reasoning_content",
            "reasoning_content": {"text": RACIOCINIO, "signature": "sig"},
        },
        {"type": "text", "text": texto},
    ]


class _ModeloConverse:
    """Como ``_Modelo`` dos testes do multi-fonte, mas cada resposta vem em
    blocos — uma ``AIMessage`` como a do ``ChatBedrockConverse``."""

    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.chamadas = []

    def invoke(self, mensagens, *_a, **_k):
        self.chamadas.append(mensagens)
        i = min(len(self.chamadas) - 1, len(self.respostas) - 1)
        return AIMessage(content=_em_blocos(self.respostas[i]))


# ── O helper ─────────────────────────────────────────────────────────────


class TestTextoDaResposta:
    def test_lista_de_blocos_so_o_texto(self):
        from core.llm.conteudo import texto_da_resposta

        msg = AIMessage(
            content=[
                {"type": "reasoning_content", "reasoning_content": {"text": "x"}},
                {"type": "text", "text": "invoices"},
                {"type": "tool_use", "id": "t1", "name": "f", "input": {}},
            ]
        )
        assert texto_da_resposta(msg) == "invoices"

    @pytest.mark.parametrize(
        "entrada,esperado",
        [
            ("texto", "texto"),
            (None, ""),
            (SimpleNamespace(content="a"), "a"),
            (SimpleNamespace(content=None), ""),
            (
                SimpleNamespace(content=["solto", {"type": "text", "text": "b"}]),
                "solto\nb",
            ),
            ({"role": "assistant", "content": "c"}, "c"),
            (SimpleNamespace(content=[{"type": "image", "source": {}}]), ""),
        ],
    )
    def test_formas(self, entrada, esperado):
        from core.llm.conteudo import texto_da_resposta

        assert texto_da_resposta(entrada) == esperado


# ── O pipeline com respostas em blocos ───────────────────────────────────


def test_orquestrador_react_com_blocos_escolhe_a_tabela(monkeypatch):
    """O caso do portão: a última mensagem do ReAct vem em blocos. Antes:
    AttributeError no ``splitlines`` e «Error consulting the AI orchestrator».
    O raciocínio fala em OUT_OF_SCOPE e não pode contar."""
    import langgraph.prebuilt as lp
    from test_latencia_nomes_unidades_12_10 import _orquestrar

    class _Agente:
        def invoke(self, _entrada, config=None):
            return {"messages": [AIMessage(content=_em_blocos("gasolineras_precio"))]}

    monkeypatch.setattr(lp, "create_react_agent", lambda *a, **k: _Agente())

    class _Chat:
        model_id = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"

        def bind_tools(self, *_a, **_k):
            return self

    modelo = SimpleNamespace(_chat=_Chat(), invoke=None)
    state = _orquestrar("¿Cuál es la gasolinera más barata de Badajoz?", modelo)
    assert not state.get("error"), state.get("error")
    assert state["chosen_tables"][0] == "gasolineras_precio"
    assert RACIOCINIO not in str(state.get("plan"))


def test_orquestrador_react_out_of_scope_no_texto_continua_a_valer(monkeypatch):
    import langgraph.prebuilt as lp
    from test_latencia_nomes_unidades_12_10 import _orquestrar

    class _Agente:
        def invoke(self, _entrada, config=None):
            return {"messages": [AIMessage(content=_em_blocos("OUT_OF_SCOPE"))]}

    monkeypatch.setattr(lp, "create_react_agent", lambda *a, **k: _Agente())

    class _Chat:
        def bind_tools(self, *_a, **_k):
            return self

    state = _orquestrar(
        "¿Quién ganó el mundial de 2010?",
        SimpleNamespace(_chat=_Chat(), invoke=None),
    )
    assert not state.get("error"), state.get("error")
    assert state.get("answer")
    assert not state.get("chosen_tables")


def test_escolha_de_tabela_legada_com_blocos():
    from core.llm.orchestrator import (
        _extract_multiple_table_choices,
        _extract_table_choice,
    )
    from test_multifonte_fatias_e_merger import _cfg

    tabelas = _cfg().tables
    assert _extract_table_choice(AIMessage(content=_em_blocos("stores")), tabelas) == (
        "stores"
    )
    assert _extract_multiple_table_choices(
        AIMessage(content=_em_blocos("orders, stores")), tabelas
    ) == ["orders", "stores"]


def test_especialista_com_blocos_corre_o_sql_do_texto():
    """O SQL vem do bloco de texto; o ``SELECT * FROM segredo`` do raciocínio
    nunca chega à base."""
    from test_multifonte_fatias_e_merger import (
        LINHAS_STORES,
        PERGUNTA_TIENDA,
        SQL_STORES_LIMPO,
        _correr_fatia,
    )

    modelo = _ModeloConverse(SQL_STORES_LIMPO)
    st, fonte = _correr_fatia(
        modelo,
        LINHAS_STORES,
        "stores",
        "stores.stores",
        ["orders (service.orders)"],
        PERGUNTA_TIENDA,
    )
    assert not st.get("error"), st.get("error")
    assert st.get("data") == LINHAS_STORES
    assert fonte.consultas and all("segredo" not in q for q in fonte.consultas)


def test_merger_com_blocos_junta_as_fatias():
    from test_multifonte_fatias_e_merger import (
        FATIA_ORDERS,
        FATIA_STORES,
        SQL_MERGER_TIENDA,
        _merger,
    )

    st = _merger([FATIA_ORDERS, FATIA_STORES], _ModeloConverse(SQL_MERGER_TIENDA))
    assert not st.get("error"), st.get("error")
    assert st["data"] == [{"store_name": "Norte", "pedidos": 30}]


def test_formatador_com_blocos_responde_so_com_o_texto():
    from core.llm.formatter import run_formatter

    st = run_formatter(
        {
            "detected_language": "es",
            "question": "¿Qué tienda tuvo más pedidos?",
            "data": [{"store_name": "Norte", "pedidos": 30}],
            "sql": "SELECT store_name, pedidos FROM t",
        },
        AgentConfig(id="t", name="t", tables=[]),
        _ModeloConverse("La tienda Norte tuvo 30 pedidos."),
    )
    assert "Norte" in (st.get("answer") or "")
    assert "OUT_OF_SCOPE" not in (st.get("answer") or "")
    assert "reasoning" not in (st.get("answer") or "")


# ── O fornecedor Bedrock ─────────────────────────────────────────────────


class _ErroBedrock(Exception):
    """Imita ``botocore.exceptions.ClientError`` (tem ``.response``)."""

    def __init__(self, codigo):
        super().__init__(f"An error occurred ({codigo}) when calling Converse")
        self.response = {"Error": {"Code": codigo, "Message": "x"}}


class _ClienteConverse:
    """``bedrock-runtime`` falso: falha com os erros dados, depois responde."""

    def __init__(self, *erros, texto="ok"):
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
                "message": {
                    "role": "assistant",
                    "content": [
                        {"reasoningContent": {"reasoningText": {"text": "pensar"}}},
                        {"text": self.texto},
                    ],
                }
            },
            "usage": {"inputTokens": 10, "outputTokens": 3, "totalTokens": 13},
            "stopReason": "end_turn",
            "metrics": {"latencyMs": 5},
        }


def _fornecedor(cliente, monkeypatch, esperas=None):
    import core.llm.providers as prov

    esperas = esperas if esperas is not None else []
    monkeypatch.setattr(prov, "_dormir", lambda s: esperas.append(s))
    p = prov.BedrockChatProvider(model="eu.anthropic.claude-haiku-4-5-20251001-v1:0")
    p._chat.client = cliente
    return p


def test_invoke_do_fornecedor_devolve_texto_e_mantem_os_tokens(monkeypatch):
    p = _fornecedor(_ClienteConverse(texto="invoices"), monkeypatch)
    r = p.invoke([{"role": "user", "content": "qual tabela?"}])
    assert r.content == "invoices"
    assert r.usage_metadata["input_tokens"] == 10
    assert r.usage_metadata["output_tokens"] == 3


def test_limite_de_pedidos_espera_e_repete(monkeypatch):
    esperas = []
    cliente = _ClienteConverse(
        _ErroBedrock("ThrottlingException"),
        _ErroBedrock("ThrottlingException"),
        texto="orders",
    )
    p = _fornecedor(cliente, monkeypatch, esperas)
    r = p.invoke([{"role": "user", "content": "x"}])
    assert r.content == "orders"
    assert cliente.chamadas == 3
    assert len(esperas) == 2 and all(e > 0 for e in esperas)
    assert esperas[1] > esperas[0] * 0.5  # cresce (com jitter)


def test_o_react_tambem_repete_no_limite(monkeypatch):
    """O orquestrador fala com o ``_chat`` (``bind_tools``), não com o
    fornecedor: a repetição tem de viver no modelo."""
    cliente = _ClienteConverse(_ErroBedrock("ThrottlingException"), texto="trips")
    p = _fornecedor(cliente, monkeypatch)
    from langchain_core.tools import tool

    @tool
    def procurar(termo: str) -> str:
        """Procura tabelas."""
        return termo

    r = p._chat.bind_tools([procurar]).invoke("x")
    assert "trips" in str(r.content)
    assert cliente.chamadas == 2


@pytest.mark.parametrize(
    "codigo",
    ["ValidationException", "AccessDeniedException", "ResourceNotFoundException"],
)
def test_outros_erros_sobem_logo(monkeypatch, codigo):
    esperas = []
    cliente = _ClienteConverse(_ErroBedrock(codigo))
    p = _fornecedor(cliente, monkeypatch, esperas)
    with pytest.raises(Exception) as ei:
        p.invoke([{"role": "user", "content": "x"}])
    assert codigo in str(ei.value)
    assert cliente.chamadas == 1 and esperas == []


def test_limite_que_nao_passa_acaba_por_subir(monkeypatch):
    import core.llm.providers as prov

    monkeypatch.setattr(prov, "_LIMITE_REPETICOES", 2)
    cliente = _ClienteConverse(*[_ErroBedrock("ThrottlingException")] * 5)
    p = _fornecedor(cliente, monkeypatch)
    with pytest.raises(Exception, match="ThrottlingException"):
        p.invoke([{"role": "user", "content": "x"}])
    assert cliente.chamadas == 3


def test_stream_do_fornecedor_so_texto(monkeypatch):
    import core.llm.providers as prov

    p = _fornecedor(_ClienteConverse(), monkeypatch)

    class _Pedaco:
        def __init__(self, c):
            self.content = c

    class _ChatFalso:
        def stream(self, _m):
            yield _Pedaco([{"type": "reasoning_content", "reasoning_content": {}}])
            yield _Pedaco([{"type": "text", "text": "Hola"}])
            yield _Pedaco(" mundo")

    p._chat = _ChatFalso()
    assert "".join(p.stream([{"role": "user", "content": "x"}])) == "Hola mundo"
    assert prov  # noqa


# ── Guarda: ninguém volta a ler ``.content`` como se fosse texto ─────────

_RAIZ = pathlib.Path(__file__).resolve().parent.parent
_PADROES = [
    re.compile(r"\.content\s+if\s+hasattr\(\s*\w+,\s*[\"']content[\"']"),
    re.compile(r"getattr\(\s*\w+,\s*[\"']content[\"']"),
    re.compile(r"\[\"messages\"\]\[-1\]\.content"),
    re.compile(r"\b(?:raw|resp|response|resposta|bruto)\.content\b"),
]
#: Onde ler ``.content`` cru é o objectivo (o helper, o fornecedor, a
#: máscara de privacidade que preserva listas).
_PERMITIDOS = {
    "core/llm/conteudo.py",
    "core/llm/providers.py",
    "core/privacidade/observabilidade.py",
    "core/data_sources/api_source.py",  # httpx.Response.content (bytes)
}


def test_nenhum_sitio_le_content_do_modelo_sem_o_helper():
    ofensores = []
    for pasta in ("core", "api", "worker", "src", "agent_registry"):
        for f in (_RAIZ / pasta).rglob("*.py"):
            rel = f.relative_to(_RAIZ).as_posix()
            if rel in _PERMITIDOS:
                continue
            for n, linha in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if linha.lstrip().startswith("#"):
                    continue
                if any(p.search(linha) for p in _PADROES):
                    ofensores.append(f"{rel}:{n}: {linha.strip()}")
    assert not ofensores, "usar core.llm.conteudo.texto_da_resposta:\n" + "\n".join(
        ofensores
    )
