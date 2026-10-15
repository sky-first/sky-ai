# -*- coding: utf-8 -*-
"""Bateria de perguntas reais no sandbox de produção, 14/10/2026.

Cada pergunta foi feita duas vezes pelo `/ai/query` do backend, como membro
do projecto. Os defeitos que eram do `sky-ai`, cada um preso aqui pelo
COMPORTAMENTO (o texto que sai, o encaminhamento, a pista que a fatia
recebe), com o esquema de `sky-backend/scripts/demo/seed_*.sql`.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.llm.numeros import CorrecaoEmFluxo, corrigir_resposta, regras_de_numeros

# ── 4. «1.252 units» numa resposta em castelhano ──────────────────────────

SQL_PRODUTOS = """SELECT p.name AS producto, SUM(ol.quantity) AS total_vendido
FROM trade.order_lines ol JOIN warehouse.lots l ON l.id = ol.lot_id
JOIN assortment.products p ON p.id = l.product_id
JOIN trade.orders o ON o.id = ol.order_id
WHERE o.ordered_at >= DATE_TRUNC('year', CURRENT_DATE)
GROUP BY p.name ORDER BY total_vendido DESC LIMIT 10"""
LINHAS_PRODUTOS = [
    {"producto": "Queso Artesano 40", "total_vendido": 1252},
    {"producto": "Queso Artesano 46", "total_vendido": 1149},
    {"producto": "Ibérico Origen 47", "total_vendido": 1145},
]


def test_units_em_ingles_numa_resposta_em_castelhano_sai_unidades():
    texto = (
        "Los 10 productos más vendidos este año son:\n\n"
        "1. Queso Artesano 40 — 1.252 units\n2. Queso Artesano 46 — 1.149 units"
    )
    out = corrigir_resposta(texto, "es", LINHAS_PRODUTOS, sql=SQL_PRODUTOS)
    assert "units" not in out
    assert "1.252 unidades" in out and "1.149 unidades" in out


def test_o_prompt_nao_ensina_units_em_castelhano():
    regras = regras_de_numeros(
        "es",
        ["producto", "total_vendido"],
        unidades={"total_vendido": "un"},
        dinheiro=set(),
    )
    import re

    # Nenhum EXEMPLO com «units» (é o que o modelo copia); a prosa em inglês
    # do prompt pode falar de «units».
    assert not re.search(r"\d units", regras), regras
    assert "unidades" in regras
    # e com dinheiro na resposta (o exemplo do «errado» também vinha em inglês)
    regras = regras_de_numeros(
        "es", ["producto", "total_vendido", "importe"], dinheiro={"importe"}
    )
    assert not re.search(r"\d units", regras), regras


def test_em_ingles_continua_units():
    out = corrigir_resposta(
        "Queso Artesano 40 — 1,252 units", "en", LINHAS_PRODUTOS, sql=SQL_PRODUTOS
    )
    assert "1,252 units" in out


# ── 5. «Conservas Costa — 1,79 km» era €/km ────────────────────────────────

SQL_CLIENTES_KM = """SELECT c.name AS cliente, COUNT(*) AS portes,
       ROUND(SUM(s.revenue)) AS facturado,
       ROUND(SUM(s.revenue) / NULLIF(SUM(t.km_run), 0), 2) AS por_km
FROM freight.shipments s
JOIN freight.clients c ON c.id = s.client_id
JOIN ops.trips t ON t.id = s.trip_id
GROUP BY c.id, c.name ORDER BY por_km DESC"""
LINHAS_KM = [
    {"cliente": "Conservas Costa", "portes": 310, "facturado": 191097, "por_km": 1.79},
    {"cliente": "Rações do Sul", "portes": 280, "facturado": 150020, "por_km": 1.75},
]


@pytest.mark.parametrize(
    "escrito",
    [
        "1. **Conservas Costa** — 1,79 km\n2. **Rações do Sul** — 1,75 km",
        "1. Conservas Costa: 1,79/km\n2. Rações do Sul: 1,75/km",
        "1. Conservas Costa, 1,79\n2. Rações do Sul, 1,75",
    ],
)
def test_dinheiro_por_km_sai_em_euros_por_km(escrito):
    out = corrigir_resposta(escrito, "es", LINHAS_KM, sql=SQL_CLIENTES_KM)
    assert "1,79 €/km" in out and "1,75 €/km" in out, out
    assert "1,79 km" not in out


def test_dinheiro_por_km_tambem_pelo_sql_do_merger_e_pela_metrica():
    from core.llm.numeros import analisar_colunas

    sql = (
        "SELECT d1.client_name, ROUND(CAST(d1.total_revenue AS DOUBLE) / "
        "NULLIF(t.total_km, 0), 4) AS revenue_per_km FROM dataset_1 d1 "
        "JOIN dataset_2 t ON t.client_id = d1.client_id"
    )
    din, _, uni = analisar_colunas(["client_name", "revenue_per_km"], sql, {}, None)
    assert "revenue_per_km" in din and uni["revenue_per_km"] == "/km"
    instr = (
        "# Trusted metrics (prefer these over ad-hoc derivations)\n"
        "- Ingreso por kilómetro [PROJECT] — Lo facturado dividido por los km "
        "(unit: EUR/km)\n"
    )
    din, _, uni = analisar_colunas(["ingreso_por_kilometro"], None, {}, instr)
    assert "ingreso_por_kilometro" in din and uni["ingreso_por_kilometro"] == "/km"


def test_distancia_continua_a_ser_km():
    from core.llm.numeros import analisar_colunas

    sql = "SELECT d.name AS conductor, SUM(t.km_run) AS total_km FROM ops.trips t GROUP BY 1"
    din, _, uni = analisar_colunas(["conductor", "total_km"], sql, {}, None)
    assert "total_km" not in din and uni["total_km"] == "km"
    out = corrigir_resposta(
        "Sérgio Monteiro ha recorrido 4040 km el último mes.",
        "es",
        [{"conductor": "Sérgio Monteiro", "total_km": 4040}],
        sql=sql,
    )
    assert "4.040 km" in out and "€" not in out


def test_dinheiro_sobre_dinheiro_nao_ganha_divisor():
    from core.llm.numeros import analisar_colunas

    sql = "SELECT SUM(cost) / NULLIF(SUM(revenue), 0) AS ratio_coste FROM x"
    _, _, uni = analisar_colunas(["ratio_coste"], sql, {}, None)
    assert "ratio_coste" not in uni


def test_o_prompt_diz_que_e_dinheiro_por_km():
    regras = regras_de_numeros(
        "es",
        ["cliente", "por_km"],
        unidades={"por_km": "/km"},
        dinheiro={"por_km"},
    )
    assert "1,79 €/km" in regras and "MONEY PER km" in regras


def test_streaming_da_o_mesmo_que_o_texto_inteiro_no_euro_por_km():
    texto = "Conservas Costa — 1,79 km de ingreso y Rações do Sul — 1,75 km."
    fluxo = CorrecaoEmFluxo("es", LINHAS_KM, sql=SQL_CLIENTES_KM)
    saida = "".join(fluxo.receber(texto[i : i + 3]) for i in range(0, len(texto), 3))
    saida += fluxo.terminar()
    assert saida == corrigir_resposta(texto, "es", LINHAS_KM, sql=SQL_CLIENTES_KM)
    assert "1,79 €/km" in saida


# ── 6. «Todos superan los 25.000 pedidos» sobre unidades ───────────────────

SQL_PLATOS = """SELECT p.name AS plato, SUM(oi.quantity) AS unidades_vendidas
FROM sales.order_items oi JOIN catalog.products p ON p.id = oi.product_id
GROUP BY p.name ORDER BY unidades_vendidas DESC LIMIT 5"""
LINHAS_PLATOS = [
    {"plato": "Alitas 12", "unidades_vendidas": 25436},
    {"plato": "Donut", "unidades_vendidas": 25425},
    {"plato": "Picante", "unidades_vendidas": 25181},
]


def test_pedidos_numa_resposta_sobre_unidades_sai_unidades():
    texto = (
        "1. Alitas 12 — 25.436 unidades\n2. Donut — 25.425 unidades\n\n"
        "Las ventas están muy concentradas. Todos superan los 25.000 pedidos."
    )
    out = corrigir_resposta(texto, "es", LINHAS_PLATOS, sql=SQL_PLATOS)
    assert "pedidos" not in out
    assert "superan las 25.000 unidades" in out


def test_pedidos_de_verdade_ficam():
    sql = "SELECT store AS tienda, COUNT(*) AS pedidos, SUM(qty) AS unidades FROM x GROUP BY 1"
    linhas = [{"tienda": "Badajoz", "pedidos": 120, "unidades": 300}]
    out = corrigir_resposta("Badajoz tuvo 120 pedidos.", "es", linhas, sql=sql)
    assert "120 pedidos" in out


def test_uma_contagem_sem_nome_impede_a_troca():
    # COUNT(*) AS total pode contar encomendas: na dúvida não se mexe.
    sql = "SELECT p.name AS plato, COUNT(*) AS total, SUM(q) AS unidades FROM x GROUP BY 1"
    linhas = [{"plato": "Donut", "total": 900, "unidades": 25425}]
    out = corrigir_resposta("Donut aparece en 900 pedidos.", "es", linhas, sql=sql)
    assert "900 pedidos" in out


def test_o_prompt_diz_que_a_coluna_conta_unidades_e_nao_pedidos():
    regras = regras_de_numeros(
        "es", ["plato", "unidades_vendidas"], unidades={"unidades_vendidas": "un"}
    )
    assert "NOT orders" in regras and "never «pedidos»" in regras


def test_streaming_troca_o_artigo_sem_partir_o_que_ja_saiu():
    texto = "Todos superan los 25.000 pedidos. Picante es el tercero."
    fluxo = CorrecaoEmFluxo("es", LINHAS_PLATOS, sql=SQL_PLATOS)
    saida = "".join(fluxo.receber(texto[i : i + 4]) for i in range(0, len(texto), 4))
    saida += fluxo.terminar()
    assert saida == corrigir_resposta(texto, "es", LINHAS_PLATOS, sql=SQL_PLATOS)
    assert "las 25.000 unidades" in saida


# ── 7. «¿Qué vehículos no se pagan?» ia para a conversa ───────────────────

CONHECIMENTO_TRANSPORTES = """# Trusted metrics (prefer these over ad-hoc derivations)
- Coste por kilómetro [PROJECT] — Todo lo que el camión consume, partido por lo que rodó (unit: EUR/km)
- Ingreso por kilómetro [PROJECT] — Lo facturado dividido por todos los kilómetros (unit: EUR/km)
- Porcentaje en vacío [PROJECT] — Kilómetros recorridos sin ninguna carga (unit: %)
- Aportación por vehículo [PROJECT] — Lo que cada camión ingresa menos lo que cuesta (unit: EUR)

# Glossary
- **Vacío de retorno** [ORG-CERTIFIED] — Un viaje completado al que no corresponde ningún porte facturado.
- **Plazo del cliente** — Los minutos de tolerancia acordados con cada cliente.

Responde siempre con frases cortas.
"""

TABELAS_TRANSPORTES = [
    {"logical_name": "vehicles", "columns": [{"name": "plate"}, {"name": "class"}]},
    {"logical_name": "trips", "columns": [{"name": "km_run"}, {"name": "fuel_litres"}]},
    {
        "logical_name": "shipments",
        "columns": [{"name": "revenue"}, {"name": "trip_id"}],
    },
]


class _ModeloQueDizMundo:
    """O classificador do modelo, como em produção: «MUNDO»."""

    chamadas = 0

    def invoke(self, *a, **k):
        type(self).chamadas += 1
        return SimpleNamespace(content="MUNDO")


def test_vehiculos_no_se_pagan_vai_aos_dados_com_o_vocabulario_do_espaco():
    from core.intent.question_intent import (
        QuestionIntent,
        classify_question_intent,
        termos_do_catalogo,
        termos_do_conhecimento,
    )

    so_catalogo = termos_do_catalogo(TABELAS_TRANSPORTES)
    # Antes: só o catálogo (tabelas em inglês) → o modelo decide → conversa.
    assert (
        classify_question_intent(
            "¿Qué vehículos no se pagan?",
            True,
            llm=_ModeloQueDizMundo(),
            catalog_terms=so_catalogo,
        )
        == QuestionIntent.CONVERSA
    )
    com_conhecimento = so_catalogo | termos_do_conhecimento(CONHECIMENTO_TRANSPORTES)
    assert (
        classify_question_intent(
            "¿Qué vehículos no se pagan?",
            True,
            llm=_ModeloQueDizMundo(),
            catalog_terms=com_conhecimento,
        )
        == QuestionIntent.DATA
    )
    assert (
        classify_question_intent(
            "¿Cuánto gasóleo quemamos en vacío, y en qué trayectos?",
            True,
            llm=_ModeloQueDizMundo(),
            catalog_terms=com_conhecimento,
        )
        == QuestionIntent.DATA
    )


def test_o_vocabulario_vem_so_das_metricas_e_do_glossario():
    from core.intent.question_intent import termos_do_conhecimento

    termos = termos_do_conhecimento(CONHECIMENTO_TRANSPORTES)
    assert {"vehiculo", "vacio", "retorno", "kilometro"} <= termos
    # As instruções livres de quem configurou o espaço não são vocabulário.
    assert "siempre" not in termos and "frase" not in termos
    # Nem a prosa das definições.
    assert "camion" not in termos


def test_um_bom_dia_continua_conversa_com_conhecimento():
    from core.intent.question_intent import (
        QuestionIntent,
        classify_question_intent,
        termos_do_conhecimento,
    )

    assert (
        classify_question_intent(
            "¡Buenos días!",
            True,
            llm=None,
            catalog_terms=termos_do_conhecimento(CONHECIMENTO_TRANSPORTES),
        )
        == QuestionIntent.CONVERSA
    )


def test_o_classificador_do_modelo_sabe_que_vehiculos_sao_da_empresa():
    from core.intent.perguntar_ao_modelo import _INSTRUCOES

    assert "vehicles" in _INSTRUCOES and "pay for themselves" in _INSTRUCOES


# ── 7. «gasóleo en vacío» / «€ por km»: a fatia deitava fora a chave ──────


def _tabela(logical, physical, cols, cid):
    return SimpleNamespace(
        logical_name=logical,
        display_name=logical,
        physical_name=physical,
        data_connection_id=cid,
        columns=[{"name": n, "type": t, "description": ""} for n, t in cols],
    )


TRIPS = _tabela(
    "trips",
    "ops.trips",
    [("id", "integer"), ("vehicle_id", "integer"), ("route_id", "integer"),
     ("km_run", "numeric"), ("fuel_litres", "numeric"), ("status", "text"),
     ("departed_at", "timestamp")],
    "ops",
)  # fmt: skip
ROUTES = _tabela(
    "routes",
    "ops.routes",
    [("id", "integer"), ("origin", "text"), ("destination", "text")],
    "ops",
)
SHIPMENTS = _tabela(
    "shipments",
    "freight.shipments",
    [("id", "integer"), ("trip_id", "integer"), ("client_id", "integer"),
     ("revenue", "numeric"), ("weight_kg", "numeric")],
    "freight",
)  # fmt: skip
CLIENTS = _tabela(
    "clients", "freight.clients", [("id", "integer"), ("name", "text")], "freight"
)
VEHICLES = _tabela(
    "vehicles", "fleet.vehicles", [("id", "integer"), ("plate", "text")], "fleet"
)


def test_a_chave_estrangeira_trip_id_e_sugerida_para_juntar_as_fatias():
    from core.llm.multi_fonte import pistas_de_juncao

    pistas = pistas_de_juncao([TRIPS, ROUTES], [SHIPMENTS, CLIENTS])
    assert any("shipments.trip_id = trips.id" in p for p in pistas), pistas
    pistas = pistas_de_juncao([VEHICLES], [TRIPS])
    assert any("trips.vehicle_id = vehicles.id" in p for p in pistas), pistas


def test_o_contrato_da_fatia_manda_agrupar_pela_chave_estrangeira():
    from core.llm.multi_fonte import Fatia, contrato_da_fatia

    ops = Fatia(connection_id="ops", tabelas=[TRIPS, ROUTES])
    freight = Fatia(connection_id="freight", tabelas=[SHIPMENTS, CLIENTS])
    contrato = contrato_da_fatia(ops, [freight])
    assert "shipments.trip_id = trips.id" in contrato
    assert "foreign key" in contrato and "that key IS the grain" in contrato
    assert "without any shipment" in contrato
    # a tabela apontada (trips.id) devolve uma linha por id
    assert "return one row per id" in contrato
    # «no se pagan»: a comparação custo × receita é do passo de junção
    assert "can only be decided by the join step" in contrato


def test_o_merger_nao_reparte_por_proporcao():
    from core.llm.merger import REGRAS_DE_RACIOCINIO

    assert "Never estimate, apportion or distribute" in REGRAS_DE_RACIOCINIO


def test_entidade_com_plural_em_ies():
    from core.llm.multi_fonte import pistas_de_juncao

    cat = _tabela(
        "categories", "x.categories", [("id", "integer"), ("name", "text")], "a"
    )
    prod = _tabela(
        "products", "y.products", [("id", "integer"), ("category_id", "integer")], "b"
    )
    assert any(
        "products.category_id = categories.id" in p
        for p in pistas_de_juncao([cat], [prod])
    )
