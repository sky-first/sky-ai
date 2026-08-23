"""Os numeros de uma resposta, e quando levam moeda.

O Lucas leu «The data shows a total revenue of 192,022.6.» — separadores
americanos, sem moeda, e uma casa decimal. Em Portugal esse numero le-se mil
vezes menor do que e.
"""

from core.llm.numeros import e_dinheiro, moeda_provavel, regras_de_numeros


class TestQueColunasSaoDinheiro:
    def test_as_obvias(self):
        assert e_dinheiro("total_revenue")
        assert e_dinheiro("amount")
        assert e_dinheiro("monthly_amount")

    def test_monthly_amount_e_dinheiro(self):
        """**A coluna de dinheiro das subscricoes.**

        A primeira versao procurava «month» DENTRO do nome para excluir
        colunas de data — e «monthly» contem «month», portanto a coluna de
        dinheiro deixava de ser dinheiro. Apanhei-o a experimentar a funcao
        antes de a ligar; e o mesmo erro que o resto do ficheiro trata,
        comparar texto onde se devia comparar significado.
        """
        assert e_dinheiro("monthly_amount")

    def test_uma_contagem_nao_e_dinheiro(self):
        # Escrever «17,00 EUR» num numero de faturas e tao errado quanto
        # escrever «17» num valor em euros.
        assert not e_dinheiro("invoice_count")
        assert not e_dinheiro("revenue_count")

    def test_um_identificador_nao_e_dinheiro(self):
        assert not e_dinheiro("price_id")
        assert not e_dinheiro("subscription_id")

    def test_datas_e_percentagens_ficam_de_fora(self):
        assert not e_dinheiro("issued_at")
        assert not e_dinheiro("month")
        assert not e_dinheiro("margem_pct")


class TestAMoeda:
    def test_sem_coluna_de_dinheiro_nao_ha_moeda(self):
        # E o que impede um simbolo de euro colado a um numero de clientes.
        assert moeda_provavel(["invoice_count", "month"], "pt") is None

    def test_portugues_traz_euros(self):
        assert moeda_provavel(["total_revenue"], "pt") == "EUR"

    def test_a_definicao_da_pessoa_ganha_a_heuristica(self):
        # Uma definicao explicita vale mais do que qualquer adivinhacao nossa.
        assert moeda_provavel(["total_revenue"], "pt", "BRL") == "BRL"


class TestAsRegrasQueVaoParaOPrompt:
    def test_portugues_pede_ponto_nos_milhares(self):
        r = regras_de_numeros("pt", ["total_revenue"])
        assert "Thousands separator: a dot (.)" in r
        assert "Decimal separator: a comma (,)" in r
        assert "192.022,60" in r

    def test_ingles_pede_o_contrario(self):
        r = regras_de_numeros("en", ["total_revenue"])
        assert "Thousands separator: a comma (,)" in r
        assert "192,022.60" in r

    def test_o_simbolo_vem_depois_em_portugues(self):
        # `192.022,60 €`, e nao `€192.022,60`. E a convencao de quem le.
        assert "192.022,60 €" in regras_de_numeros("pt", ["amount"])

    def test_proibe_a_casa_decimal_solta(self):
        """`265.221,0` — nem inteiro nem dinheiro.

        Uma casa decimal e sempre lixo de virgula flutuante que passou pelo
        modelo; dinheiro tem duas e contagens nao tem nenhuma.
        """
        r = regras_de_numeros("pt", ["total_revenue"])
        assert "never 17,0" in r
        assert "EXACTLY two decimals" in r

    def test_sem_dinheiro_proibe_o_simbolo(self):
        r = regras_de_numeros("pt", ["invoice_count"])
        assert "Do NOT attach a" in r
        assert "€" not in r

    def test_nao_manda_converter_moeda(self):
        # Converter com uma taxa que nao temos e pior do que nao dizer nada.
        assert "Do NOT convert between currencies" in regras_de_numeros(
            "pt", ["amount"]
        )
