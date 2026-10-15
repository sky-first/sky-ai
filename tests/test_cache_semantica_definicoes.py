"""A cache semântica não sobrevive a uma mudança das definições do espaço.

Produção, 16/10/2026 (sandbox, «Logística y Transporte»), depois do promote
de 1a22f72c (#297) e de o job da demo gravar o termo «Porte fuera de plazo»
e a métrica «Vehículos que no se pagan»:

    semantic_cache_hit  similarity_score 1.0     «¿Qué vehículos no se pagan?»
    semantic_cache_hit  similarity_score 0.9583  «¿Qué camiones no se pagan?»
    query_total_timing  cache_hit true, llm_calls 0

e a resposta servida foi a da véspera, palavra por palavra: «No hay
vehículos que no se paguen en el periodo analizado…» (na base, 03-GH-19
tem aportação −15.936 €).

Estes testes correm a rota real (``query_connection``) contra uma base
falsa COM MEMÓRIA: o que se grava fica lá, e a procura aplica os filtros
que o SQL da procura pede (versão, língua, período e — agora — a impressão
digital das definições). Antes da correcção, o 2.º pedido com o glossário
novo recebia a resposta gravada com o antigo.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from api.schemas import QueryRequest, QueryResponse, QueryResultMeta
from core import cache_semantica

GLOSSARIO_ANTIGO = """# Trusted metrics (prefer these over ad-hoc derivations)
- Aportación por vehículo [PROJECT] — Lo que cada camión ingresa menos lo que él mismo cuesta. (unit: EUR)

# Glossary
- **Plazo del cliente** — Los minutos de tolerancia acordados con cada cliente."""

GLOSSARIO_NOVO = GLOSSARIO_ANTIGO + """
- **Porte fuera de plazo** — Un porte que llega después de la llegada prevista más la tolerancia del cliente.
- **Vehículo que no se paga** — Un vehículo cuya aportación es negativa."""

RESPOSTA_ERRADA_DE_ONTEM = (
    "No hay vehículos que no se paguen en el periodo analizado. Todos los "
    "camiones de la flota generan una aportación positiva."
)

LINHAS = [{"plate": "03-GH-19", "aportacion": -15936}]


# ── base falsa com memória ────────────────────────────────────────────────


class _Resultado:
    def __init__(self, primeira=None):
        self._primeira = primeira

    def first(self):
        return self._primeira


class _BaseComMemoria:
    """Guarda o que é ``add``-ado e responde à procura com os filtros dela.

    Só aplica um filtro se o SQL da procura o pedir — é isso que separa o
    código antigo (sem impressão digital na chave) do novo.
    """

    def __init__(self):
        self.guardados: list = []
        self.procuras: list[tuple[str, dict]] = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}
        if "FROM semantic_cache" in sql and "SELECT" in sql:
            self.procuras.append((sql, params))
            for r in reversed(self.guardados):
                if str(r.connection_id) != str(params.get("conn_id")):
                    continue
                if r.cache_version != params.get("cache_version"):
                    continue
                if r.locale != params.get("locale"):
                    continue
                if r.temporal_bucket != params.get("temporal_bucket"):
                    continue
                if ":context_fingerprint" in sql and getattr(
                    r, "context_fingerprint", None
                ) != params.get("context_fingerprint"):
                    continue
                return _Resultado((r.response_json, 1.0))
            return _Resultado(None)
        if "FROM data_connections" in sql:
            return _Resultado(("conn-1", "Fonte", "postgres", {}))
        return _Resultado(None)

    def add(self, obj):
        self.guardados.append(obj)

    async def commit(self):
        pass

    async def rollback(self):
        pass


class _Fonte:
    def __init__(self, linhas):
        self.linhas = linhas

    def run_query(self, sql):
        return list(self.linhas)


class _Embeddings:
    async def embed_async(self, textos):
        # A mesma frase dá sempre o mesmo vector (similaridade 1,0).
        return [[0.0, 0.1, 0.2] for _ in textos]


def _pedido(instrucoes=GLOSSARIO_NOVO, **extra):
    return QueryRequest(
        question="¿Qué vehículos no se pagan?",
        user_id="u-1",
        space_id="s-1",
        crew_ids=["crew-1"],
        is_personal=False,
        locale="es",
        instructions=instrucoes,
        **extra,
    )


def _resposta(answer, linhas, sql="SELECT plate, aportacion FROM v"):
    return QueryResponse(
        answer=answer,
        data_sample=list(linhas),
        meta=QueryResultMeta(sql=sql, num_rows=len(linhas)),
    )


def _perguntar(db, pedido, resposta_do_pipeline, fonte_linhas=LINHAS):
    """Uma pergunta pela rota real. Devolve (resposta, correu_o_pipeline)."""
    from api.routes import connection_query as cq

    corridas = []

    async def _interior(connection_id, body, db_):
        corridas.append(body.question)
        return resposta_do_pipeline

    with patch(
        "core.llm.factory.create_embedding_provider", return_value=_Embeddings()
    ), patch.object(cq, "_query_connection_inner", _interior), patch.object(
        cq,
        "_dispatch_map_from_conn_rows",
        lambda rows: {"conn-1": _Fonte(fonte_linhas)},
    ):
        resposta = asyncio.run(cq.query_connection("conn-1", pedido, db))
    return resposta, bool(corridas)


# ── a regra que faltava: definições na chave ──────────────────────────────


def test_glossario_novo_nao_recebe_a_resposta_gravada_com_o_antigo():
    db = _BaseComMemoria()
    certa_de_ontem = _resposta("03-GH-19 no se paga: −15.936 €.", LINHAS)
    _perguntar(db, _pedido(GLOSSARIO_ANTIGO), certa_de_ontem)
    assert len(db.guardados) == 1

    nova = _resposta("03-GH-19: aportación −15.936 € (definición nueva).", LINHAS)
    resposta, correu = _perguntar(db, _pedido(GLOSSARIO_NOVO), nova)

    assert correu, (
        "o glossário mudou: a resposta gravada com as definições antigas não "
        "pode ser servida"
    )
    assert resposta.answer == nova.answer


def test_mesmas_definicoes_continuam_a_acertar_na_cache():
    db = _BaseComMemoria()
    _perguntar(db, _pedido(), _resposta("03-GH-19: −15.936 €.", LINHAS))

    resposta, correu = _perguntar(db, _pedido(), _resposta("outra", LINHAS))

    assert not correu, "nada mudou: a cache tem de continuar a servir"
    assert resposta.answer == "03-GH-19: −15.936 €."
    assert resposta.data_sample == LINHAS


def test_a_ordem_das_metricas_nao_parte_a_cache():
    """O backend lista as métricas pela ordem da consulta, sem garantia."""
    linhas = GLOSSARIO_NOVO.splitlines()
    baralhado = "\n".join([linhas[0]] + list(reversed(linhas[1:])))
    assert cache_semantica.impressao_das_definicoes(
        _pedido(GLOSSARIO_NOVO)
    ) == cache_semantica.impressao_das_definicoes(_pedido(baralhado))


def test_uma_virgula_numa_definicao_muda_a_impressao():
    a = cache_semantica.impressao_das_definicoes(_pedido(GLOSSARIO_NOVO))
    b = cache_semantica.impressao_das_definicoes(
        _pedido(GLOSSARIO_NOVO.replace("es negativa", "es negativa, en el año"))
    )
    assert a != b


def test_regras_de_acesso_e_instrucoes_de_sql_tambem_entram():
    base = cache_semantica.impressao_das_definicoes(_pedido())
    assert base != cache_semantica.impressao_das_definicoes(
        _pedido(sql_instructions="Excluye los viajes cancelados.")
    )
    assert base != cache_semantica.impressao_das_definicoes(
        _pedido(authorized_tables=["fleet.vehicles"])
    )
    assert base != cache_semantica.impressao_das_definicoes(
        _pedido(
            security_config={
                "tables": {"ops.trips": {"row_filter": "vehicle_id = 3"}},
            }
        )
    )


def test_a_procura_filtra_pela_impressao_e_a_escrita_grava_a():
    db = _BaseComMemoria()
    _perguntar(db, _pedido(), _resposta("03-GH-19: −15.936 €.", LINHAS))
    esperado = cache_semantica.impressao_das_definicoes(_pedido())
    assert db.guardados[0].context_fingerprint == esperado
    for sql, params in db.procuras:
        assert "context_fingerprint = :context_fingerprint" in sql
        assert params["context_fingerprint"] == esperado


# ── negativas e 0 linhas nunca ficam ──────────────────────────────────────


def test_a_resposta_errada_de_ontem_nao_e_gravada():
    """O caso de produção: merger com 0 linhas e «No hay…»."""
    db = _BaseComMemoria()
    errada = _resposta(
        RESPOSTA_ERRADA_DE_ONTEM,
        [],
        sql="WITH v AS (SELECT * FROM dataset_1) SELECT * FROM v WHERE fixed_cost_month = 0",
    )
    _perguntar(db, _pedido(), errada)
    assert db.guardados == [], "uma resposta de 0 linhas não pode ficar na cache"

    # E a pergunta seguinte corre outra vez (podia acertar desta vez).
    _, correu = _perguntar(db, _pedido(), _resposta("03-GH-19: −15.936 €.", LINHAS))
    assert correu


def test_negativa_sem_sql_tambem_nao_e_gravada():
    db = _BaseComMemoria()
    for frase in (
        "No hay datos para ese periodo.",
        "Não há vendas registadas este mês.",
        "There are no vehicles matching that condition.",
        "Ningún vehículo cumple la condición.",
    ):
        _perguntar(db, _pedido(), _resposta(frase, [], sql=None))
    assert db.guardados == []


def test_negativa_ja_guardada_nunca_e_servida():
    """Defesa em profundidade: uma linha negativa que lá esteja (de antes
    desta regra, ou escrita por outro caminho) não se serve."""
    db = _BaseComMemoria()
    from api.routes import connection_query as cq
    from core.privacidade import cache_semantico
    from db.models import SemanticCacheRecord

    errada = _resposta(RESPOSTA_ERRADA_DE_ONTEM, [], sql="SELECT 1 WHERE false")
    db.guardados.append(
        SemanticCacheRecord(
            connection_id="conn-1",
            space_id="s-1",
            crew_id="crew-1",
            question="¿Qué vehículos no se pagan?",
            embedding=[0.0, 0.1, 0.2],
            response_json=cache_semantico.payload_para_cache(errada),
            locale="es",
            cache_version=cq.VERSAO_DA_CACHE_SEMANTICA,
            temporal_bucket="absoluto",
            context_fingerprint=cache_semantica.impressao_das_definicoes(_pedido()),
        )
    )
    certa = _resposta("03-GH-19: −15.936 €.", LINHAS)
    resposta, correu = _perguntar(db, _pedido(), certa)

    assert correu
    assert resposta.answer == certa.answer


def test_resposta_com_linhas_e_gravada():
    db = _BaseComMemoria()
    _perguntar(db, _pedido(), _resposta("03-GH-19 no se paga: −15.936 €.", LINHAS))
    assert len(db.guardados) == 1


def test_sql_do_merger_multi_fonte_nao_e_gravado():
    """``dataset_1`` só existe dentro do pedido: um acerto nunca o consegue
    voltar a correr (produção: ``semantic_cache_rerun_failed`` em todas as
    perguntas multi-fonte). Guardá-lo só enchia a tabela."""
    db = _BaseComMemoria()
    _perguntar(
        db,
        _pedido(),
        _resposta(
            "Viñedos del Duero Rueda Verdejo: 15.349 unidades.",
            [{"producto": "Viñedos del Duero Rueda Verdejo", "unidades": 15349}],
            sql="SELECT p.name, SUM(d1.q) FROM dataset_1 d1 JOIN dataset_3 p ON p.id = d1.product_id GROUP BY 1",
        ),
    )
    assert db.guardados == []


def test_versao_da_cache_subiu_para_descartar_as_respostas_antigas():
    """As linhas da v4 em produção (a de «No hay vehículos…» incluída) nunca
    mais são servidas."""
    from api.routes import connection_query as cq

    assert cq.VERSAO_DA_CACHE_SEMANTICA >= 5
