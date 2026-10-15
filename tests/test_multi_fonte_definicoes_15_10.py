"""Produção, 15/10/2026 — sandbox, «Logística y Transporte» (3 ligações:
Flota = fleet, Operaciones = ops, Carga = freight).

Verdade na base (SQL directo, só leitura, na `skydemo`):

* «Portes fuera de plazo» (métrica semeada: ``delivered_at > promised_at +
  sla_minutes``): Lisboa–Madrid 74,0 %, Porto–Madrid 64,3 %, as outras 18
  rotas ≤ 6,9 %. Sem a tolerância do cliente, 2.629 de 3.953 portes (66,5 %)
  parecem tarde — e foi isso que a IA respondeu (Porto→Madrid 94,38 %).
* «Vehículos que no se pagan» (``ingreso < coste`` com gasóleo, horas,
  portagens, oficina e custo fixo): 03-GH-19, aportação −15.936 €. A IA disse
  que nenhum.

Três defeitos do caminho multi-fonte:

1. As métricas e o glossário do espaço chegam nas instruções, mas só o
   orquestrador e o formatador as liam. As fatias e o merger — quem escreve o
   SQL — nunca as viam: a fatia de Operaciones decidiu «tarde» sozinha, sem a
   tolerância que vive em Carga.
2. «¿Qué rutas incumplen el plazo del cliente?»: o merger fez INNER JOIN das
   viagens às que falharam; total = falhadas, 100 % nas 20 rotas.
3. «¿Qué vehículos no se pagan?»: o merger acabou com ``WHERE
   fixed_cost_month = 0`` sobre UM conjunto, 0 linhas, e o formatador
   escreveu «todos generan una aportación positiva».
"""

from __future__ import annotations

from core.agents.generic_sql_agent import AgentConfig, TableSchema

CONHECIMENTO = """# Trusted metrics (prefer these over ad-hoc derivations)
- Cumplimiento de plazo [SPACE] — Portes que llegan dentro de la tolerancia CONTRATADA de cada cliente — no contra una hora fija igual para todos. (unit: %)
- Portes fuera de plazo [SPACE] — Portes entregados después de la hora prometida más la tolerancia del cliente. (unit: portes)
- Vehículos que no se pagan [SPACE] — Vehículos cuya aportación en el periodo es negativa: lo que facturan sus portes no cubre lo que el propio camión cuesta (gasóleo, horas de conductor, peajes, taller y coste fijo mensual). (unit: vehículos)

# Glossary
- **Plazo del cliente**  — Los minutos de tolerancia acordados con cada cliente antes de que la llegada cuente como retraso.

Responde siempre en dos frases."""

PERGUNTA_PCT = "¿Qué rutas tienen el mayor porcentaje de portes fuera de plazo?"
PERGUNTA_RUTAS = "¿Qué rutas incumplen el plazo del cliente?"
PERGUNTA_FROTA = "¿Qué vehículos no se pagan?"


class _LLM:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.mensagens = []

    def invoke(self, msgs, **_):
        self.mensagens.append(msgs)
        r = self.respostas.pop(0) if self.respostas else "SELECT 1 AS fim"

        class R:
            content = r

        return R()


def _cfg():
    return AgentConfig(id="t", name="t", tables=[])


# ── 1. As definições chegam a quem escreve o SQL ───────────────────────


def test_definicoes_tiram_metricas_e_glossario_e_deixam_o_estilo():
    from core.llm.multi_fonte import definicoes_do_espaco

    d = definicoes_do_espaco(CONHECIMENTO, PERGUNTA_PCT)
    assert "Portes fuera de plazo" in d and "tolerancia del cliente" in d
    assert "Plazo del cliente" in d
    assert "Vehículos que no se pagan" in d
    assert "dos frases" not in d


def test_definicoes_sem_conhecimento_e_vazio():
    from core.llm.multi_fonte import definicoes_do_espaco

    assert definicoes_do_espaco(None) == ""
    assert definicoes_do_espaco("Responde en castellano.") == ""


def test_definicoes_acima_do_limite_preferem_as_da_pergunta():
    from core.llm.multi_fonte import definicoes_do_espaco

    muitas = "# Trusted metrics\n" + "\n".join(
        f"- Métrica de relleno {i} [SPACE] — algo que no tiene nada que ver {i}"
        for i in range(60)
    )
    muitas += "\n- Portes fuera de plazo [SPACE] — después de la hora prometida más la tolerancia del cliente."
    d = definicoes_do_espaco(muitas, PERGUNTA_PCT, limite=400)
    assert "Portes fuera de plazo" in d
    assert len(d) <= 400


def _tabela(nome, fisica, conn, cols):
    return TableSchema(
        logical_name=nome,
        physical_name=fisica,
        description="",
        data_connection_id=conn,
        columns=[{"name": c, "type": "integer"} for c in cols],
    )


def test_cada_fatia_recebe_as_definicoes_e_a_regra_de_nao_decidir_sozinha():
    from core.llm.multi_fonte import executar_fatias

    cfg = AgentConfig(
        id="t",
        name="t",
        tables=[
            _tabela("trips", "ops.trips", "ops", ["id", "route_id", "vehicle_id"]),
            _tabela("routes", "ops.routes", "ops", ["id", "origin", "destination"]),
            _tabela(
                "shipments",
                "freight.shipments",
                "carga",
                ["id", "trip_id", "client_id"],
            ),
            _tabela("clients", "freight.clients", "carga", ["id", "sla_minutes"]),
        ],
    )
    vistos = {}

    def especialista(st, *_):
        vistos[st["chosen_table"]] = st["contrato_da_fatia"]
        return {**st, "data": [{"x": 1}], "sql": "SELECT 1"}

    executar_fatias(
        {"question": PERGUNTA_PCT, "instructions": CONHECIMENTO},
        cfg,
        ["trips", "routes", "shipments", "clients"],
        {"ops": object(), "carga": object()},
        object(),
        None,
        especialista,
    )
    assert len(vistos) == 2
    for contrato in vistos.values():
        assert "BUSINESS DEFINITIONS" in contrato
        assert "más la tolerancia del cliente" in contrato
        assert "do NOT decide the condition here" in contrato
        assert "dos frases" not in contrato


def test_sem_conhecimento_o_contrato_fica_como_estava():
    from core.llm.multi_fonte import Fatia, contrato_da_fatia

    a = Fatia(connection_id="a", tabelas=[_tabela("trips", "ops.trips", "a", ["id"])])
    b = Fatia(
        connection_id="b", tabelas=[_tabela("shipments", "f.s", "b", ["trip_id"])]
    )
    assert "BUSINESS DEFINITIONS" not in contrato_da_fatia(a, [b])


def test_merger_recebe_as_definicoes_e_as_regras_15_a_17():
    from core.llm.merger import run_merger

    llm = _LLM(["```sql\nSELECT 1 AS a, 2 AS b\n```"])
    run_merger(
        {
            "question": PERGUNTA_PCT,
            "instructions": CONHECIMENTO,
            "multi_fonte_por_ligacao": True,
            "partial_results": [
                {"table": "shipments", "data": [{"trip_id": 1}], "metadata": {}},
                {"table": "trips", "data": [{"trip_id": 1}], "metadata": {}},
            ],
        },
        _cfg(),
        llm,
    )
    sistema, user = llm.mensagens[0][0]["content"], llm.mensagens[0][1]["content"]
    assert "15. A share or percentage per group" in sistema
    assert "16. A comparison between measures of different datasets" in sistema
    assert "17. BUSINESS DEFINITIONS" in sistema
    assert "BUSINESS DEFINITIONS (mandatory" in user
    assert "más la tolerancia del cliente" in user


# ── 2. «Las 20 rutas incumplen el 100 %» ───────────────────────────────

# Conjuntos à escala do caso: rota 4 com 3 de 4 viagens a falhar, rota 9
# com 0 de 3, rota 2 com 1 de 4. dataset_1 = Carga (portes com a decisão
# da tolerância), dataset_2 = Operaciones (viagem → rota).
CARGA = [
    {"trip_id": t, "has_sla_breach": b}
    for t, b in [(1, True), (2, True), (3, True), (4, False),
                 (5, False), (6, False), (7, False),
                 (8, True), (9, False), (10, False), (11, False)]
]  # fmt: skip
OPERACIONES = [
    {"trip_id": t, "route_id": r, "origin": o, "destination": d}
    for t, r, o, d in [(1, 4, "Lisboa", "Madrid"), (2, 4, "Lisboa", "Madrid"),
                       (3, 4, "Lisboa", "Madrid"), (4, 4, "Lisboa", "Madrid"),
                       (5, 9, "Porto", "Coimbra"), (6, 9, "Porto", "Coimbra"),
                       (7, 9, "Porto", "Coimbra"),
                       (8, 2, "Lisboa", "Porto"), (9, 2, "Lisboa", "Porto"),
                       (10, 2, "Lisboa", "Porto"), (11, 2, "Lisboa", "Porto")]
]  # fmt: skip

# O SQL que o merger escreveu em produção (15/10, trace 561a36a8…).
SQL_PRODUCAO_100 = """```sql
WITH breaching_trips AS (
    SELECT DISTINCT trip_id FROM dataset_1 WHERE has_sla_breach = true
),
route_breach AS (
    SELECT d2.route_id, d2.origin, d2.destination,
        COUNT(DISTINCT d2.trip_id) AS total_trips,
        COUNT(DISTINCT bt.trip_id) AS breaching_trips,
        ROUND(COUNT(DISTINCT bt.trip_id) * 100.0 / NULLIF(COUNT(DISTINCT d2.trip_id), 0), 2) AS breach_pct
    FROM dataset_2 d2
    INNER JOIN breaching_trips bt ON d2.trip_id = bt.trip_id
    GROUP BY d2.route_id, d2.origin, d2.destination
)
SELECT route_id, origin, destination, total_trips, breaching_trips, breach_pct
FROM route_breach ORDER BY breaching_trips DESC, breach_pct DESC
```"""

SQL_CERTO = """```sql
SELECT d2.route_id, d2.origin, d2.destination,
       COUNT(*) AS total_trips,
       COUNT(*) FILTER (WHERE d1.has_sla_breach) AS breaching_trips,
       ROUND(100.0 * COUNT(*) FILTER (WHERE d1.has_sla_breach) / COUNT(*), 2) AS breach_pct
FROM dataset_2 d2 LEFT JOIN dataset_1 d1 ON d1.trip_id = d2.trip_id
GROUP BY 1, 2, 3 ORDER BY breach_pct DESC
```"""


def _estado_rutas():
    return {
        "question": PERGUNTA_RUTAS,
        "instructions": CONHECIMENTO,
        "multi_fonte_por_ligacao": True,
        "partial_results": [
            {"table": "shipments, clients", "data": CARGA, "metadata": {}},
            {"table": "trips, routes", "data": OPERACIONES, "metadata": {}},
        ],
    }


def test_sql_de_producao_dava_100_em_todas_as_rotas():
    # A prova de que o SQL de produção é o defeito, não os dados.
    from core.llm.merger import resultado_suspeito
    from core.data_manager.duck_engine import DuckEngine

    e = DuckEngine()
    try:
        e.register_data("dataset_1", CARGA)
        e.register_data("dataset_2", OPERACIONES)
        sql = SQL_PRODUCAO_100.strip("`").removeprefix("sql").strip()
        linhas = e.execute(sql)
    finally:
        e.close()
    assert {float(r["breach_pct"]) for r in linhas} == {100.0}
    assert "100 % in every one" in resultado_suspeito(linhas, 2)


def test_merger_reve_a_percentagem_de_100_em_todas_as_linhas():
    from core.llm.merger import run_merger

    llm = _LLM([SQL_PRODUCAO_100, SQL_CERTO])
    r = run_merger(_estado_rutas(), _cfg(), llm)
    assert len(llm.mensagens) == 2
    assert "100 % in every one" in llm.mensagens[1][-1]["content"]
    pct = {row["route_id"]: float(row["breach_pct"]) for row in r["data"]}
    assert pct == {4: 75.0, 2: 25.0, 9: 0.0}


def test_revisao_que_continua_suspeita_fica_com_a_primeira():
    from core.llm.merger import run_merger

    llm = _LLM([SQL_PRODUCAO_100, SQL_PRODUCAO_100])
    r = run_merger(_estado_rutas(), _cfg(), llm)
    assert len(llm.mensagens) == 2  # uma revisão só, nunca um ciclo
    assert r["data"] and not r.get("merge_failure")


def test_percentagens_que_nao_sao_todas_100_nao_pedem_revisao():
    from core.llm.merger import run_merger

    llm = _LLM([SQL_CERTO])
    r = run_merger(_estado_rutas(), _cfg(), llm)
    assert len(llm.mensagens) == 1
    assert len(r["data"]) == 3


# ── 3. «¿Qué vehículos no se pagan?» → 0 linhas e «todos se pagan» ─────

FLOTA = [
    {"vehicle_id": 3, "plate": "03-GH-19", "fixed_cost_month": 1500.0, "total_maintenance_cost": 22185.78},
    {"vehicle_id": 13, "plate": "13-IJ-49", "fixed_cost_month": 1500.0, "total_maintenance_cost": 4100.0},
]  # fmt: skip
VIAGENS = [
    {"trip_id": 1, "vehicle_id": 3, "coste_variable": 18000.0},
    {"trip_id": 2, "vehicle_id": 13, "coste_variable": 60000.0},
]
PORTES = [
    {"trip_id": 1, "total_revenue": 42534.0},
    {"trip_id": 2, "total_revenue": 126875.0},
]

# O SQL com que o merger acabou em produção (15/10, trace 0592c509…).
SQL_PRODUCAO_VAZIO = """```sql
SELECT v.vehicle_id, v.plate,
    CAST(v.fixed_cost_month AS DECIMAL) + CAST(v.total_maintenance_cost AS DECIMAL) AS total_cost
FROM dataset_1 v
WHERE CAST(v.fixed_cost_month AS DECIMAL) = 0
   OR CAST(v.total_maintenance_cost AS DECIMAL) = 0
ORDER BY total_cost ASC
```"""

SQL_FROTA_CERTO = """```sql
WITH custo AS (SELECT vehicle_id, SUM(coste_variable) AS variavel FROM dataset_2 GROUP BY 1),
receita AS (SELECT t.vehicle_id, SUM(p.total_revenue) AS ingreso
            FROM dataset_3 p JOIN dataset_2 t ON t.trip_id = p.trip_id GROUP BY 1)
SELECT f.plate, ROUND(r.ingreso - (c.variavel + f.total_maintenance_cost + f.fixed_cost_month * 12)) AS aportacion
FROM dataset_1 f JOIN custo c USING (vehicle_id) JOIN receita r USING (vehicle_id)
WHERE r.ingreso < c.variavel + f.total_maintenance_cost + f.fixed_cost_month * 12
```"""


def _estado_frota():
    return {
        "question": PERGUNTA_FROTA,
        "instructions": CONHECIMENTO,
        "multi_fonte_por_ligacao": True,
        "partial_results": [
            {"table": "vehicles, maintenance_jobs", "data": FLOTA, "metadata": {}},
            {"table": "trips", "data": VIAGENS, "metadata": {}},
            {"table": "shipments", "data": PORTES, "metadata": {}},
        ],
    }


def test_merger_reve_zero_linhas_com_tres_conjuntos_cheios():
    from core.llm.merger import run_merger

    llm = _LLM([SQL_PRODUCAO_VAZIO, SQL_FROTA_CERTO])
    r = run_merger(_estado_frota(), _cfg(), llm)
    assert len(llm.mensagens) == 2
    assert (
        "returned 0 rows although every dataset has rows"
        in llm.mensagens[1][-1]["content"]
    )
    assert [row["plate"] for row in r["data"]] == ["03-GH-19"]


def test_zero_linhas_que_continuam_zero_ficam_zero_sem_ciclo():
    from core.llm.merger import run_merger

    llm = _LLM([SQL_PRODUCAO_VAZIO, SQL_PRODUCAO_VAZIO])
    r = run_merger(_estado_frota(), _cfg(), llm)
    assert len(llm.mensagens) == 2
    assert r["data"] == [] and not r.get("merge_failure")


def test_revisao_que_rebenta_fica_com_o_resultado_da_primeira():
    from core.llm.merger import run_merger

    llm = _LLM([SQL_PRODUCAO_VAZIO, "```sql\nSELECT nada FROM dataset_9\n```"])
    r = run_merger(_estado_frota(), _cfg(), llm)
    assert r["data"] == [] and not r.get("merge_failure")


def test_regra_das_zero_linhas_proibe_conclusoes_sobre_os_outros():
    from core.llm.prompts.formatter_prompts import REGRA_ZERO_LINHAS

    assert "Do NOT add claims about the other items" in REGRA_ZERO_LINHAS
