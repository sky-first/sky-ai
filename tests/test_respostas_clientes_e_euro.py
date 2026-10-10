"""Produção, 10/10/2026 — projecto «Restauración — Operación de tiendas».

1. «¿Quantos clientes eu tenho?» → «No encontré datos sobre clientes tenho.»
   e «¿Cuántos clientes tengo?» → «No encontré datos sobre cuántos clientes
   tengo.» A base de restauração NÃO tem clientes (pedidos anónimos: nem
   tabela de clientes nem coluna customer_id em service.orders). A
   verificação `conceito_ausente` sabia-o — mas o caminho em streaming (app
   e voz) deitava o MISSING fora e respondia NO_DATA_FOUND com a pergunta
   colada na frase.
2. «¿Cuánto he facturado?» → «El usuario ha facturado un total de
   6 153 185,72.» Terceira pessoa, espaços nos milhares e sem euro.
"""

from __future__ import annotations

import inspect
from decimal import Decimal
from types import SimpleNamespace

import pytest

from core.agents.generic_sql_agent import TableSchema
from core.llm.conceito_em_falta import conceito_ausente, traduzir_conceito
from core.llm.formatter import _extract_topic, mensagem_sem_dados
from core.llm.numeros import (
    CorrecaoEmFluxo,
    corrigir_resposta,
    e_dinheiro,
    formatar_valor,
    moeda_provavel,
)

# O esquema real do seed (sky-infra/gitops/manifests/demo-seed/seed_restaurant.sql).
_RESTAURACAO = [
    TableSchema(
        logical_name="orders",
        physical_name="service.orders",
        description="",
        columns=[
            {"name": n}
            for n in (
                "id",
                "store_id",
                "placed_at",
                "channel",
                "day_part",
                "service_sec",
                "total",
            )
        ],
    ),
    TableSchema(
        logical_name="order_items",
        physical_name="service.order_items",
        description="",
        columns=[
            {"name": n}
            for n in ("id", "order_id", "product_id", "quantity", "unit_price")
        ],
    ),
    TableSchema(
        logical_name="stores",
        physical_name="restaurant.stores",
        description="",
        columns=[
            {"name": n} for n in ("id", "name", "city", "format", "seats", "has_drive")
        ],
    ),
    TableSchema(
        logical_name="staff_shifts",
        physical_name="restaurant.staff_shifts",
        description="",
        columns=[
            {"name": n}
            for n in (
                "id",
                "store_id",
                "worked_on",
                "day_part",
                "headcount",
                "hours",
                "cost_per_hour",
            )
        ],
    ),
    TableSchema(
        logical_name="products",
        physical_name="kitchen.products",
        description="",
        columns=[
            {"name": n}
            for n in (
                "id",
                "sku",
                "name",
                "family",
                "unit_cost",
                "menu_price",
                "hold_minutes",
            )
        ],
    ),
    TableSchema(
        logical_name="waste",
        physical_name="kitchen.waste",
        description="",
        columns=[
            {"name": n}
            for n in (
                "id",
                "store_id",
                "product_id",
                "wasted_on",
                "day_part",
                "units",
                "reason",
            )
        ],
    ),
]


# ── 1. Clientes: o conceito não existe, e a frase diz isso limpo ──────


@pytest.mark.parametrize(
    "pergunta,lingua",
    [("¿Quantos clientes eu tenho?", "pt"), ("¿Cuántos clientes tengo?", "es")],
)
def test_restauracao_nao_tem_clientes(pergunta, lingua):
    razao = conceito_ausente(pergunta, _RESTAURACAO, lingua)
    assert razao and razao.startswith("MISSING")
    assert "NEAREST" in razao  # oferece os pedidos


@pytest.mark.parametrize(
    "pergunta",
    [
        "¿Quantos clientes eu tenho?",
        "¿Cuántos clientes tengo?",
        "Quantos clientes temos?",
        "how many customers do I have?",
    ],
)
def test_o_assunto_e_um_substantivo_limpo(pergunta):
    assert _extract_topic(pergunta) == (
        "customers" if "customers" in pergunta else "clientes"
    )


@pytest.mark.parametrize(
    "pergunta,lingua_detectada,lingua_resposta,esperado",
    [
        (
            "¿Cuántos clientes tengo?",
            "es",
            "es",
            "Los datos a los que tengo acceso no registran datos de clientes. Lo más "
            "parecido que le puedo dar es el número de pedidos. ¿Quiere que lo calcule?",
        ),
        # Pergunta em português, preferência castelhana: responde em
        # castelhano — mas TUDO em castelhano.
        (
            "¿Quantos clientes eu tenho?",
            "pt",
            "es",
            "Los datos a los que tengo acceso no registran datos de clientes. Lo más "
            "parecido que le puedo dar es el número de pedidos. ¿Quiere que lo calcule?",
        ),
        (
            "¿Quantos clientes eu tenho?",
            "pt",
            "pt",
            "Os dados a que tenho acesso não registam dados de clientes. O mais "
            "próximo que lhe posso dar é o número de encomendas — quer que o calcule?",
        ),
    ],
)
def test_a_mensagem_de_conceito_em_falta(
    pergunta, lingua_detectada, lingua_resposta, esperado
):
    razao = conceito_ausente(pergunta, _RESTAURACAO, lingua_detectada)
    msg = mensagem_sem_dados(pergunta, razao, lingua_resposta)
    assert msg == esperado
    assert "tenho" not in msg.replace("tengo acceso", "").replace("tenho acesso", "")
    assert "cuántos" not in msg.lower()


def test_sem_motivo_o_nao_encontrei_leva_so_o_assunto():
    assert mensagem_sem_dados("¿Cuántos clientes tengo?", None, "es") == (
        "No encontré datos sobre clientes. Pruebe a reformular la pregunta."
    )
    assert mensagem_sem_dados("¿Quantos clientes eu tenho?", None, "pt") == (
        "Não encontrei dados sobre clientes. Experimente perguntar de outra maneira."
    )


def test_sem_assunto_usa_a_generica():
    assert mensagem_sem_dados("¿Cuántos hay?", None, "es").startswith(
        "No encontré datos para responder"
    )


def test_frases_do_modelo_ficam_como_vieram():
    assert traduzir_conceito("datos de márgenes", None, "pt") == (
        "datos de márgenes",
        None,
    )


def test_o_streaming_ja_nao_deita_fora_o_missing():
    """O caminho da app e da voz usava NO_DATA_FOUND para qualquer
    impossible_reason — incluindo o MISSING de `conceito_ausente`."""
    from api.routes import connection_query

    fonte = inspect.getsource(connection_query)
    inicio = fonte.index("Executar agente até o specialist")
    fim = fonte.index("Persist conversation turn for future follow-ups", inicio)
    trecho = fonte[inicio:fim]
    assert 'get_message("NO_DATA_FOUND"' not in trecho
    assert (
        'mensagem_sem_dados(\n                    body.question, final_state.get("impossible_reason")'
        in trecho
    )


# ── 2. Dinheiro: «€», separadores europeus, segunda pessoa ───────────

_FACTURADO = [{"total_facturado": Decimal("6153185.72")}]


@pytest.mark.parametrize(
    "lingua,esperado",
    [
        ("es", "Ha facturado un total de 6.153.185,72 €."),
        ("pt", "Ha facturado un total de 6.153.185,72 €."),
        ("en", "Ha facturado un total de €6,153,185.72."),
    ],
)
def test_o_caso_de_producao(lingua, esperado):
    texto = "El usuario ha facturado un total de 6 153 185,72."
    assert corrigir_resposta(texto, lingua, _FACTURADO) == esperado


@pytest.mark.parametrize(
    "texto",
    [
        "Has facturado 6 153 185,72.",
        "Has facturado 6.153.185,72.",
        "Has facturado 6,153,185.72.",
        "Has facturado 6153185.72.",
        "Has facturado 6153185,72 €.",
        "Has facturado €6,153,185.72.",
        "Has facturado 6.153.185,72 euros.",
        "Has facturado 6.153.185,72 EUR.",
    ],
)
def test_qualquer_escrita_do_modelo_sai_igual(texto):
    assert corrigir_resposta(texto, "es", _FACTURADO) == "Has facturado 6.153.185,72 €."


def test_em_ingles_o_simbolo_vem_antes():
    assert (
        corrigir_resposta("You have invoiced 6 153 185,72.", "en", _FACTURADO)
        == "You have invoiced €6,153,185.72."
    )


@pytest.mark.parametrize(
    "texto,lingua,esperado",
    [
        ("O utilizador faturou 6 153 185,72.", "pt", "Faturou 6.153.185,72 €."),
        ("The user has invoiced 6153185.72.", "en", "You have invoiced €6,153,185.72."),
        ("The user's revenue is 6153185.72.", "en", "Your revenue is €6,153,185.72."),
        (
            "Total: 6153185.72. El usuario tiene 12 tiendas.",
            "es",
            "Total: 6.153.185,72 €. Tiene 12 tiendas.",
        ),
    ],
)
def test_fala_com_quem_pergunta(texto, lingua, esperado):
    assert corrigir_resposta(texto, lingua, _FACTURADO) == esperado


def test_o_que_nao_e_dinheiro_nao_leva_euro():
    linhas = [{"pedidos": 158340, "tiendas": 12}]
    r = corrigir_resposta("Hay 158340 pedidos en 12 tiendas.", "es", linhas)
    assert r == "Hay 158.340 pedidos en 12 tiendas."
    assert corrigir_resposta("There are 158340 orders.", "en", linhas) == (
        "There are 158,340 orders."
    )


def test_datas_anos_percentagens_e_ids_ficam_como_estao():
    linhas = [{"order_id": 158340, "total": Decimal("15.50")}]
    texto = "El pedido 158340 del 2026-08-01 a las 12:30 en 2026 subió un 12,5 %."
    assert corrigir_resposta(texto, "es", linhas) == texto


def test_a_soma_e_a_media_tambem_sao_dinheiro():
    linhas = [{"store": "A", "ventas": 1000.5}, {"store": "B", "ventas": 2000.25}]
    r = corrigir_resposta(
        "Entre las dos suman 3000.75, con una media de 1500.375.", "es", linhas
    )
    assert "3.000,75 €" in r
    assert "1.500,38 €" in r


def test_com_marcador_de_moeda_e_dinheiro_mesmo_fora_do_resultado():
    assert (
        corrigir_resposta("Ticket medio de 15.5 €.", "es", [])
        == "Ticket medio de 15,50 €."
    )


def test_a_moeda_definida_pela_pessoa_ganha():
    assert corrigir_resposta("Total 1234.5", "pt", [{"total": 1234.5}], "BRL") == (
        "Total 1.234,50 R$"
    )


@pytest.mark.parametrize(
    "coluna",
    [
        "total_facturado",
        "facturacion",
        "importe",
        "ingresos",
        "ventas",
        "precio",
        "coste",
        "margen",
        "revenue",
        "amount",
        "total",
    ],
)
def test_colunas_de_dinheiro_em_castelhano(coluna):
    assert e_dinheiro(coluna)


@pytest.mark.parametrize(
    "coluna", ["total_pedidos", "num_clientes", "orders", "service_sec", "store_id"]
)
def test_contagens_nao_sao_dinheiro(coluna):
    assert not e_dinheiro(coluna)


def test_em_ingles_tambem_sao_euros():
    """Regra do Lucas: estamos na Europa."""
    assert moeda_provavel(["total_revenue"], "en") == "EUR"


@pytest.mark.parametrize(
    "valor,lingua,dinheiro,esperado",
    [
        (6153185.72, "es", True, "6.153.185,72 €"),
        (6153185.72, "pt", True, "6.153.185,72 €"),
        (6153185.72, "en", True, "€6,153,185.72"),
        (-1234.5, "es", True, "-1.234,50 €"),
        (158340, "es", False, "158.340"),
        (2026, "es", False, "2026"),
        (0.75, "pt", False, "0,75"),
    ],
)
def test_formatar_valor(valor, lingua, dinheiro, esperado):
    assert formatar_valor(valor, lingua, dinheiro) == esperado


# ── 3. Streaming (app e voz): pedaço a pedaço sai o mesmo ────────────


@pytest.mark.parametrize("tamanho", [1, 2, 3, 5, 7, 1000])
def test_streaming_da_o_mesmo_que_o_texto_inteiro(tamanho):
    texto = (
        "El usuario ha facturado un total de 6 153 185,72 euros. La tienda de "
        "Madrid vendió 1 234 567,10 y hay 158340 pedidos. El 2026-08-01 fue el mejor día."
    )
    linhas = [
        {
            "total_facturado": Decimal("6153185.72"),
            "ventas_madrid": 1234567.10,
            "pedidos": 158340,
        }
    ]
    c = CorrecaoEmFluxo("es", linhas)
    saida = ""
    for i in range(0, len(texto), tamanho):
        saida += c.receber(texto[i : i + tamanho])
    saida += c.terminar()
    assert saida == corrigir_resposta(texto, "es", linhas)
    assert saida.startswith("Ha facturado un total de 6.153.185,72 €.")
    assert "1.234.567,10 €" in saida and "158.340 pedidos" in saida
    assert c.texto == saida


def test_o_formatador_devolve_o_texto_corrigido(monkeypatch):
    """A resposta da API (`answer`) — e a voz — leva o texto corrigido."""
    from core.llm import formatter

    monkeypatch.setattr(formatter, "build_context_bundle", lambda *a, **k: None)
    monkeypatch.setattr(
        formatter,
        "build_formatter_prompt",
        lambda **k: ({"content": ""}, {"content": ""}),
    )
    monkeypatch.setattr(
        formatter,
        "_invoke_llm",
        lambda *a, **k: "El usuario ha facturado un total de 6 153 185,72.",
    )
    monkeypatch.setattr(formatter.settings, "use_local_models", False, raising=False)
    state = {
        "question": "¿Cuánto he facturado?",
        "data": _FACTURADO,
        "detected_language": "es",
    }
    out = formatter.run_formatter(
        state, SimpleNamespace(id="a", security_config=None), llm=None
    )
    assert out["answer"] == "Ha facturado un total de 6.153.185,72 €."
