"""Produção, 13/10/2026 — tenant sandbox, projecto «Restauración — Operación
de tiendas», três ligações Postgres: Tiendas (schema ``stores``), Servicio
(``service``) e Cocina (``kitchen``). Caminho multi-fonte ANTIGO (flag
MULTI_FONTE_POR_LIGACAO desligada).

«¿Qué tienda tuvo más pedidos el último mes?» → fatias ``orders`` e
``stores``:
- a fatia ``stores`` escreveu SQL a juntar ``service.orders`` → guardrail →
  fatia perdida (o especialista via a pergunta inteira, sem saber que era só
  uma parte, e não havia segunda tentativa);
- o merger correu com UMA fatia e o modelo escreveu ``FROM orders AS o JOIN
  stores AS s`` — mas as fatias estavam registadas como ``dataset_N`` e a de
  stores nem existia → DuckDB «Table with name orders does not exist»;
- resposta: «Algo falló de nuestro lado…», com a causa conhecida.

O mesmo com «¿Cuáles son los 5 platos más vendidos?» (``order_items`` em
service + ``products`` em kitchen).

O ``INTERVAL '?'`` dos registos é a redacção de literais do log_event
(core/privacidade/registo.sem_literais), não SQL estragado.

Modelos e fontes falsos: o que se testa é o comportamento do pipeline à
volta do modelo — o que ele recebe, o que acontece quando erra.
"""

from __future__ import annotations

from types import SimpleNamespace

from core.agents.generic_sql_agent import AgentConfig, TableSchema

PERGUNTA_TIENDA = "¿Qué tienda tuvo más pedidos el último mes?"
PERGUNTA_PLATOS = "¿Cuáles son los 5 platos más vendidos?"
TECHNICAL_ES = "Algo falló de nuestro lado"


# ── Esquema do sandbox ────────────────────────────────────────────────


def _orders():
    return TableSchema(
        logical_name="orders",
        physical_name="service.orders",
        description="Pedidos servidos en tienda.",
        data_connection_id="006f2967",
        columns=[
            {"name": "order_id", "type": "integer"},
            {"name": "store_id", "type": "integer"},
            {"name": "created_at", "type": "timestamp"},
            {"name": "total", "type": "numeric"},
        ],
    )


def _stores():
    return TableSchema(
        logical_name="stores",
        physical_name="stores.stores",
        description="Tiendas de la cadena.",
        data_connection_id="611b5fb0",
        columns=[
            {"name": "store_id", "type": "integer"},
            {"name": "store_name", "type": "text"},
            {"name": "city", "type": "text"},
        ],
    )


def _order_items():
    return TableSchema(
        logical_name="order_items",
        physical_name="service.order_items",
        description="Líneas de cada pedido.",
        data_connection_id="006f2967",
        columns=[
            {"name": "order_id", "type": "integer"},
            {"name": "product_id", "type": "integer"},
            {"name": "quantity", "type": "integer"},
        ],
    )


def _products():
    return TableSchema(
        logical_name="products",
        physical_name="kitchen.products",
        description="Platos de la carta.",
        data_connection_id="d553b700",
        columns=[
            {"name": "product_id", "type": "integer"},
            {"name": "product_name", "type": "text"},
            {"name": "category", "type": "text"},
        ],
    )


def _cfg():
    return AgentConfig(
        id="t",
        name="t",
        tables=[_orders(), _stores(), _order_items(), _products()],
    )


class _Fonte:
    """Fonte Postgres falsa: devolve sempre as mesmas linhas à consulta."""

    dialect = "postgres"

    def __init__(self, linhas):
        self.linhas = linhas
        self.consultas = []

    def sample_table_rows(self, *_a, **_k):
        return []

    def run_query(self, sql):
        self.consultas.append(sql)
        if sql.strip().upper().startswith("SELECT DISTINCT"):
            return []
        return list(self.linhas)


class _Modelo:
    """Responde, por ordem, com as respostas dadas (a última repete-se)."""

    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.chamadas = []

    def invoke(self, mensagens, *_a, **_k):
        self.chamadas.append(mensagens)
        i = min(len(self.chamadas) - 1, len(self.respostas) - 1)
        return SimpleNamespace(content=self.respostas[i])


def _texto(mensagens):
    return "\n".join(m["content"] for m in mensagens)


# ── 1. Especialista de UMA fatia ───────────────────────────────────────

SQL_STORES_COM_JOIN = (
    "-- TITLE: Tienda con más pedidos\n"
    "SELECT s.store_id, s.store_name, COUNT(o.order_id) AS pedidos\n"
    "FROM stores.stores s JOIN service.orders o ON o.store_id = s.store_id\n"
    "WHERE o.created_at >= NOW() - INTERVAL '1 month'\n"
    "GROUP BY s.store_id, s.store_name ORDER BY pedidos DESC LIMIT 1"
)
SQL_STORES_LIMPO = (
    "-- TITLE: Tiendas\n" "SELECT s.store_id, s.store_name FROM stores.stores s"
)
LINHAS_STORES = [
    {"store_id": 1, "store_name": "Centro"},
    {"store_id": 2, "store_name": "Norte"},
]

SQL_PRODUCTS_COM_JOIN = (
    "-- TITLE: Platos más vendidos\n"
    "SELECT p.product_name, SUM(oi.quantity) AS unidades\n"
    "FROM kitchen.products p JOIN service.order_items oi "
    "ON oi.product_id = p.product_id\n"
    "GROUP BY p.product_name ORDER BY unidades DESC LIMIT 5"
)
SQL_PRODUCTS_LIMPO = (
    "-- TITLE: Platos\n" "SELECT p.product_id, p.product_name FROM kitchen.products p"
)


def _fatia(tabela, fisica, irmas, pergunta):
    return {
        "question": pergunta,
        "detected_language": "es",
        "chosen_table": tabela,
        "chosen_table_physical": fisica,
        "chosen_tables": None,
        "chosen_tables_physical": [fisica],
        "join_relationships": None,
        "multi_source_subquery": True,
        "multi_source_sibling_tables": irmas,
    }


def _correr_fatia(modelo, linhas, tabela, fisica, irmas, pergunta):
    from core.llm.specialist import run_specialist

    fonte = _Fonte(linhas)
    st = run_specialist(_fatia(tabela, fisica, irmas, pergunta), _cfg(), fonte, modelo)
    return st, fonte


def test_a_fatia_sabe_que_e_so_uma_parte_e_quais_sao_as_outras():
    """O especialista de `stores` recebia a pergunta inteira sem saber que
    `orders` vinha de outra ligação — e juntava-a."""
    modelo = _Modelo(SQL_STORES_LIMPO)
    st, _ = _correr_fatia(
        modelo,
        LINHAS_STORES,
        "stores",
        "stores.stores",
        ["orders (service.orders)"],
        PERGUNTA_TIENDA,
    )
    prompt = _texto(modelo.chamadas[0])
    assert "MULTI-SOURCE SLICE" in prompt
    assert "service.orders" in prompt  # sabe qual é a outra fatia
    assert "NEVER JOIN" in prompt
    assert "store_id" in prompt  # pede as colunas de junção
    assert st.get("data") == LINHAS_STORES


def test_guardrail_numa_fatia_tenta_outra_vez_com_o_erro_como_feedback():
    """O caso de produção: a fatia `stores` junta service.orders. Antes:
    impossible_reason «Security Guardrail» e a fatia perdia-se."""
    modelo = _Modelo(SQL_STORES_COM_JOIN, SQL_STORES_LIMPO)
    st, fonte = _correr_fatia(
        modelo,
        LINHAS_STORES,
        "stores",
        "stores.stores",
        ["orders (service.orders)"],
        PERGUNTA_TIENDA,
    )
    assert not st.get("impossible_reason"), st.get("impossible_reason")
    assert st.get("data") == LINHAS_STORES
    assert len(modelo.chamadas) == 2
    feedback = modelo.chamadas[1][-1]["content"]
    assert "BLOCKED" in feedback and "service.orders" in feedback
    # O SQL bloqueado nunca chegou à base.
    assert not any("service.orders" in c for c in fonte.consultas)


def test_guardrail_que_bloqueia_duas_vezes_continua_a_bloquear():
    """A segurança não afrouxa: se a nova tentativa também junta a tabela
    proibida, a fatia é recusada e nada corre na base."""
    modelo = _Modelo(SQL_STORES_COM_JOIN, SQL_STORES_COM_JOIN)
    st, fonte = _correr_fatia(
        modelo,
        LINHAS_STORES,
        "stores",
        "stores.stores",
        ["orders (service.orders)"],
        PERGUNTA_TIENDA,
    )
    assert "Security Guardrail" in (st.get("impossible_reason") or "")
    assert st.get("sql") is None
    assert len(modelo.chamadas) == 2
    assert not any("service.orders" in c for c in fonte.consultas)


def test_fatia_products_dos_platos_tambem_recupera_do_guardrail():
    modelo = _Modelo(SQL_PRODUCTS_COM_JOIN, SQL_PRODUCTS_LIMPO)
    linhas = [{"product_id": 7, "product_name": "Paella"}]
    st, _ = _correr_fatia(
        modelo,
        linhas,
        "products",
        "kitchen.products",
        ["order_items (service.order_items)"],
        PERGUNTA_PLATOS,
    )
    assert not st.get("impossible_reason"), st.get("impossible_reason")
    assert st.get("data") == linhas


def test_fora_do_multi_fonte_nao_ha_bloco_nem_segunda_tentativa():
    """Pergunta normal de uma tabela: o guardrail recusa logo, como antes."""
    from core.llm.specialist import run_specialist

    modelo = _Modelo(SQL_STORES_COM_JOIN, SQL_STORES_LIMPO)
    estado = _fatia("stores", "stores.stores", [], PERGUNTA_TIENDA)
    estado.pop("multi_source_subquery")
    estado.pop("multi_source_sibling_tables")
    st = run_specialist(estado, _cfg(), _Fonte(LINHAS_STORES), modelo)
    assert "Security Guardrail" in (st.get("impossible_reason") or "")
    assert len(modelo.chamadas) == 1
    assert "MULTI-SOURCE SLICE" not in _texto(modelo.chamadas[0])


# ── 2. Merger: nomes no DuckDB ─────────────────────────────────────────

FATIA_ORDERS = {
    "table": "orders",
    "data": [{"store_id": 1, "pedidos": 10}, {"store_id": 2, "pedidos": 30}],
    "sql": "SELECT store_id, COUNT(*) AS pedidos FROM service.orders GROUP BY 1",
    "metadata": {"title": "Pedidos por tienda"},
}
FATIA_STORES = {
    "table": "stores",
    "data": LINHAS_STORES,
    "sql": SQL_STORES_LIMPO,
    "metadata": {"title": "Tiendas"},
}
SQL_MERGER_TIENDA = (
    "```sql\nSELECT s.store_name, o.pedidos\n"
    "FROM orders AS o JOIN stores AS s ON o.store_id = s.store_id\n"
    "ORDER BY o.pedidos DESC LIMIT 1\n```"
)


def _merger(partial, modelo, failed=None, pergunta=PERGUNTA_TIENDA):
    from core.llm.merger import run_merger

    return run_merger(
        {
            "question": pergunta,
            "plan": "Join orders with stores by store_id and rank by orders.",
            "partial_results": partial,
            "failed_slices": failed or [],
        },
        _cfg(),
        modelo,
    )


def test_merger_regista_as_fatias_com_o_nome_logico_da_tabela():
    """O SQL de produção — FROM orders AS o JOIN stores AS s — tem de correr:
    as fatias ficam no DuckDB com os nomes que o modelo vai usar."""
    modelo = _Modelo(SQL_MERGER_TIENDA)
    st = _merger([FATIA_ORDERS, FATIA_STORES], modelo)
    assert not st.get("error"), st.get("error")
    assert st["data"] == [{"store_name": "Norte", "pedidos": 30}]
    prompt = _texto(modelo.chamadas[0])
    assert "`orders`" in prompt and "`stores`" in prompt
    assert "dataset_1" not in prompt
    assert "store_name" in prompt and "pedidos" in prompt  # colunas reais


def test_merger_dos_platos_junta_order_items_e_products():
    fatia_items = {
        "table": "order_items",
        "data": [
            {"product_id": 7, "unidades": 50},
            {"product_id": 8, "unidades": 20},
            {"product_id": 9, "unidades": 90},
        ],
        "sql": "SELECT product_id, SUM(quantity) AS unidades ...",
        "metadata": {},
    }
    fatia_products = {
        "table": "products",
        "data": [
            {"product_id": 7, "product_name": "Paella"},
            {"product_id": 8, "product_name": "Gazpacho"},
            {"product_id": 9, "product_name": "Croquetas"},
        ],
        "sql": SQL_PRODUCTS_LIMPO,
        "metadata": {},
    }
    modelo = _Modelo(
        "```sql\nSELECT p.product_name, oi.unidades FROM order_items oi "
        "JOIN products p ON oi.product_id = p.product_id "
        "ORDER BY oi.unidades DESC LIMIT 5\n```"
    )
    st = _merger([fatia_items, fatia_products], modelo, pergunta=PERGUNTA_PLATOS)
    assert not st.get("error"), st.get("error")
    assert [r["product_name"] for r in st["data"]] == [
        "Croquetas",
        "Paella",
        "Gazpacho",
    ]


def test_merger_com_tabela_inexistente_tenta_outra_vez_com_o_erro():
    modelo = _Modelo(
        "```sql\nSELECT * FROM dataset_1 d1 JOIN dataset_2 d2 USING (store_id)\n```",
        SQL_MERGER_TIENDA,
    )
    st = _merger([FATIA_ORDERS, FATIA_STORES], modelo)
    assert not st.get("error"), st.get("error")
    assert st["data"] == [{"store_name": "Norte", "pedidos": 30}]
    assert len(modelo.chamadas) == 2
    assert "dataset_1" in modelo.chamadas[1][-1]["content"]


# ── 3. Fatia em falta: nunca inventar, nunca «Algo falló» ──────────────


def _formatar(estado, frase="La tienda 2 tuvo 30 pedidos."):
    from core.llm.formatter import run_formatter

    return run_formatter(
        {"detected_language": "es", **estado},
        AgentConfig(id="t", name="t", tables=[]),
        _Modelo(frase),
    )


def test_caso_de_producao_stores_bloqueada_responde_com_orders_e_diz_o_que_falta():
    """Fatia `stores` bloqueada pelo guardrail, só `orders` com dados. O
    merger não pode pedir ao modelo um JOIN a uma tabela que não existe; a
    resposta usa `orders` e diz que `stores` faltou."""
    from core.llm.merger import resultado_da_fatia

    parcial, falha = resultado_da_fatia(
        "orders", {"data": FATIA_ORDERS["data"], "sql": FATIA_ORDERS["sql"]}
    )
    vazia, falha_stores = resultado_da_fatia(
        "stores",
        {
            "impossible_reason": "Security Guardrail: Attempted to access "
            "unauthorized data table (service.orders).",
            "sql": None,
        },
    )
    assert parcial and not falha and not vazia
    assert falha_stores["table"] == "stores"

    modelo = _Modelo(SQL_MERGER_TIENDA)  # o que o modelo escreveu em produção
    st = _merger([parcial], modelo, failed=[falha_stores])
    assert modelo.chamadas == []  # nada a juntar: o modelo nem é chamado
    assert not st.get("error"), st.get("error")
    assert st["data"] == FATIA_ORDERS["data"]

    st = _formatar({**st, "question": PERGUNTA_TIENDA})
    assert TECHNICAL_ES not in st["answer"]
    assert "«stores»" in st["answer"] and "«orders»" in st["answer"]
    assert "La tienda 2 tuvo 30 pedidos." in st["answer"]


def test_nenhuma_fatia_com_dados_diz_que_fontes_faltaram():
    st = _merger(
        [],
        _Modelo(SQL_MERGER_TIENDA),
        failed=[
            {"table": "order_items", "reason": "Security Guardrail"},
            {"table": "products", "reason": "query ran and returned 0 rows"},
        ],
        pergunta=PERGUNTA_PLATOS,
    )
    st = _formatar({**st, "question": PERGUNTA_PLATOS})
    assert TECHNICAL_ES not in st["answer"]
    assert "«order_items»" in st["answer"] and "«products»" in st["answer"]


def test_juncao_que_falha_duas_vezes_e_dita_com_franqueza():
    modelo = _Modelo("```sql\nSELECT * FROM pedidos JOIN tiendas USING (x)\n```")
    st = _merger([FATIA_ORDERS, FATIA_STORES], modelo)
    assert len(modelo.chamadas) == 2
    st = _formatar({**st, "question": PERGUNTA_TIENDA})
    assert TECHNICAL_ES not in st["answer"]
    assert "combinar" in st["answer"]
    assert "«orders»" in st["answer"] and "«stores»" in st["answer"]


def test_as_mensagens_existem_nas_tres_linguas():
    from core.i18n.i18n import MESSAGES

    for chave in (
        "MULTI_SOURCE_PARTIAL",
        "MULTI_SOURCE_NO_SLICES",
        "MULTI_SOURCE_MERGE_FAILED",
    ):
        assert set(MESSAGES[chave]) >= {"en", "pt", "es"}


# ── 4. As fatias no grafo: cada uma na sua ligação, falhas registadas ──


def test_executar_fatias_regista_a_que_falhou_e_diz_a_cada_uma_as_irmas():
    """Antes, a fatia sem dados era deitada fora em silêncio e o merger
    não sabia que faltava `stores`."""
    from core.llm.merger import executar_fatias_por_tabela

    fonte_service, fonte_stores, primaria = object(), object(), object()
    vistos = {}

    def especialista(st, cfg, src, llm):
        vistos[st["chosen_table"]] = (src, st)
        if st["chosen_table"] == "stores":
            return {
                **st,
                "impossible_reason": "Security Guardrail: Attempted to access "
                "unauthorized data table (service.orders).",
                "sql": None,
            }
        return {**st, "data": FATIA_ORDERS["data"], "sql": "SELECT 1"}

    parciais, falhas = executar_fatias_por_tabela(
        {"question": PERGUNTA_TIENDA},
        _cfg(),
        ["orders", "stores"],
        {"006f2967": fonte_service, "611b5fb0": fonte_stores},
        primaria,
        None,
        especialista,
    )
    assert [p["table"] for p in parciais] == ["orders"]
    assert [f["table"] for f in falhas] == ["stores"]
    assert "Security Guardrail" in falhas[0]["reason"]
    assert vistos["orders"][0] is fonte_service
    assert vistos["stores"][0] is fonte_stores
    st_stores = vistos["stores"][1]
    assert st_stores["chosen_tables_physical"] == ["stores.stores"]
    assert st_stores["multi_source_subquery"] is True
    assert st_stores["multi_source_sibling_tables"] == ["orders (service.orders)"]


# ── 5. Três (ou mais) ligações na mesma pergunta ───────────────────────
#
# O plano Enterprise tem até 5 fontes. «Ventas por tienda y familia de
# producto»: stores (Tiendas) + order_items (Servicio) + products (Cocina).

PERGUNTA_3 = "Ventas por tienda y familia de producto"

FATIA_ITEMS_3 = {
    "table": "order_items",
    "data": [
        {"store_id": 1, "product_id": 7, "unidades": 10},
        {"store_id": 1, "product_id": 8, "unidades": 4},
        {"store_id": 2, "product_id": 7, "unidades": 6},
        {"store_id": 2, "product_id": 9, "unidades": 5},
    ],
    "sql": "SELECT store_id, product_id, SUM(quantity) AS unidades ...",
    "metadata": {},
}
FATIA_PRODUCTS_3 = {
    "table": "products",
    "data": [
        {"product_id": 7, "category": "principal"},
        {"product_id": 8, "category": "entrante"},
        {"product_id": 9, "category": "entrante"},
    ],
    "sql": "SELECT product_id, category FROM kitchen.products",
    "metadata": {},
}
SQL_MERGER_3 = (
    "```sql\nSELECT s.store_name, p.category, SUM(oi.unidades) AS unidades\n"
    "FROM order_items oi\n"
    "JOIN stores s ON s.store_id = oi.store_id\n"
    "JOIN products p ON p.product_id = oi.product_id\n"
    "GROUP BY 1, 2 ORDER BY 1, 2\n```"
)


def test_merger_junta_tres_fatias_de_tres_ligacoes():
    modelo = _Modelo(SQL_MERGER_3)
    st = _merger(
        [FATIA_STORES, FATIA_ITEMS_3, FATIA_PRODUCTS_3], modelo, pergunta=PERGUNTA_3
    )
    assert not st.get("error"), st.get("error")
    assert st["data"] == [
        {"store_name": "Centro", "category": "entrante", "unidades": 4},
        {"store_name": "Centro", "category": "principal", "unidades": 10},
        {"store_name": "Norte", "category": "entrante", "unidades": 5},
        {"store_name": "Norte", "category": "principal", "unidades": 6},
    ]
    prompt = _texto(modelo.chamadas[0])
    for nome in ("`stores`", "`order_items`", "`products`"):
        assert nome in prompt


def test_tres_ligacoes_cada_fatia_na_sua_e_uma_falha_fica_registada():
    from core.llm.merger import executar_fatias_por_tabela

    f_tiendas, f_servicio, f_cocina = object(), object(), object()
    vistos = {}

    def especialista(st, cfg, src, llm):
        vistos[st["chosen_table"]] = (src, st)
        if st["chosen_table"] == "products":
            return {**st, "error": "connection refused", "sql": None}
        dados = {"stores": LINHAS_STORES, "order_items": FATIA_ITEMS_3["data"]}
        return {**st, "data": dados[st["chosen_table"]], "sql": "SELECT 1"}

    parciais, falhas = executar_fatias_por_tabela(
        {"question": PERGUNTA_3},
        _cfg(),
        ["stores", "order_items", "products"],
        {"611b5fb0": f_tiendas, "006f2967": f_servicio, "d553b700": f_cocina},
        object(),
        None,
        especialista,
    )
    assert [p["table"] for p in parciais] == ["stores", "order_items"]
    assert [f["table"] for f in falhas] == ["products"]
    assert vistos["stores"][0] is f_tiendas
    assert vistos["order_items"][0] is f_servicio
    assert vistos["products"][0] is f_cocina
    assert vistos["order_items"][1]["multi_source_sibling_tables"] == [
        "stores (stores.stores)",
        "products (kitchen.products)",
    ]


def test_tres_fatias_com_uma_em_falta_junta_as_duas_e_diz_qual_faltou():
    modelo = _Modelo(
        "```sql\nSELECT s.store_name, SUM(oi.unidades) AS unidades\n"
        "FROM order_items oi JOIN stores s ON s.store_id = oi.store_id\n"
        "GROUP BY 1 ORDER BY 2 DESC\n```"
    )
    falha = [{"table": "products", "reason": "connection refused"}]
    st = _merger(
        [FATIA_STORES, FATIA_ITEMS_3], modelo, failed=falha, pergunta=PERGUNTA_3
    )
    assert not st.get("error"), st.get("error")
    assert st["data"] == [
        {"store_name": "Centro", "unidades": 14},
        {"store_name": "Norte", "unidades": 11},
    ]
    prompt = _texto(modelo.chamadas[0])
    assert "NOT AVAILABLE" in prompt and "`products`" in prompt

    st = _formatar({**st, "question": PERGUNTA_3}, frase="Centro vendió 14 y Norte 11.")
    assert TECHNICAL_ES not in st["answer"]
    assert "«products»" in st["answer"]
    assert "«stores», «order_items»" in st["answer"]


def test_merger_que_inventa_a_tabela_em_falta_e_corrigido_na_segunda_tentativa():
    """Com products em falta, o modelo junta `products` na mesma: a SQL é
    recusada antes do DuckDB e o modelo recebe os nomes que existem."""
    modelo = _Modelo(
        SQL_MERGER_3,
        "```sql\nSELECT s.store_name, SUM(oi.unidades) AS unidades FROM order_items"
        " oi JOIN stores s USING (store_id) GROUP BY 1 ORDER BY 2 DESC\n```",
    )
    st = _merger(
        [FATIA_STORES, FATIA_ITEMS_3],
        modelo,
        failed=[{"table": "products", "reason": "x"}],
        pergunta=PERGUNTA_3,
    )
    assert not st.get("error") and not st.get("merge_failure")
    assert st["data"][0] == {"store_name": "Centro", "unidades": 14}
    assert "products" in modelo.chamadas[1][-1]["content"]


def test_cinco_fatias_tem_nomes_distintos_no_duckdb():
    from core.llm.merger import nomes_das_fatias

    nomes = nomes_das_fatias(
        [
            {"table": "orders"},
            {"table": "service.orders"},
            {"table": "Pedidos 2026"},
            {"table": "2026_ventas"},
            {"table": "stores"},
        ]
    )
    assert nomes == ["orders", "orders_2", "pedidos_2026", "t_2026_ventas", "stores"]
    assert len(set(nomes)) == 5


FATIA_ORDERS_POR_LOJA = {
    "table": "orders",
    "data": [{"store_id": 1, "pedidos": 10}, {"store_id": 2, "pedidos": 30}],
    "sql": "SELECT store_id, COUNT(*) AS pedidos ...",
    "metadata": {},
}
FATIA_ITENS_POR_PRATO = {
    "table": "order_items",
    "data": [{"product_id": 7, "unidades": 50}],
    "sql": "SELECT product_id, SUM(quantity) AS unidades ...",
    "metadata": {},
}


def test_fatias_sem_coluna_em_comum_nao_chegam_ao_modelo():
    """Medido com os modelos de produção («ventas por tienda y familia de
    producto», 4 tabelas em 3 ligações): orders vinha agregada por loja e
    order_items por prato — nenhum caminho de junção. O merger fazia CROSS
    JOIN (544.008 € inventados) ou UNION com NULLs («todas as lojas com
    0 €»). Agora decide-se sem o modelo e diz-se que não deu para combinar."""
    modelo = _Modelo(SQL_MERGER_3)
    st = _merger(
        [FATIA_STORES, FATIA_ORDERS_POR_LOJA, FATIA_ITENS_POR_PRATO, FATIA_PRODUCTS_3],
        modelo,
        pergunta=PERGUNTA_3,
    )
    assert modelo.chamadas == []
    assert not st.get("data")
    assert st["merge_failure"]["kind"] == "merge_failed"
    st = _formatar({**st, "question": PERGUNTA_3})
    assert TECHNICAL_ES not in st["answer"] and "combinar" in st["answer"]


def test_grupos_de_ligacao_reconhecem_id_contra_tabela_id():
    from core.llm.merger import grupos_sem_ligacao

    lojas_com_id = {"table": "stores", "data": [{"id": 1, "store_name": "Centro"}]}
    assert grupos_sem_ligacao(
        [FATIA_ORDERS_POR_LOJA, lojas_com_id], ["orders", "stores"]
    ) == [["orders", "stores"]]
    assert (
        len(
            grupos_sem_ligacao(
                [FATIA_ORDERS_POR_LOJA, FATIA_ITENS_POR_PRATO],
                ["orders", "order_items"],
            )
        )
        == 2
    )


def test_cross_join_entre_fatias_e_recusado_e_acaba_em_mensagem_honesta():
    """Há chave (store_id), mas o modelo junta sem ela: recusado antes do
    DuckDB, nova tentativa e, se insistir, a resposta diz que não combinou."""
    modelo = _Modelo(
        "```sql\nSELECT s.store_name, o.pedidos FROM stores s CROSS JOIN orders o\n```"
    )
    st = _merger([FATIA_ORDERS, FATIA_STORES], modelo)
    assert len(modelo.chamadas) == 2
    assert "without a key" in modelo.chamadas[1][-1]["content"]
    assert not st.get("data")
    assert st["merge_failure"]["kind"] == "merge_failed"
    st = _formatar({**st, "question": PERGUNTA_TIENDA})
    assert TECHNICAL_ES not in st["answer"] and "combinar" in st["answer"]


def test_cross_join_a_um_total_de_uma_linha_continua_permitido():
    from core.llm.merger import juncoes_sem_chave

    sql = (
        "WITH t AS (SELECT SUM(pedidos) AS total FROM orders) "
        "SELECT s.store_name, o.pedidos * 100.0 / t.total AS pct "
        "FROM orders o JOIN stores s USING (store_id) CROSS JOIN t"
    )
    assert juncoes_sem_chave(sql, ["orders", "stores"]) == []
    assert juncoes_sem_chave("SELECT * FROM orders, stores", ["orders", "stores"]) == [
        "stores"
    ]
