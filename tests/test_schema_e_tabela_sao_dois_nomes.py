"""`finance.invoices` são DOIS nomes, não um nome com um ponto.

O descobridor de período citava o nome inteiro de uma vez — `"finance.invoices"`
— e isso é um nome com um ponto lá dentro. O Postgres procura uma tabela
chamada literalmente «finance.invoices», não a encontra, e devolve:

    relation "finance.invoices" does not exist

**O efeito não é um erro à vista.** Quem chama isto está só a descobrir o
período dos dados, e uma falha devolve `(None, None)` — o motor conclui que a
fonte não tem datas e a resposta que chega a quem perguntou é «Não há dados
disponíveis nessa fonte».

Medido em produção a 22/08/2026: 558 faturas na tabela, e o agente a dizer que
não havia dados. A consulta principal escapava porque o modelo escreve o SQL
sem aspas; era só este passo.
"""

from __future__ import annotations

from core.llm.periodo_decision import _citar


def test_o_schema_e_a_tabela_ficam_em_aspas_separadas():
    assert _citar("finance.invoices") == '"finance"."invoices"'


def test_um_nome_sem_schema_continua_inteiro():
    """Nem tudo tem schema — e envolver um nome simples em aspas continua a
    ser o que se quer."""
    assert _citar("invoices") == '"invoices"'


def test_o_bigquery_usa_as_suas_aspas():
    assert _citar("dataset.tabela", "`") == "`dataset`.`tabela`"


def test_tres_partes_tambem(  ):
    """O BigQuery tem `projeto.dataset.tabela`. Cada parte é uma parte."""
    assert _citar("proj.ds.tab", "`") == "`proj`.`ds`.`tab`"


def test_o_nome_inteiro_ja_nao_e_citado_de_uma_vez():
    """O guarda do defeito: era isto, à letra, que produzia o SQL errado."""
    import inspect

    from core.llm import periodo_decision

    fonte = "\n".join(
        l
        for l in inspect.getsource(periodo_decision).splitlines()
        if not l.lstrip().startswith("#")
    )
    assert '"{physical_name}"' not in fonte
    assert "`{physical_name}`" not in fonte
