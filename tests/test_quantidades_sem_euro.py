"""Produção, 13/10/2026 — sandbox «Restauración», modelos de produção.

«¿Cuáles son los 5 platos más vendidos?» → «… 2.508,00 € unidades».

O SQL era ``SUM(oi.quantity) AS total_quantity``: uma QUANTIDADE. Mas o nome
tem «total», que estava na lista de palavras de dinheiro, e «quantity» não
estava na das excepções (só «quantidade», «qty» e «cantidad»). A coluna
passava por dinheiro — o prompt dizia ao modelo que a resposta tinha euros e
a correcção determinística reescrevia 2508 como «2.508,00 €».

A regra do Lucas: dinheiro em euro, «1.234,56 €»; contagens, quantidades,
unidades, pedidos, percentagens e segundos NUNCA levam «€», e contagens
inteiras não levam casas decimais («2.508 unidades», «331 pedidos»).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.llm.numeros import (
    CorrecaoEmFluxo,
    colunas_de_dinheiro,
    corrigir_resposta,
    e_dinheiro,
    regras_de_numeros,
    unidades_das_metricas,
)

# O resultado real da pergunta (forma do seed de restauração).
_PLATOS = [
    {"product_name": "Hamburguesa clásica", "total_quantity": 2508},
    {"product_name": "Patatas fritas", "total_quantity": 2311},
    {"product_name": "Refresco", "total_quantity": 1987},
    {"product_name": "Ensalada César", "total_quantity": 1204},
    {"product_name": "Helado", "total_quantity": 998},
]
_SQL_PLATOS = (
    "SELECT p.name AS product_name, SUM(oi.quantity) AS total_quantity "
    "FROM service.order_items oi JOIN catalog.products p ON p.id = oi.product_id "
    "GROUP BY p.name ORDER BY total_quantity DESC LIMIT 5"
)


# ── 1. O caso de produção ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "texto",
    [
        # O que saiu em produção (o modelo seguiu o prompt, que dizia euros).
        "El plato más vendido es la Hamburguesa clásica, con 2.508,00 € unidades.",
        # O que o modelo escreve quando o prompt não fala de euros.
        "El plato más vendido es la Hamburguesa clásica, con 2508 unidades.",
        "El plato más vendido es la Hamburguesa clásica, con 2.508 € unidades.",
    ],
)
def test_platos_mas_vendidos_sem_euro(texto):
    r = corrigir_resposta(texto, "es", _PLATOS, sql=_SQL_PLATOS)
    assert r == "El plato más vendido es la Hamburguesa clásica, con 2.508 unidades."


def test_platos_mas_vendidos_em_portugues_e_ingles():
    pt = corrigir_resposta(
        "O prato mais vendido é a Hamburguesa clásica, com 2.508,00 € unidades.",
        "pt",
        _PLATOS,
        sql=_SQL_PLATOS,
    )
    assert pt == "O prato mais vendido é a Hamburguesa clásica, com 2.508 unidades."
    en = corrigir_resposta(
        "The best seller is the burger, with €2,508.00 units.",
        "en",
        _PLATOS,
        sql=_SQL_PLATOS,
    )
    assert en == "The best seller is the burger, with 2,508 units."


def test_o_prompt_nao_anuncia_euros_para_quantidades():
    for lingua in ("pt", "es", "en"):
        r = regras_de_numeros(lingua, ["product_name", "total_quantity"])
        assert "No monetary column was detected" in r
        assert "MONEY:" not in r


def test_streaming_tambem_sem_euro():
    texto = "Los más vendidos: Hamburguesa clásica (2.508,00 € unidades) y Helado (998,00 € unidades)."
    c = CorrecaoEmFluxo("es", _PLATOS, sql=_SQL_PLATOS)
    saida = ""
    for i in range(0, len(texto), 3):
        saida += c.receber(texto[i : i + 3])
    saida += c.terminar()
    assert "€" not in saida
    assert "2.508 unidades" in saida and "998 unidades" in saida


# ── 2. A decisão por coluna ───────────────────────────────────────────


@pytest.mark.parametrize(
    "coluna",
    [
        "total_quantity",
        "quantity",
        "quantities",
        "qty_sold",
        "units_sold",
        "unidades_vendidas",
        "cantidad_total",
        "num_orders",
        "n_pedidos",
        "orders_count",
        "total_pedidos",
        "total_platos",
        "total_vendido",
        "tickets",
        "pct_drive",
        "porcentaje",
        "avg_service_seconds",
        "tiempo_segundos",
        "minutos_espera",
    ],
)
def test_quantidades_nao_sao_dinheiro(coluna):
    assert not e_dinheiro(coluna)


@pytest.mark.parametrize(
    "coluna",
    [
        "total",
        "total_eur",
        "amount",
        "revenue",
        "price",
        "unit_price",
        "importe",
        "ventas",
        "facturacion",
        "facturación_total",
        "ticket_medio",
        "coste",
        "margin",
        "valor_total",
        "avg_value",
    ],
)
def test_dinheiro_continua_dinheiro(coluna):
    assert e_dinheiro(coluna)


def test_a_linhagem_do_sql_decide_quando_o_nome_nao_chega():
    sql = (
        "SELECT COUNT(*) AS total, SUM(oi.quantity) AS vendidos, "
        "SUM(oi.quantity * oi.unit_price) AS facturado_bruto, "
        "SUM(oi.quantity * oi.unit_price) AS bruto "
        "FROM service.order_items oi"
    )
    d = colunas_de_dinheiro(["total", "vendidos", "facturado_bruto", "bruto"], sql)
    # COUNT(*) AS total é uma contagem, apesar do nome.
    assert "total" not in d
    assert "vendidos" not in d
    assert "facturado_bruto" in d
    # «bruto» não diz nada; vem de quantity * unit_price → dinheiro.
    assert "bruto" in d


def test_razao_entre_dinheiros_nao_e_dinheiro():
    sql = "SELECT SUM(o.total) / SUM(t.total) * 100 AS cuota FROM o, t"
    assert "cuota" not in colunas_de_dinheiro(["cuota"], sql)


def test_contagem_com_nome_de_dinheiro_nao_leva_euro():
    linhas = [{"total": 331}]
    sql = "SELECT COUNT(*) AS total FROM service.orders"
    r = corrigir_resposta("Hay 331,00 € pedidos.", "es", linhas, sql=sql)
    assert r == "Hay 331 pedidos."


# ── 3. Os outros casos da regra ───────────────────────────────────────


def test_receita_continua_com_euro():
    linhas = [{"store": "Madrid", "revenue": Decimal("192022.6")}]
    assert (
        corrigir_resposta("Madrid facturó 192022.6.", "es", linhas)
        == "Madrid facturó 192.022,60 €."
    )
    assert (
        corrigir_resposta("Madrid faturou 192022.6.", "pt", linhas)
        == "Madrid faturou 192.022,60 €."
    )
    assert (
        corrigir_resposta("Madrid billed 192022.6.", "en", linhas)
        == "Madrid billed €192,022.60."
    )


def test_percentagem_sem_euro():
    linhas = [{"channel": "drive", "pct_pedidos": 12.5}]
    r = corrigir_resposta("El drive pesa un 12,5 € de los pedidos.", "es", linhas)
    assert "€" not in r
    assert "12,5 %" in r or "12,50 %" in r
    # E a percentagem já escrita fica como está.
    assert (
        corrigir_resposta("El drive pesa un 12,5 % de los pedidos.", "es", linhas)
        == "El drive pesa un 12,5 % de los pedidos."
    )


def test_segundos_sem_euro():
    linhas = [
        {"channel": "drive", "avg_service_sec": 180.0},
        {"channel": "sala", "avg_service_sec": 143.19},
    ]
    r = corrigir_resposta(
        "La mayor diferencia es de 36,81 € en el canal drive.", "es", linhas
    )
    assert r == "La mayor diferencia es de 36,81 s en el canal drive."


def test_contagem_inteira_sem_casas_decimais():
    linhas = [{"channel": "drive", "orders_count": 331}]
    assert (
        corrigir_resposta("El drive tuvo 331,00 € pedidos.", "es", linhas)
        == "El drive tuvo 331 pedidos."
    )
    assert (
        corrigir_resposta("O drive teve 331,00 pedidos.", "pt", linhas)
        == "O drive teve 331 pedidos."
    )


# ── 4. A unidade da métrica do espaço manda ───────────────────────────

_INSTRUCOES = (
    "# Trusted metrics (prefer these over ad-hoc derivations)\n"
    "- Tiempo de servicio [ORG-CERTIFIED] — media por pedido (unit: s)\n"
    "- Valor medio [SPACE] — media del pedido (unit: pedidos)\n"
    "- Volumen [SPACE] — facturación por tienda (unit: €)\n"
)


def test_unidades_das_metricas_lidas_das_instrucoes():
    m = unidades_das_metricas(_INSTRUCOES)
    assert m["tiempo_de_servicio"] == "s"
    assert m["volumen"] == "EUR"


def test_metrica_com_unidade_nao_monetaria_ganha_ao_nome():
    # «valor» parecia dinheiro; a métrica diz que não é.
    linhas = [{"valor_medio": 14}]
    r = corrigir_resposta(
        "El valor medio es 14,00 €.", "es", linhas, instrucoes=_INSTRUCOES
    )
    assert "€" not in r and "14" in r


def test_metrica_em_euros_e_dinheiro():
    linhas = [{"volumen": 1500.5}]
    r = corrigir_resposta(
        "El volumen fue de 1500.5.", "es", linhas, instrucoes=_INSTRUCOES
    )
    assert r == "El volumen fue de 1.500,50 €."


def test_metrica_em_segundos_leva_s():
    linhas = [{"tiempo_de_servicio": 36.81}]
    r = corrigir_resposta(
        "El tiempo de servicio fue de 36,81.", "es", linhas, instrucoes=_INSTRUCOES
    )
    assert r == "El tiempo de servicio fue de 36,81 s."


# ── 5. Os dois exemplos vistos em produção a 13/10 (sandbox) ──────────


def test_producao_clasica_24898_unidades_sem_euro():
    linhas = [
        {"product_name": "Clásica", "total_quantity": 24898},
        {"product_name": "Doble", "total_quantity": 19012},
    ]
    sql = (
        "SELECT p.name AS product_name, SUM(oi.quantity) AS total_quantity "
        "FROM service.order_items oi JOIN catalog.products p "
        "ON p.id = oi.product_id GROUP BY p.name ORDER BY 2 DESC LIMIT 5"
    )
    r = corrigir_resposta(
        "Los 5 platos más vendidos son: Clásica, 24.898,00 € unidades; "
        "Doble, 19.012,00 € unidades.",
        "es",
        linhas,
        sql=sql,
    )
    assert r == (
        "Los 5 platos más vendidos son: Clásica, 24.898 unidades; "
        "Doble, 19.012 unidades."
    )


@pytest.mark.parametrize(
    "lingua,texto,esperado",
    [
        (
            "es",
            "Tienda 01 (Madrid) con **4526** pedidos.",
            "Tienda 01 (Madrid) con **4.526** pedidos.",
        ),
        (
            "pt",
            "Loja 01 (Madrid) com **4526** pedidos.",
            "Loja 01 (Madrid) com **4.526** pedidos.",
        ),
        (
            "en",
            "Store 01 (Madrid) with **4526** orders.",
            "Store 01 (Madrid) with **4,526** orders.",
        ),
    ],
)
def test_producao_4526_pedidos_leva_separador(lingua, texto, esperado):
    linhas = [
        {"store_name": "Tienda 01 (Madrid)", "num_pedidos": 4526},
        {"store_name": "Tienda 02 (Barcelona)", "num_pedidos": 3980},
    ]
    sql = (
        "SELECT s.name AS store_name, COUNT(*) AS num_pedidos FROM service.orders o "
        "JOIN restaurant.stores s ON s.id = o.store_id GROUP BY s.name"
    )
    assert corrigir_resposta(texto, lingua, linhas, sql=sql) == esperado
