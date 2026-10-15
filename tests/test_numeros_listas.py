"""Marcadores de lista não são números da resposta (15/10/2026).

Alimentación, «¿Cuáles son los 10 productos más vendidos este año?», uma
das duas respostas saiu:

    1 unidades. Viñedos del Duero Rueda Verdejo — 15.349 unidades
    2 unidades. Tierra de Barros Cayetana — 10.281 unidades

Dois defeitos juntos:

1. A rede determinística (``corrigir_numeros``) tratava o «1» de «1.» como
   um número da resposta. Se casava com um valor de uma coluna com unidade,
   levava a palavra («1 unidades.»).
2. O valor casava porque o SQL tinha ``RANK() OVER (ORDER BY
   SUM(oi.quantity) DESC) AS posicion`` e a linhagem fazia a posição herdar
   a unidade da coluna do ORDER BY da janela — 1, 2, 3… eram «unidades».
"""

import pytest

from core.llm.numeros import CorrecaoEmFluxo, analisar_colunas, corrigir_resposta

SQL_COM_POSICAO = (
    "SELECT p.name AS producto, SUM(oi.quantity) AS unidades, "
    "RANK() OVER (ORDER BY SUM(oi.quantity) DESC) AS posicion "
    "FROM sales.order_items oi JOIN sales.products p ON p.id = oi.product_id "
    "GROUP BY p.name ORDER BY unidades DESC LIMIT 3"
)
LINHAS = [
    {"producto": "Viñedos del Duero Rueda Verdejo", "unidades": 15349, "posicion": 1},
    {"producto": "Tierra de Barros Cayetana", "unidades": 10281, "posicion": 2},
    {"producto": "AOVE Guadiana Picual 500 ml", "unidades": 8951, "posicion": 3},
]

LISTAS = {
    "es": (
        "Los 3 productos más vendidos este año son:\n\n"
        "1. Viñedos del Duero Rueda Verdejo — 15349 unidades\n"
        "2. Tierra de Barros Cayetana — 10281 unidades\n"
        "3. AOVE Guadiana Picual 500 ml — 8951 unidades\n\n"
        "El primero vende un 49 % más que el segundo."
    ),
    "pt": (
        "Os 3 produtos mais vendidos este ano são:\n\n"
        "1. Viñedos del Duero Rueda Verdejo — 15349 unidades\n"
        "2. Tierra de Barros Cayetana — 10281 unidades\n"
        "3. AOVE Guadiana Picual 500 ml — 8951 unidades"
    ),
    "en": (
        "The 3 best-selling products this year are:\n\n"
        "1. Viñedos del Duero Rueda Verdejo — 15349 units\n"
        "2. Tierra de Barros Cayetana — 10281 units\n"
        "3. AOVE Guadiana Picual 500 ml — 8951 units"
    ),
}
MILHARES = {"es": "15.349", "pt": "15.349", "en": "15,349"}


def _sem_unidade_no_marcador(texto: str) -> None:
    for n in ("1", "2", "3"):
        assert f"\n{n}. Viñedos" in texto or f"\n{n}. " in texto, texto
        assert f"{n} unidades." not in texto and f"{n} units." not in texto, texto


class TestPosicaoNaoTemUnidade:
    def test_rank_over_sum_quantity_nao_herda_unidades(self):
        _, nao_dinheiro, unidades = analisar_colunas(
            ["producto", "unidades", "posicion"], SQL_COM_POSICAO
        )
        assert unidades.get("unidades") == "un"
        assert "posicion" not in unidades

    def test_row_number_over_sum_amount_nao_e_dinheiro(self):
        sql = (
            "SELECT c.name AS cliente, SUM(o.amount) AS facturacion, "
            "ROW_NUMBER() OVER (ORDER BY SUM(o.amount) DESC) AS puesto "
            "FROM sales.orders o JOIN sales.customers c ON c.id = o.customer_id "
            "GROUP BY c.name"
        )
        dinheiro, nao_dinheiro, unidades = analisar_colunas(
            ["cliente", "facturacion", "puesto"], sql
        )
        assert "facturacion" in dinheiro
        assert "puesto" not in dinheiro and "puesto" in nao_dinheiro
        assert "puesto" not in unidades

    def test_soma_em_janela_continua_a_herdar(self):
        # Um acumulado continua a ser unidades: só as POSIÇÕES perdem a unidade.
        sql = "SELECT d, SUM(quantity) OVER (ORDER BY d) AS acumulado FROM t"
        _, _, unidades = analisar_colunas(["d", "acumulado"], sql)
        assert unidades.get("acumulado") == "un"


@pytest.mark.parametrize("lingua", ["es", "pt", "en"])
class TestListaNumerada:
    def test_marcadores_ficam_e_valores_levam_separador(self, lingua):
        r = corrigir_resposta(LISTAS[lingua], lingua, LINHAS, sql=SQL_COM_POSICAO)
        _sem_unidade_no_marcador(r)
        assert MILHARES[lingua] in r

    def test_mesmo_que_a_coluna_tenha_unidade_nos_valores_1_2_3(self, lingua):
        # Sem SQL e com a posição numa coluna que SE chama «unidades»: o pior
        # caso — 1, 2 e 3 são mesmo valores de uma coluna com unidade.
        linhas = [
            {"producto": "A", "unidades": 1},
            {"producto": "B", "unidades": 2},
            {"producto": "C", "unidades": 3},
        ]
        palavra = "units" if lingua == "en" else "unidades"
        texto = (
            "Ranking:\n\n"
            f"1. A — 1 {palavra}\n"
            f"2) B — 2 {palavra}\n"
            f"  3. C — 3 {palavra}\n"
        )
        r = corrigir_resposta(texto, lingua, linhas)
        assert "\n1. A — 1 " in r and "\n2) B — 2 " in r and "\n  3. C — 3 " in r, r
        assert f"1 {palavra}. A" not in r and f"2 {palavra}) B" not in r, r

    def test_negrito_markdown(self, lingua):
        texto = "**1.** Viñedos del Duero Rueda Verdejo: 15349\n**2.** Tierra de Barros Cayetana: 10281"
        r = corrigir_resposta(texto, lingua, LINHAS, sql=SQL_COM_POSICAO)
        assert r.startswith("**1.** Viñedos"), r
        assert "\n**2.** Tierra" in r, r

    def test_marcador_logo_no_inicio_do_texto(self, lingua):
        texto = LISTAS[lingua].split("\n\n", 1)[1]
        r = corrigir_resposta(texto, lingua, LINHAS, sql=SQL_COM_POSICAO)
        assert r.startswith("1. Viñedos"), r

    def test_em_fluxo_letra_a_letra(self, lingua):
        texto = LISTAS[lingua]
        fluxo = CorrecaoEmFluxo(lingua, LINHAS, sql=SQL_COM_POSICAO)
        saida = "".join(fluxo.receber(c) for c in texto) + fluxo.terminar()
        _sem_unidade_no_marcador(saida)
        assert saida == corrigir_resposta(texto, lingua, LINHAS, sql=SQL_COM_POSICAO)

    def test_em_fluxo_aos_pedacos(self, lingua):
        texto = LISTAS[lingua]
        fluxo = CorrecaoEmFluxo(lingua, LINHAS, sql=SQL_COM_POSICAO)
        pedacos = [texto[i : i + 7] for i in range(0, len(texto), 7)]
        saida = "".join(fluxo.receber(p) for p in pedacos) + fluxo.terminar()
        _sem_unidade_no_marcador(saida)


class TestNaoDeixaDeCorrigirOResto:
    def test_valor_a_meio_da_linha_continua_a_levar_unidade(self):
        linhas = [{"producto": "A", "unidades": 3}, {"producto": "B", "unidades": 7}]
        r = corrigir_resposta("A vendió 3, B vendió 7.", "es", linhas)
        assert "3 unidades" in r and "7 unidades." in r, r

    def test_valor_no_inicio_da_linha_sem_ponto_de_lista(self):
        linhas = [{"producto": "A", "unidades": 15349}]
        r = corrigir_resposta("Total:\n15349 unidades vendidas.", "es", linhas)
        assert "15.349 unidades" in r, r

    def test_marcador_de_tres_algarismos_no_maximo(self):
        # «2026.» no início da linha não é um marcador de lista: é um ano ou
        # um valor — fica a cargo das regras de sempre.
        linhas = [{"producto": "A", "unidades": 2026}]
        r = corrigir_resposta("Vendas:\n2026. Fim.", "es", linhas)
        assert "2.026 unidades." in r, r
