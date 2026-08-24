"""O prompt do formatador nao pode mandar duas coisas contrarias.

**O defeito, visto ao vivo.** Com as regras de formatacao ja no prompt, a Sky
respondeu «O total das faturas em atraso é 7476.32.» — sem separadores e sem
moeda.

A causa nao era o bloco de formatacao. Era a regra 10, que dizia::

    report every number EXACTLY as it appears in the results

O modelo obedecia a essa, que e mais antiga, esta numerada e grita
NON-NEGOTIABLE. **Duas instrucoes que se contradizem nao sao duas instrucoes:
sao uma instrucao e a ilusao de que se pediu a outra coisa.**

A regra 10 e sobre o VALOR (nao multiplicar, nao converter). O bloco de
formatacao e sobre a PONTUACAO. Agora dizem-no as duas.
"""

from unittest.mock import MagicMock

from core.llm.numeros import regras_de_numeros
from core.llm.prompts.formatter_prompts import build_formatter_prompt


def _prompt(lingua="pt", colunas=("total_amount",)):
    cb = MagicMock()
    cb.user.platform_role = "admin"
    cb.user.crew_role = "member"
    cb.user.role_label = "Admin"
    s, _u = build_formatter_prompt(
        context_bundle=cb,
        question="quanto somam as faturas em atraso?",
        sql="select ...",
        data_preview='[{"total_amount": 7476.32}]',
        detected_language=lingua,
        regras_dos_numeros=regras_de_numeros(lingua, list(colunas)),
    )
    return s["content"]


def test_as_regras_de_formatacao_estao_no_prompt():
    assert "NUMBER FORMATTING" in _prompt()


def test_a_regra_10_ja_NAO_manda_copiar_o_numero_tal_e_qual():
    """**O defeito exacto.**

    «EXACTLY as it appears» ganhava ao bloco de formatacao e o numero saia em
    cru.
    """
    p = _prompt()
    assert "EXACTLY as it appears" not in p


def test_a_regra_10_continua_a_proibir_converter():
    """A correccao nao pode abrir a porta ao que a regra 10 protegia.

    Multiplicar 0,75 por 100 continua proibido — o que passa a ser permitido
    e so mover um separador.
    """
    p = _prompt()
    assert "NEVER rescale, multiply, divide or convert" in p
    assert "0.75 is 0.75, NOT 75%" in p


def test_a_regra_10_APONTA_para_o_bloco_de_formatacao():
    """As duas tem de se reconhecer, senao o modelo escolhe uma.

    Nao chega tirar a contradicao: e preciso dizer-lhe que nao ha
    contradicao, porque ele ve as duas seccoes ao mesmo tempo.
    """
    p = _prompt()
    i = p.find("10. NEVER rescale")
    # O CABECALHO da seccao, e nao a primeira mencao — a regra 10 cita o nome
    # da seccao, e procurar so o nome encontrava a citacao.
    j = p.find("NUMBER FORMATTING (NON-NEGOTIABLE")
    assert i >= 0, "regra 10 nao encontrada"
    assert j > i, "o bloco de formatacao tem de vir DEPOIS da regra 10"
    # A regra 10 tem de MENCIONAR a seccao. Sem isso o modelo ve duas
    # instrucoes e escolhe uma.
    assert "NUMBER FORMATTING" in p[i:j]
    assert "separator" in p[i:j].lower()


def test_a_regra_de_moeda_so_aparece_quando_ha_dinheiro():
    com = _prompt(colunas=("total_amount",))
    sem = _prompt(colunas=("invoice_count",))
    assert "MONEY:" in com
    assert "MONEY:" not in sem
