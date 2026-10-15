"""Produção, 16/10/2026 — sandbox, «Alimentación Selecta y Vinos» (3 ligações:
Comercial = trade, Almacén = warehouse, Catálogo = assortment).

«¿Cuáles son los 10 productos más vendidos este año?» alternava entre os
produtos certos e «Lote 81: 5.790 unidades». As vendas estão por LOTE
(``trade.order_lines.lot_id``); o lote leva ao produto
(``warehouse.lots.product_id``); o nome está no catálogo. Os logs dos 4
pedidos (nenhum era cache — ``semantic_cache_rerun_failed``) mostram as
fatias que o modelo escreveu:

* Almacén: ``SELECT product_id, SUM(quantity) FROM warehouse.lots WHERE
  EXTRACT(YEAR FROM received_on) = … GROUP BY product_id LIMIT 10`` — deitou
  fora o id do lote (a ponte para as vendas) e somou o que ENTROU no armazém;
* Comercial: ``SELECT lot_id, SUM(quantity) … GROUP BY lot_id ORDER BY …
  LIMIT 10`` — os 10 lotes mais vendidos, cortados antes de se saber de que
  produto são.

Sem a ponte, o merger escolhia uma de três coisas erradas: agrupar por lote
(«Lote 81»), juntar ``lot_id = product_id``, ou ordenar pela quantidade
recebida. Estes testes fixam o que o código passa a fazer, sem LLM: ver o
defeito no resultado da fatia e pedir UMA correcção com o porquê.
"""

from __future__ import annotations

from core.agents.generic_sql_agent import AgentConfig, TableSchema

PERGUNTA = "¿Cuáles son los 10 productos más vendidos este año?"


def _tabela(nome, fisica, conn, cols):
    return TableSchema(
        logical_name=nome,
        physical_name=fisica,
        description="",
        data_connection_id=conn,
        columns=[{"name": c, "type": "integer"} for c in cols],
    )


TABELAS = [
    _tabela(
        "order_lines",
        "trade.order_lines",
        "com",
        ["id", "order_id", "lot_id", "quantity"],
    ),
    _tabela("orders", "trade.orders", "com", ["id", "ordered_at", "status"]),
    _tabela(
        "lots",
        "warehouse.lots",
        "alm",
        ["id", "product_id", "lot_code", "received_on", "quantity"],
    ),
    _tabela("products", "assortment.products", "cat", ["id", "sku", "name", "family"]),
]

# Os resultados que as fatias devolveram em produção (forma e SQL reais).
COMERCIAL_CORTADO = {
    "sql": (
        'SELECT ol."lot_id", SUM(ol."quantity") AS total_quantity FROM trade."order_lines" ol '
        'JOIN trade."orders" o ON ol."order_id" = o."id" WHERE EXTRACT(YEAR FROM o."ordered_at") '
        '= EXTRACT(YEAR FROM CURRENT_DATE) GROUP BY ol."lot_id" ORDER BY total_quantity DESC LIMIT 10'
    ),
    "data": [{"lot_id": 81 - i, "total_quantity": 5790 - 100 * i} for i in range(10)],
}
ALMACEN_SEM_PONTE = {
    "sql": (
        'SELECT "product_id", SUM("quantity") AS total_quantity FROM warehouse.lots WHERE '
        'EXTRACT(YEAR FROM "received_on") = EXTRACT(YEAR FROM CURRENT_DATE) GROUP BY '
        '"product_id" ORDER BY total_quantity DESC LIMIT 10'
    ),
    "data": [{"product_id": i, "total_quantity": 15349 - 50 * i} for i in range(1, 11)],
}
CATALOGO = {
    "sql": 'SELECT "id", "sku", "name", "family" FROM assortment.products LIMIT 5000',
    "data": [
        {"id": i, "sku": f"S{i}", "name": f"Producto {i}", "family": "Vino"}
        for i in range(1, 73)
    ],
}
# O que as fatias devem devolver.
COMERCIAL_INTEIRO = {
    "sql": COMERCIAL_CORTADO["sql"].replace("LIMIT 10", "LIMIT 5000"),
    "data": [{"lot_id": i, "total_quantity": 100 + i} for i in range(1, 227)],
}
ALMACEN_PONTE = {
    "sql": 'SELECT "id" AS lot_id, "product_id" FROM warehouse.lots LIMIT 5000',
    "data": [{"lot_id": i, "product_id": 1 + i % 72} for i in range(1, 300)],
}


def _fatias():
    from core.llm.multi_fonte import Fatia

    com = Fatia("com", [TABELAS[0], TABELAS[1]])
    alm = Fatia("alm", [TABELAS[2]])
    cat = Fatia("cat", [TABELAS[3]])
    return com, alm, cat


# ── o defeito vê-se no resultado ──────────────────────────────────────────


def test_fatia_do_armazem_sem_o_id_do_lote_e_um_defeito():
    from core.llm.multi_fonte import defeitos_da_fatia

    com, alm, cat = _fatias()
    defeitos = defeitos_da_fatia(
        alm, ALMACEN_SEM_PONTE, [(com, COMERCIAL_CORTADO), (cat, CATALOGO)]
    )
    assert any("lot_id" in d and "lots" in d for d in defeitos), defeitos


def test_fatia_comercial_cortada_em_top_10_e_um_defeito():
    from core.llm.multi_fonte import defeitos_da_fatia

    com, alm, cat = _fatias()
    defeitos = defeitos_da_fatia(
        com, COMERCIAL_CORTADO, [(alm, ALMACEN_PONTE), (cat, CATALOGO)]
    )
    assert any("LIMIT 10" in d for d in defeitos), defeitos


def test_fatias_certas_nao_tem_defeito():
    from core.llm.multi_fonte import defeitos_da_fatia

    com, alm, cat = _fatias()
    todas = [(com, COMERCIAL_INTEIRO), (alm, ALMACEN_PONTE), (cat, CATALOGO)]
    for i, (f, r) in enumerate(todas):
        outros = [p for j, p in enumerate(todas) if j != i]
        assert defeitos_da_fatia(f, r, outros) == [], f.connection_id


def test_catalogo_com_id_serve_de_ponte_para_product_id():
    from core.llm.multi_fonte import defeitos_da_fatia

    com, alm, cat = _fatias()
    assert defeitos_da_fatia(cat, CATALOGO, [(alm, ALMACEN_PONTE)]) == []


def test_tabela_irma_que_a_fatia_nao_usou_nao_e_defeito():
    """Prova com modelos reais (16/10), «¿Qué vehículos no se pagan?»: a fatia
    da frota (vehicles, drivers, maintenance_jobs) devolveu um carro por linha;
    a de operações devolveu driver_id. Exigir o id dos condutores fez o modelo
    cruzar vehicles × drivers (48 linhas, aportações duplicadas). drivers não
    foi usado como ponte (nenhuma chave dele no resultado): não é defeito."""
    from core.llm.multi_fonte import Fatia, defeitos_da_fatia

    frota = Fatia(
        "fleet",
        [
            _tabela(
                "vehicles",
                "fleet.vehicles",
                "fleet",
                ["id", "plate", "fixed_cost_month"],
            ),
            _tabela(
                "drivers", "fleet.drivers", "fleet", ["id", "name", "cost_per_hour"]
            ),
            _tabela(
                "maintenance_jobs",
                "fleet.maintenance_jobs",
                "fleet",
                ["id", "vehicle_id", "cost"],
            ),
        ],
    )
    ops = Fatia(
        "ops", [_tabela("trips", "ops.trips", "ops", ["id", "vehicle_id", "driver_id"])]
    )
    r_frota = {
        "sql": "SELECT v.id AS vehicle_id, v.plate FROM fleet.vehicles v LIMIT 5000",
        "data": [{"vehicle_id": i, "plate": f"P{i}"} for i in range(1, 9)],
    }
    r_ops = {
        "sql": "SELECT id AS trip_id, vehicle_id, driver_id FROM ops.trips LIMIT 5000",
        "data": [
            {"trip_id": i, "vehicle_id": 1 + i % 8, "driver_id": 1 + i % 6}
            for i in range(1, 50)
        ],
    }
    assert defeitos_da_fatia(frota, r_frota, [(ops, r_ops)]) == []


def test_uma_fatia_so_nao_tem_defeito_de_limit():
    """Sem outras fatias, o top-N da própria fatia é a resposta."""
    from core.llm.multi_fonte import defeitos_da_fatia

    com, _, _ = _fatias()
    assert defeitos_da_fatia(com, COMERCIAL_CORTADO, []) == []


# ── e corrige-se com UMA nova tentativa ───────────────────────────────────


def _cfg():
    return AgentConfig(id="t", name="t", tables=TABELAS)


def test_executar_fatias_pede_correcao_com_o_porque_e_usa_a_nova():
    from core.llm.multi_fonte import executar_fatias

    primeiras = {"com": COMERCIAL_CORTADO, "alm": ALMACEN_SEM_PONTE, "cat": CATALOGO}
    segundas = {"com": COMERCIAL_INTEIRO, "alm": ALMACEN_PONTE}
    feedbacks = {}

    def especialista(st, cfg, src, llm):
        cid = st["chosen_table"]
        conn = {"order_lines": "com", "lots": "alm", "products": "cat"}[cid]
        if st.get("feedback_da_fatia"):
            feedbacks[conn] = st["feedback_da_fatia"]
            return {**st, **segundas[conn]}
        return {**st, **primeiras[conn]}

    resultados, _, falhadas = executar_fatias(
        {"question": PERGUNTA},
        _cfg(),
        ["order_lines", "orders", "lots", "products"],
        {"com": object(), "alm": object(), "cat": object()},
        object(),
        None,
        especialista,
    )
    assert not falhadas
    por_conn = {r["connection_id"]: r for r in resultados}
    # O armazém volta com a ponte (id do lote → produto)…
    assert set(por_conn["alm"]["data"][0]) == {"lot_id", "product_id"}
    assert "lot_id" in feedbacks["alm"]
    # …o comercial volta inteiro…
    assert len(por_conn["com"]["data"]) == 226
    assert "LIMIT 10" in feedbacks["com"]
    # …e o catálogo, que estava certo, não é pedido outra vez.
    assert "cat" not in feedbacks
    assert len(por_conn["cat"]["data"]) == 72


def test_correcao_pior_que_a_primeira_e_ignorada():
    from core.llm.multi_fonte import executar_fatias

    def especialista(st, cfg, src, llm):
        conn = {"order_lines": "com", "lots": "alm", "products": "cat"}[
            st["chosen_table"]
        ]
        if conn == "alm" and st.get("feedback_da_fatia"):
            return {**st, "sql": "SELECT 1", "data": []}  # a correcção falhou
        return {
            **st,
            **{"com": COMERCIAL_INTEIRO, "alm": ALMACEN_SEM_PONTE, "cat": CATALOGO}[
                conn
            ],
        }

    resultados, _, _ = executar_fatias(
        {"question": PERGUNTA},
        _cfg(),
        ["order_lines", "orders", "lots", "products"],
        {"com": object(), "alm": object(), "cat": object()},
        object(),
        None,
        especialista,
    )
    alm = next(r for r in resultados if r["connection_id"] == "alm")
    assert alm["data"] == ALMACEN_SEM_PONTE["data"]


# ── o contrato e o merger dizem-no ────────────────────────────────────────


def test_contrato_da_fatia_explica_a_ponte_e_o_top_n():
    from core.llm.multi_fonte import contrato_da_fatia

    com, alm, cat = _fatias()
    contrato = contrato_da_fatia(alm, [com, cat])
    assert "BRIDGE" in contrato
    assert "no period filter on its own dates" in contrato
    assert "ranking is decided AFTER the join" in contrato


def test_merger_agrupa_pelo_produto_e_nunca_pelo_lote():
    from core.llm.merger import _generate_merger_prompt_por_ligacao

    sistema = _generate_merger_prompt_por_ligacao(
        PERGUNTA,
        [
            {
                "table": "order_lines, orders",
                "data": COMERCIAL_INTEIRO["data"],
                "metadata": {},
            },
            {"table": "lots", "data": ALMACEN_PONTE["data"], "metadata": {}},
            {"table": "products", "data": CATALOGO["data"], "metadata": {}},
        ],
        "",
    )[0]["content"]
    assert "a lot or batch is never a product" in sistema
    assert "Rank (ORDER BY ... LIMIT N) only after aggregating to the item" in sistema
