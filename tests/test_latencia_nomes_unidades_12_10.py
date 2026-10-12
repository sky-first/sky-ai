"""Produção, 12/10/2026, depois do deploy de cbb56743 (tenant skyfirstlabs).

1. Latência — «Lista las 5 gasolineras con el gasóleo A más barato en la tabla
   gasolineras_rota para la ruta Badajoz-Madrid» levou 82,6 s. Os registos do
   pod (com --timestamps) explicam-nos todos:

   * 34,5 s — detector de línguas a frio, no handler, com o laço parado;
   * 29,7 s — descarga + carga do modelo de embeddings dentro do orquestrador,
     por um caminho síncrono que ignorava a cache onde o vector já estava;
   * 12,3 s — duas chamadas do orquestrador ReAct (gpt-oss) para escolher a
     tabela que a pessoa tinha NOMEADO;
   * ~0,3 s — uma chamada ao qwen só para classificar o tipo de análise;
   * o resto: especialista 0,75 s, formatador 2,3 s, SQL, amostragem.

   E nenhuma destas etapas escrevia o seu tempo nos registos.

2. «No se pueden proporcionar los nombres completos…» com rotulo e localidad
   nas 5 linhas; e «en la muestra» para um top-5 pedido.

3. «uma diferença de 36,81» sem unidade — servido pela cache semântica, escrito
   pelo código anterior a #282.
"""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

import latency_timing
from core.agents.generic_sql_agent import AgentConfig, TableSchema


@pytest.fixture
def eventos():
    """Apanha tudo o que vai para log_event (registos do pod), de qualquer
    módulo — lê o logger, não o símbolo importado."""
    import json
    import logging

    apanhados = []

    class _H(logging.Handler):
        def emit(self, record):
            try:
                obj = json.loads(record.getMessage())
            except Exception:
                return
            if isinstance(obj, dict) and "event_type" in obj:
                tipo = obj.pop("event_type")
                apanhados.append((tipo, obj))

    h = _H(level=logging.INFO)
    lg = logging.getLogger("dataassistant")
    nivel, desligado = lg.level, lg.disabled
    lg.setLevel(logging.INFO)
    lg.disabled = False
    lg.addHandler(h)
    try:
        yield apanhados
    finally:
        lg.removeHandler(h)
        lg.setLevel(nivel)
        lg.disabled = desligado


def _de(eventos, tipo):
    return [p for t, p in eventos if t == tipo]


# ── 1a. Tempos nos registos e o total do pedido ──────────────────────────


class TestTemposDoPedido:
    def test_etapas_detalhe_e_total(self, eventos):
        latency_timing.new_trace("t-1")
        latency_timing.registar_tempo("rag_timing", 120, etapa="rag")
        latency_timing.registar_tempo(
            "llm_call_timing", 900, detalhe="llm:x", caller="x", model="m"
        )
        latency_timing.registar_tempo("node_timing", 1000, etapa="formatter")
        resumo = latency_timing.fechar_pedido(connection_id="c")

        assert resumo["breakdown_ms"] == {"formatter": 1000, "rag": 120}
        assert resumo["llm_calls"] == 1 and resumo["llm_ms"] == 900
        assert resumo["detail_ms"] == {"llm:x": 900}
        total = _de(eventos, "query_total_timing")
        assert total and total[-1]["connection_id"] == "c"
        assert total[-1]["trace"] == "t-1"
        # Cada etapa escreve o seu ``ms`` nos registos do pod.
        assert _de(eventos, "rag_timing")[0]["ms"] == 120

    def test_os_nos_do_grafo_vao_para_os_registos(self, eventos):
        latency_timing.new_trace("t-2")

        @latency_timing.timed("orchestrator")
        def no(state):
            return state

        no({})
        assert _de(eventos, "node_timing")[0]["node"] == "orchestrator"
        assert "orchestrator" in latency_timing.resumo_do_pedido()["breakdown_ms"]

    def test_o_acumulador_atravessa_to_thread(self):
        """O grafo corre em asyncio.to_thread: o que lá se mede tem de chegar
        ao total do pedido."""

        async def pedido():
            latency_timing.new_trace("t-3")
            await asyncio.to_thread(
                latency_timing.registar_tempo, "node_timing", 50, etapa="specialist"
            )
            return latency_timing.resumo_do_pedido()

        resumo = asyncio.run(pedido())
        assert resumo["breakdown_ms"]["specialist"] == 50

    def test_fora_de_um_pedido_so_regista(self, eventos):
        import contextvars

        def fora():
            latency_timing._pedido.set(None)
            latency_timing.registar_tempo("x_timing", 5, etapa="x")
            return latency_timing.resumo_do_pedido()

        assert contextvars.Context().run(fora) is None
        assert _de(eventos, "x_timing")[0]["ms"] == 5

    def test_o_streaming_tambem_fecha_o_pedido(self, eventos):
        from api.routes.connection_query import _com_tempos_do_pedido

        async def gerador():
            latency_timing.registar_tempo("node_timing", 7, etapa="formatter")
            yield "a"
            yield "b"

        async def consumir():
            return [p async for p in _com_tempos_do_pedido(gerador(), "c-s", "th")]

        assert asyncio.run(consumir()) == ["a", "b"]
        total = _de(eventos, "query_total_timing")[-1]
        assert total["stream"] is True and total["ok"] is True
        assert total["breakdown_ms"] == {"formatter": 7}


class _ChatFalso:
    model_name = "openai.gpt-oss-120b"

    def __init__(self, espera=0.02):
        self.espera = espera

    def invoke(self, _msgs):
        time.sleep(self.espera)
        return SimpleNamespace(content="ok")

    def stream(self, _msgs):
        time.sleep(self.espera)
        yield SimpleNamespace(content="o")
        yield SimpleNamespace(content="k")


def _quem_pergunta_ao_modelo(provider):
    return provider.invoke([{"role": "user", "content": "x" * 40}])


class TestCadaChamadaAoModeloEMedida:
    def _provider(self):
        from core.llm.providers import LangChainChatOpenAIProvider

        p = LangChainChatOpenAIProvider.__new__(LangChainChatOpenAIProvider)
        p._chat = _ChatFalso()
        return p

    def test_invoke(self, eventos):
        latency_timing.new_trace("t-llm")
        _quem_pergunta_ao_modelo(self._provider())
        ev = _de(eventos, "llm_call_timing")[-1]
        assert ev["ms"] >= 15
        assert ev["model"] == "openai.gpt-oss-120b"
        assert ev["prompt_chars"] == 40
        assert ev["ok"] is True
        # Quem chamou, e não o fornecedor.
        assert ev["caller"].endswith("_quem_pergunta_ao_modelo")
        assert latency_timing.resumo_do_pedido()["llm_calls"] == 1

    def test_stream(self, eventos):
        latency_timing.new_trace("t-llm-s")
        assert (
            "".join(self._provider().stream([{"role": "user", "content": "x"}])) == "ok"
        )
        ev = _de(eventos, "llm_call_timing")[-1]
        assert ev["mode"] == "stream" and ev["ms"] >= 15

    def test_erro_tambem_conta(self, eventos):
        class _Partido(_ChatFalso):
            def invoke(self, _m):
                raise RuntimeError("timeout")

        p = self._provider()
        p._chat = _Partido()
        latency_timing.new_trace("t-llm-e")
        with pytest.raises(RuntimeError):
            p.invoke([{"role": "user", "content": "x"}])
        assert _de(eventos, "llm_call_timing")[-1]["ok"] is False

    def test_o_react_do_orquestrador_tambem(self, eventos):
        """O ReAct fala com o ``_chat`` por baixo do fornecedor: mede-se por
        callback do LangChain."""
        import uuid

        from core.llm.orchestrator import _TemposDoReAct

        latency_timing.new_trace("t-react")
        cb = _TemposDoReAct("openai.gpt-oss-120b")
        for _ in range(2):
            rid = uuid.uuid4()
            cb.on_chat_model_start({}, [[]], run_id=rid)
            time.sleep(0.01)
            cb.on_llm_end(SimpleNamespace(), run_id=rid)
        evs = _de(eventos, "llm_call_timing")
        assert len(evs) == 2
        assert all(e["caller"] == "core.llm.orchestrator.react" for e in evs)
        assert latency_timing.resumo_do_pedido()["llm_calls"] == 2


# ── 1b. A tabela nomeada não se pergunta ao modelo ───────────────────────


class _ModeloProibido:
    """Tem ``_chat`` com ``bind_tools`` (caminho ReAct) e rebenta se usado."""

    class _Chat:
        model_name = "openai.gpt-oss-120b"

        def bind_tools(self, *_a, **_k):
            raise AssertionError("o orquestrador não devia chamar o modelo")

        def invoke(self, *_a, **_k):
            raise AssertionError("o orquestrador não devia chamar o modelo")

    _chat = _Chat()

    def invoke(self, *_a, **_k):
        raise AssertionError("o orquestrador não devia chamar o modelo")


def _orquestrar(pergunta, modelo):
    from core.llm.orchestrator import run_orchestrator
    from test_gasolineras_rota_e_euro_duplicado import OPERACIONES

    state = {
        "question": pergunta,
        "chat_history": [],
        "locale": "es",
        "retrieval_context": [],
        "agent_mode": "question",
    }
    cfg = AgentConfig(id="ops", name="Operaciones", tables=list(OPERACIONES))
    return run_orchestrator(state, cfg, modelo)


class TestTabelaNomeada:
    def test_a_pergunta_de_producao_nao_chama_o_modelo(self, eventos):
        from test_gasolineras_rota_e_euro_duplicado import PERGUNTA_1

        state = _orquestrar(PERGUNTA_1, _ModeloProibido())
        assert state.get("answer") in (None, "")
        # A nomeada primeiro, e a vizinha com o preço — como fazia o ReAct.
        assert state["chosen_tables"][0] == "gasolineras_rota"
        assert "gasolineras_precio" in state["chosen_tables"]
        assert state.get("join_relationships")
        assert _de(eventos, "orchestrator_named_table")[0]["skipped_llm"] is True

    @pytest.mark.parametrize(
        "pergunta,esperada",
        [
            ("precio medio según gasoleo_historico_diario", "gasoleo_historico_diario"),
            ("cuántas filas tiene ops.gasolineras_precio", "gasolineras_precio"),
            ("total de la tabla trips por ruta", "trips"),
            ("Quantos registos tem a tabela «festivos»?", "festivos"),
        ],
    )
    def test_nomes_que_contam(self, pergunta, esperada):
        from core.llm.orchestrator import tabela_nomeada_na_pergunta
        from test_gasolineras_rota_e_euro_duplicado import OPERACIONES

        t = tabela_nomeada_na_pergunta(pergunta, OPERACIONES)
        assert t is not None and t.logical_name == esperada

    @pytest.mark.parametrize(
        "pergunta",
        [
            # O assunto, não o nome de uma tabela.
            "¿Cuál es la ruta más corta entre Lisboa y Madrid?",
            "Quantos festivos há em Dezembro?",
            "Lista los trips más caros",
            # Duas tabelas nomeadas: decide o modelo, como antes.
            "compara gasolineras_rota con gasolineras_precio",
            "",
        ],
    )
    def test_nomes_que_nao_contam(self, pergunta):
        from core.llm.orchestrator import tabela_nomeada_na_pergunta
        from test_gasolineras_rota_e_euro_duplicado import OPERACIONES

        assert tabela_nomeada_na_pergunta(pergunta, OPERACIONES) is None

    def test_sem_nome_o_react_corre_e_e_medido(self, monkeypatch, eventos):
        """Sem tabela nomeada, o caminho ReAct continua — com o callback de
        tempos ligado."""
        import langgraph.prebuilt as lp

        visto = {}

        class _Agente:
            def invoke(self, _entrada, config=None):
                visto["callbacks"] = (config or {}).get("callbacks")
                return {"messages": [SimpleNamespace(content="gasolineras_precio")]}

        monkeypatch.setattr(lp, "create_react_agent", lambda *a, **k: _Agente())

        class _Chat:
            model_name = "openai.gpt-oss-120b"

            def bind_tools(self, *_a, **_k):
                return self

        modelo = SimpleNamespace(_chat=_Chat(), invoke=None)
        state = _orquestrar("¿Cuál es la gasolinera más barata de Badajoz?", modelo)
        assert state["chosen_tables"][0] == "gasolineras_precio"
        from core.llm.orchestrator import _TemposDoReAct

        assert any(isinstance(c, _TemposDoReAct) for c in visto["callbacks"])


# ── 1c. Sem chamada ao modelo para o «analysis context» ──────────────────


class TestContextoDeAnaliseSemModelo:
    def test_nao_chama_o_modelo(self, eventos):
        from core.context.analysis_session_store import AnalysisSessionStore
        from core.llm.analysis_context_generator import (
            generate_and_save_analysis_context,
        )

        class _Proibido:
            def invoke(self, *_a, **_k):
                raise AssertionError("não devia chamar o modelo")

        generate_and_save_analysis_context(
            {
                "sql": "SELECT gp.rotulo, gp.precio_gasoleo_a FROM ops.gasolineras_precio gp "
                "ORDER BY gp.precio_gasoleo_a ASC LIMIT 5",
                "user_id": "u-ctx",
                "question": "Lista las 5…",
                "chosen_tables": ["gasolineras_precio"],
            },
            _Proibido(),
        )
        ctx = AnalysisSessionStore.get("u-ctx", "default")
        assert ctx is not None and ctx.detected_analysis_type == "list"
        assert _de(eventos, "analysis_context_timing")[0]["llm"] is False

    @pytest.mark.parametrize(
        "sql,tipo,tempo",
        [
            (
                "SELECT date_trunc('month', placed_at) AS mes, SUM(total) "
                "FROM service.orders GROUP BY 1 ORDER BY 1",
                "trend",
                "placed_at",
            ),
            (
                "SELECT channel, AVG(service_sec) FROM service.orders GROUP BY channel",
                "distribution",
                None,
            ),
            (
                "SELECT channel, AVG(service_sec) a FROM service.orders GROUP BY channel "
                "ORDER BY a DESC LIMIT 3",
                "comparison",
                None,
            ),
            ("SELECT COUNT(*) FROM service.orders", "kpi", None),
        ],
    )
    def test_tipos(self, sql, tipo, tempo):
        from core.llm.analysis_context_generator import _infer_analysis_type

        r = _infer_analysis_type(sql)
        assert r == {"analysis_type": tipo, "time_column": tempo}


# ── 1d. Embeddings: cache no caminho síncrono, uma carga só, aquecimento ──


class TestEmbeddings:
    def test_a_busca_sincrona_usa_a_cache(self, monkeypatch):
        from core.rag import embeddings as emb
        from core.rag import vector_store as vs

        class _Provider(emb.EmbeddingProvider):
            chamadas = 0

            def embed(self, texts):
                _Provider.chamadas += 1
                return [[0.0] * 3 for _ in texts]

        monkeypatch.setattr(emb, "get_cached_embedding", lambda _t: [0.1, 0.2, 0.3])
        monkeypatch.setattr(vs, "_is_pgvector_available_sync", lambda _db: True)

        class _Q:
            def order_by(self, *_a):
                return self

            def limit(self, *_a):
                return self

        monkeypatch.setattr(vs, "_build_embedding_base_query", lambda *a, **k: _Q())
        db = SimpleNamespace(
            execute=lambda *_a: SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: [])
            )
        )
        vs.search_embeddings(db, _Provider(), "s", [], "Lista las 5 gasolineras")
        assert _Provider.chamadas == 0  # o vector veio da cache

    def test_o_modelo_local_carrega_uma_vez_com_dois_pedidos_ao_mesmo_tempo(
        self, monkeypatch, eventos
    ):
        from core.rag.embeddings import LocalEmbeddingProvider

        cargas = []

        def _carregar(self):
            cargas.append(1)
            time.sleep(0.05)
            self._client = SimpleNamespace(embed=lambda ts: [])

        monkeypatch.setattr(LocalEmbeddingProvider, "_carregar", _carregar)
        p = LocalEmbeddingProvider(model="m")
        ts = [threading.Thread(target=p._ensure_client) for _ in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert len(cargas) == 1
        ev = _de(eventos, "embedding_model_load_timing")
        assert len(ev) == 1 and ev[0]["ms"] >= 40 and ev[0]["ok"] is True

    def test_aquecimento_carrega_linguas_e_embeddings(self, monkeypatch, eventos):
        from core import aquecimento
        from core.rag import embeddings as emb

        chamadas = []
        monkeypatch.setattr(
            "core.i18n.i18n.detect_language",
            lambda t: chamadas.append(("lingua", t)) or "es",
        )

        class _Local(emb.LocalEmbeddingProvider):
            def __init__(self):
                self._client = None

            def embed(self, texts):
                chamadas.append(("embed", tuple(texts)))
                return [[0.0]]

        monkeypatch.setattr(
            "core.llm.factory.create_embedding_provider", lambda: _Local()
        )
        r = aquecimento.aquecer()
        assert r["language_detector"] is not None and r["embedding_model"] is not None
        assert any(c[0] == "lingua" for c in chamadas)
        assert any(c[0] == "embed" for c in chamadas)
        assert {p["component"] for p in _de(eventos, "warmup_timing")} == {
            "language_detector",
            "embedding_model",
        }

    def test_aquecimento_nao_corre_nos_testes_nem_desligado(self, monkeypatch):
        from core import aquecimento

        assert aquecimento.desligado() is True  # pytest carregado
        assert aquecimento.aquecer_em_segundo_plano() is None

    def test_aquecimento_falhado_nao_parte_nada(self, monkeypatch, eventos):
        from core import aquecimento

        def _rebenta():
            raise RuntimeError("sem rede")

        monkeypatch.setattr(aquecimento, "_embeddings", _rebenta)
        r = aquecimento.aquecer()
        assert r["embedding_model"] is None
        assert _de(eventos, "warmup_failed")[0]["component"] == "embedding_model"

    def test_o_arranque_lanca_o_aquecimento(self):
        import inspect

        import api.main as m

        assert "aquecer_em_segundo_plano()" in inspect.getsource(m.on_startup)


# ── 1e. O valor que a pergunta nomeia vai ao pé da pergunta ──────────────


class TestLiteraisDaPergunta:
    def _tabelas(self):
        from test_literal_com_gralha_e_zero_linhas import _precio, _rota

        rota, precio = _rota(), _precio()
        for c in rota.columns:
            if c["name"] in ("origem", "destino"):
                c["sample_values"] = ["BADAJOZ", "MADRID", "LISBOA", "PORTO"]
        for c in precio.columns:
            if c["name"] == "rotulo":
                c["sample_values"] = ["REPSOL", "CEPSA", "GASÓLEO A"]
        return [rota, precio]

    def test_badajoz_madrid(self):
        from core.sql.valores_de_coluna import literais_da_pergunta

        achados = literais_da_pergunta(
            self._tabelas(),
            "Lista las 5 gasolineras con el gasóleo A más barato en la tabla "
            "gasolineras_rota para la ruta Badajoz-Madrid",
        )
        assert ("ops.gasolineras_rota", "origem", "BADAJOZ") in achados
        assert ("ops.gasolineras_rota", "destino", "MADRID") in achados
        assert ("ops.gasolineras_precio", "rotulo", "GASÓLEO A") in achados
        assert all(v != "LISBOA" for _, _, v in achados)

    def test_palavras_curtas_e_comuns_nao_contam(self):
        from core.sql.valores_de_coluna import literais_da_pergunta

        t = TableSchema(
            logical_name="x",
            physical_name="s.x",
            columns=[
                {
                    "name": "tipo",
                    "type": "text",
                    "sample_values": ["P", "R", "TOTAL", "de"],
                }
            ],
        )
        assert literais_da_pergunta([t], "Tipo P de venta total por provincia") == []

    def test_no_prompt_logo_a_seguir_a_pergunta(self):
        from core.sql import valores_de_coluna
        from test_literal_com_gralha_e_zero_linhas import (
            SQL_COM_GRALHA,
            _correr,
            _dominios,
            _Fonte,
        )

        valores_de_coluna.limpar_cache()
        try:
            fonte = _Fonte(
                _dominios(),
                {"'BADAJOZ'": [{"rotulo": "REPSOL", "precio_gasoleo_a": 1.39}]},
            )
            _, modelo = _correr(SQL_COM_GRALHA.replace("BAJAZOZ", "BADAJOZ"), fonte)
        finally:
            valores_de_coluna.limpar_cache()
        sistema, utilizador = modelo.mensagens[0]
        u = utilizador["content"]
        i_pergunta = u.index("User question:")
        i_bloco = u.index("VALUES IN THE DATA THAT MATCH THE QUESTION")
        i_esquema = u.index("Table schema(s):")
        assert i_pergunta < i_bloco < i_esquema
        assert "ops.gasolineras_rota.origem = 'BADAJOZ'" in u
        assert "ops.gasolineras_rota.destino = 'MADRID'" in u
        # A regra que mandava retipar em maiúsculas já não é absoluta.
        assert "ALWAYS use UPPER()" not in sistema["content"]
        assert "Compare that column DIRECTLY" in sistema["content"]


# ── 2. Nomes e «muestra» ─────────────────────────────────────────────────

LINHAS_5 = [
    {
        "id_estacion": 4375,
        "rotulo": "BALLENOIL",
        "localidad": "MÓSTOLES",
        "precio_gasoleo_a": 1.69,
    },
    {
        "id_estacion": 4376,
        "rotulo": "PETROPRIX",
        "localidad": "MÓSTOLES",
        "precio_gasoleo_a": 1.69,
    },
    {
        "id_estacion": 5120,
        "rotulo": "BALLENOIL",
        "localidad": "MÉRIDA",
        "precio_gasoleo_a": 1.71,
    },
    {
        "id_estacion": 5121,
        "rotulo": "PETROPRIX",
        "localidad": "MÉRIDA",
        "precio_gasoleo_a": 1.72,
    },
    {
        "id_estacion": 5200,
        "rotulo": "BALLENOIL",
        "localidad": "ESPARRAGALEJO",
        "precio_gasoleo_a": 1.73,
    },
]

RESPOSTA_DE_PRODUCAO = (
    "El precio más bajo de gasóleo A que aparece en la muestra es de 1,69 € por "
    "litro, ofrecido por dos estaciones, BALLENOIL y PETROPRIX, ambas en Móstoles. "
    "El siguiente precio registrado es 1,71 € en Mérida. No se pueden proporcionar "
    "los nombres completos de las cinco estaciones solicitadas."
)


class _Formatador:
    def __init__(self, resposta):
        self.resposta = resposta
        self.mensagens = None

    def invoke(self, mensagens, *_a, **_k):
        self.mensagens = mensagens
        return SimpleNamespace(content=self.resposta)


def _formatar(resposta, linhas, pergunta, lingua="es", sql=None):
    from core.llm.formatter import run_formatter

    modelo = _Formatador(resposta)
    st = run_formatter(
        {
            "question": pergunta,
            "detected_language": lingua,
            "data": list(linhas),
            "sql": sql or "SELECT 1",
        },
        AgentConfig(id="t", name="t", tables=[]),
        modelo,
    )
    return st["answer"], "\n".join(m["content"] for m in modelo.mensagens)


class TestNomesEMuestra:
    PERGUNTA = (
        "Lista las 5 gasolineras con el gasóleo A más barato en la tabla "
        "gasolineras_rota para la ruta Badajoz-Madrid"
    )

    def test_a_resposta_de_producao_fica_sem_as_duas_mentiras(self):
        resposta, _ = _formatar(RESPOSTA_DE_PRODUCAO, LINHAS_5, self.PERGUNTA)
        assert "No se pueden proporcionar" not in resposta
        assert "muestra" not in resposta
        assert "BALLENOIL" in resposta and "PETROPRIX" in resposta
        assert resposta.startswith("El precio más bajo de gasóleo A es de 1,69 €")

    def test_o_prompt_diz_onde_estao_os_nomes_e_que_esta_completo(self):
        _, prompt = _formatar("ok", LINHAS_5, self.PERGUNTA)
        assert "NAMES ARE IN THE ROWS: the columns rotulo, localidad" in prompt
        assert "COMPLETE answer" in prompt
        # As regras que mandavam recusar listas já não estão lá.
        assert "lists of names" not in prompt
        assert "REFUSE and provide ONLY aggregated" not in prompt
        assert "name EACH returned item" in prompt

    def test_com_amostra_a_sério_a_palavra_fica(self):
        linhas = [
            {
                "rotulo": f"POSTO {i}",
                "localidad": "MADRID",
                "precio_gasoleo_a": 1.5 + i / 100,
            }
            for i in range(30)
        ]
        resposta, prompt = _formatar(
            "El más barato en la muestra es POSTO 0, con 1,50 €.",
            linhas,
            "¿Cuál es el más barato?",
        )
        assert "SAMPLE NOTICE" in prompt and "COMPLETE answer" not in prompt
        assert "muestra" in resposta

    @pytest.mark.parametrize(
        "texto,linhas,esperado",
        [
            (
                "O preço mais baixo na amostra é 1,69 €. Não é possível indicar os nomes dos postos.",
                LINHAS_5,
                "O preço mais baixo é 1,69 €.",
            ),
            (
                "The cheapest price in the sample is 1.69. Station names are not available.",
                LINHAS_5,
                "The cheapest price is 1.69.",
            ),
            # Uma falta que pode ser verdade (dados de 2025) não se corta.
            (
                "No hay datos de 2025; el precio de 2024 fue 1,69 €.",
                LINHAS_5,
                "No hay datos de 2025; el precio de 2024 fue 1,69 €.",
            ),
            # Sem colunas de nome nas linhas: a frase sobre nomes fica.
            (
                "El total es 12. No se pueden proporcionar los nombres de los clientes.",
                [{"total": 12}],
                "El total es 12. No se pueden proporcionar los nombres de los clientes.",
            ),
            # Nunca deixar a resposta vazia.
            (
                "No se pueden proporcionar los nombres.",
                LINHAS_5,
                "No se pueden proporcionar los nombres.",
            ),
        ],
    )
    def test_corrigir_completude(self, texto, linhas, esperado):
        from core.llm.completude import corrigir_completude

        assert corrigir_completude(texto, linhas, completo=True) == esperado

    def test_o_streaming_nao_chama_amostra_a_um_resultado_completo(self):
        import inspect

        import api.routes.connection_query as cq

        src = inspect.getsource(cq._stream_connection_query)
        assert "Result rows (complete, JSON)" in src
        assert "regras_do_resultado(data, len(raw_sample))" in src


# ── 3. Unidade numa métrica derivada ─────────────────────────────────────

SQL_MELHORAR = (
    "WITH por_canal AS (\n"
    "  SELECT channel, AVG(service_sec) AS avg_service_sec\n"
    "  FROM service.orders GROUP BY channel\n"
    ")\n"
    "SELECT channel, avg_service_sec,\n"
    "  (SELECT MAX(avg_service_sec) - MIN(avg_service_sec) FROM por_canal) AS maior_diferenca,\n"
    "  (SELECT MAX(avg_service_sec) - AVG(avg_service_sec) FROM por_canal) AS ganho\n"
    "FROM por_canal ORDER BY avg_service_sec DESC"
)
LINHAS_MELHORAR = [
    {
        "channel": "drive",
        "avg_service_sec": 120.5,
        "maior_diferenca": 36.81,
        "ganho": 36.81,
    },
    {
        "channel": "sala",
        "avg_service_sec": 83.69,
        "maior_diferenca": 36.81,
        "ganho": 36.81,
    },
]


class TestUnidadeDerivada:
    def test_alias_herda_s(self):
        from core.llm.numeros import unidades_do_resultado

        u = unidades_do_resultado(list(LINHAS_MELHORAR[0]), SQL_MELHORAR, {})
        assert u == {"avg_service_sec": "s", "maior_diferenca": "s", "ganho": "s"}

    def test_max_menos_min_sem_cte(self):
        from core.llm.numeros import unidades_do_resultado

        sql = (
            "SELECT MAX(m) - MIN(m) AS diferenca FROM (SELECT channel, "
            "AVG(service_sec) AS m FROM service.orders GROUP BY channel) t"
        )
        assert unidades_do_resultado(["diferenca"], sql, {}) == {"diferenca": "s"}

    def test_a_resposta_em_portugues_leva_a_unidade(self):
        frase = (
            "A maior diferença está no canal drive, com uma diferença de 36,81; "
            "aproximar o pior da média geraria um ganho de 36,81."
        )
        resposta, _ = _formatar(
            frase,
            LINHAS_MELHORAR,
            "Onde é que se pode melhorar? Encontra a maior diferença entre o melhor e "
            "o pior (zona, equipa, produto ou canal) e quanto se ganharia a aproximar "
            "o pior da média.",
            lingua="pt",
            sql=SQL_MELHORAR,
        )
        assert "diferença de 36,81 s;" in resposta
        assert "ganho de 36,81 s." in resposta
