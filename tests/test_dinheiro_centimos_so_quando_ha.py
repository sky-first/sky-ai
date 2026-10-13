"""Dinheiro: cêntimos só quando há (decisão do Lucas, 13/10/2026).

Valores redondos sem «,00» («412.300 €»); duas casas só quando há cêntimos
(«1.234,50 €», nunca «1.234,5 €»). É a regra da web
(`sky-frontend/src/lib/numeros.ts`, `formatarNumero`) e da app
(`sky-mobile/apps/mobile/src/numeros.ts`, cópia da web): a resposta escrita
pela IA e o cartão desenhado pela web dizem o mesmo número da mesma maneira.

Até aqui o sky-ai escrevia sempre duas casas («412.300,00 €», #290).
"""

from core.llm.numeros import (
    CorrecaoEmFluxo,
    corrigir_resposta,
    formatar_valor,
    regras_de_numeros,
)

# ── O formatador determinístico ─────────────────────────────────────────


def test_redondo_sem_zeros_a_direita():
    assert formatar_valor(412300, "pt", True) == "412.300 €"
    assert formatar_valor(412300.0, "es", True) == "412.300 €"
    assert formatar_valor(17, "pt", True) == "17 €"


def test_com_centimos_leva_as_duas_casas():
    assert formatar_valor(1234.5, "pt", True) == "1.234,50 €"
    assert formatar_valor(1234.56, "pt", True) == "1.234,56 €"
    assert formatar_valor(6153185.72, "es", True) == "6.153.185,72 €"


def test_meio_euro_e_0_50():
    assert formatar_valor(0.5, "pt", True) == "0,50 €"
    assert formatar_valor(0.5, "en", True) == "€0.50"


def test_negativos():
    assert formatar_valor(-1234.5, "pt", True) == "-1.234,50 €"
    assert formatar_valor(-412300, "pt", True) == "-412.300 €"
    assert formatar_valor(-1234.5, "en", True) == "-€1,234.50"
    assert formatar_valor(-412300, "en", True) == "-€412,300"


def test_arredondado_a_zero_nao_leva_sinal():
    # Web: `negativo = valor < 0 && arredondado !== 0`.
    assert formatar_valor(-0.001, "pt", True) == "0 €"


def test_quase_redondo_arredonda_para_redondo():
    # 1234,999 a duas casas é 1235,00 → redondo.
    assert formatar_valor(1234.999, "pt", True) == "1.235 €"
    assert formatar_valor(412300.004, "pt", True) == "412.300 €"


def test_ingles():
    assert formatar_valor(412300, "en", True) == "€412,300"
    assert formatar_valor(1234.5, "en", True) == "€1,234.50"


def test_contagens_nao_mudam():
    # A regra é só do dinheiro: contagens continuam como no #290.
    assert formatar_valor(4526, "pt", agrupar=True) == "4.526"
    assert formatar_valor(17, "pt") == "17"


# ── A correcção da resposta (caminho escrito) ────────────────────────────


def test_resposta_tira_o_00_que_o_modelo_escreveu():
    linhas = [{"revenue": 412300.0}]
    out = corrigir_resposta("Faturou 412.300,00 € este ano.", "pt", linhas)
    assert out == "Faturou 412.300 € este ano."


def test_resposta_poe_a_segunda_casa_que_faltava():
    linhas = [{"revenue": 1234.5}]
    out = corrigir_resposta("Faturou 1.234,5 € este mês.", "pt", linhas)
    assert out == "Faturou 1.234,50 € este mês."


def test_resposta_em_ingles():
    linhas = [{"revenue": 412300.0}, {"revenue": 1234.5}]
    out = corrigir_resposta(
        "Revenue was 412300.00 and then 1234.5 euros.", "en", linhas
    )
    assert "€412,300" in out and "€412,300.00" not in out
    assert "€1,234.50" in out


# ── O streaming (CorrecaoEmFluxo) decide o mesmo ────────────────────────


def _fluxo(pedacos, lingua, linhas):
    c = CorrecaoEmFluxo(lingua, linhas)
    out = "".join(c.receber(p) for p in pedacos)
    return out + c.terminar()


def test_streaming_redondo_e_com_centimos():
    linhas = [{"revenue": 412300.0}, {"revenue": 1234.5}]
    texto = "Faturou 412.300,00 € num mês e 1.234,5 € no outro."
    pedacos = [texto[i : i + 4] for i in range(0, len(texto), 4)]
    out = _fluxo(pedacos, "pt", linhas)
    assert out == "Faturou 412.300 € num mês e 1.234,50 € no outro."
    assert out == corrigir_resposta(texto, "pt", linhas)


# ── As instruções ao modelo ─────────────────────────────────────────────


def test_prompt_pt_diz_redondo_sem_00_e_centimos_com_duas():
    p = regras_de_numeros("pt", ["revenue", "customers"])
    assert "monetary amount with EXACTLY two decimals" not in p
    assert "412.300 €" in p
    assert "1.234,50 €" in p
    assert "412.300,00" in p  # como exemplo do que NÃO se escreve
    assert "1.234,5 €" in p  # idem


def test_prompt_en():
    p = regras_de_numeros("en", ["revenue"])
    assert "monetary amount with EXACTLY two decimals" not in p
    assert "€412,300" in p
    assert "€1,234.50" in p
