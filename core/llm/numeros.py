"""Como se escrevem os números numa resposta — e quando levam moeda.

**O defeito.** O Lucas perguntou «Sky quanto faturamos?» e leu:

    The data shows a total revenue of 192,022.6.

Três coisas erradas numa frase de seis palavras:

1. **Os separadores são os americanos.** Em Portugal `192,022.6` lê-se cento
   e noventa e dois vírgula zero vinte e dois — um número mil vezes menor.
   Não é cosmético: é o número errado para quem o lê.
2. **Não diz que são euros.** «Receita de 192 022» pode ser euros, reais ou
   unidades. Numa reunião de vendas isso é a diferença entre uma boa notícia
   e uma pergunta.
3. **Uma casa decimal.** `265.221,0` — nem inteiro nem dinheiro. Dinheiro tem
   duas casas; contagens não têm nenhuma. Uma é sempre lixo de vírgula
   flutuante que passou pelo modelo.

**Porque não havia regra nenhuma.** O prompt do formatador tem dez regras
sobre o que NÃO inventar e zero sobre como escrever um número. O modelo
copiava o que via na pré-visualização dos dados — que vem do Postgres em
formato neutro — e o resultado dependia do humor do modelo nesse dia.

── Porque a moeda se adivinha da COLUNA e não da pergunta ───────────────────

A tentação é olhar para a pergunta: «faturamos» → dinheiro. Falha nos dois
sentidos. «Quantas faturas estão em atraso?» tem «fatura» e a resposta é uma
contagem. «Qual foi o ticket médio?» não tem palavra nenhuma de dinheiro e é
dinheiro.

A coluna sabe. `amount`, `revenue`, `monthly_amount`, `price` são dinheiro
onde quer que apareçam; `count`, `id`, `qty` nunca são. É o esquema que
manda, não o vocabulário da pergunta.

── O que isto NÃO faz ───────────────────────────────────────────────────────

Não converte moeda. Se a base guarda dólares e a pessoa está em Portugal, o
número é em dólares e assim é apresentado — inventar uma conversão com uma
taxa que não temos era pior do que não dizer nada.

E não reescreve a resposta depois de o modelo a escrever. Já tentei essa
tentação noutro sítio: uma passagem de expressões regulares por cima do texto
final apanha datas (`2026-08-01`), identificadores e percentagens, e estraga
mais do que arranja. As regras vão ANTES, no prompt, onde o modelo ainda sabe
o que cada número significa.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

#: Pedacos de nome que dizem «isto e dinheiro». Comparados por PALAVRA e nao
#: por pedaco de texto — ver `_palavras`, e a razao la em baixo.
PALAVRAS_DE_DINHEIRO = {
    "amount",
    "amounts",
    "revenue",
    "receita",
    "faturado",
    "faturamento",
    "price",
    "preco",
    "preço",
    "cost",
    "custo",
    "value",
    "valor",
    "salary",
    "salario",
    "salário",
    "mrr",
    "arr",
    "ticket",
    "margem",
    "margin",
    "lucro",
    "profit",
    "despesa",
    "expense",
    "billing",
    "total",
    "subtotal",
    "balance",
    "saldo",
    "spend",
    "gasto",
}

#: E as que NUNCA sao, mesmo ao lado de uma das de cima. `revenue_count` e uma
#: contagem; `price_id` e um identificador. Ganham a lista anterior.
PALAVRAS_QUE_NAO_SAO_DINHEIRO = {
    "id",
    "ids",
    "count",
    "contagem",
    "quantidade",
    "qty",
    "num",
    "numero",
    "pct",
    "percent",
    "percentagem",
    "percentage",
    "ratio",
    "rate",
    "taxa",
    "year",
    "ano",
    "month",
    "mes",
    "mês",
    "day",
    "dia",
    "week",
    "semana",
    "date",
    "data",
    "hora",
    "hour",
}


def _palavras(nome: str) -> set:
    """As palavras de um nome de coluna.

    **Por palavra e nao por pedaco de texto.** A primeira versao disto
    procurava «month» dentro do nome — e `monthly_amount`, que e a coluna de
    dinheiro das subscricoes, deixava de ser dinheiro porque «monthly» contem
    «month». Apanhei-o a experimentar a funcao antes de a ligar.

    E o mesmo erro em ponto pequeno que o resto deste ficheiro trata: comparar
    texto onde se devia comparar significado.
    """
    return set(re.split(r"[^a-z0-9]+", (nome or "").lower())) - {""}


def e_dinheiro(nome_da_coluna: str) -> bool:
    """Se uma coluna com este nome contem dinheiro.

    A lista de excepcoes ganha: `revenue_count` e uma contagem apesar de ter
    «revenue», e escrever «1.234,00 EUR» num numero de faturas e tao errado
    quanto o contrario.
    """
    p = _palavras(nome_da_coluna)
    if not p:
        return False
    if p & PALAVRAS_QUE_NAO_SAO_DINHEIRO:
        return False
    return bool(p & PALAVRAS_DE_DINHEIRO)


#: A moeda de omissao por lingua. Nao e adivinhacao sobre os DADOS — e sobre
#: quem le. Ver a limitacao la em cima: nao se converte nada.
MOEDA_POR_LINGUA = {"pt": "EUR", "en": "USD"}

SIMBOLO = {"EUR": "€", "USD": "$", "BRL": "R$", "GBP": "£"}


def moeda_provavel(
    colunas: Optional[Iterable[str]],
    lingua: str,
    moeda_pedida: Optional[str] = None,
) -> Optional[str]:
    """A moeda a usar, ou `None` quando não há dinheiro nenhum na resposta.

    `moeda_pedida` ganha sempre: é a definição de quem pergunta, e uma
    definição explícita vale mais do que qualquer heurística nossa.
    """
    if not any(e_dinheiro(c) for c in (colunas or [])):
        return None
    if moeda_pedida:
        return moeda_pedida.upper()
    return MOEDA_POR_LINGUA.get(lingua, "USD")


def regras_de_numeros(
    lingua: str,
    colunas: Optional[Iterable[str]] = None,
    moeda_pedida: Optional[str] = None,
) -> str:
    """O bloco que entra no prompt do formatador.

    Escrito em inglês como o resto do prompt: misturar línguas dentro de um
    prompt faz modelos pequenos responderem na língua das instruções em vez
    da língua pedida — já aconteceu aqui.
    """
    if lingua == "pt":
        milhares, decimal, exemplo = "a dot (.)", "a comma (,)", "192.022,60"
        exemplo_inteiro = "17"
    else:
        milhares, decimal, exemplo = "a comma (,)", "a dot (.)", "192,022.60"
        exemplo_inteiro = "17"

    moeda = moeda_provavel(colunas, lingua, moeda_pedida)

    linhas = [
        "",
        "NUMBER FORMATTING (NON-NEGOTIABLE — the reader is in a locale where",
        "the separators are NOT the US ones; getting them wrong changes the value):",
        f"- Thousands separator: {milhares}. Decimal separator: {decimal}.",
        f"- Example of a correctly written amount: {exemplo}",
        "- COUNTS (invoices, customers, orders, days) have NO decimals at all:",
        f"  write {exemplo_inteiro}, never {exemplo_inteiro},0 or {exemplo_inteiro}.0.",
        "- Never leave a single trailing decimal digit. It is float noise, not a",
        "  measurement.",
        "- Do NOT change any digit while reformatting. Only the separators move.",
    ]

    if moeda:
        s = SIMBOLO.get(moeda, moeda)
        if lingua == "pt":
            linhas += [
                f"- MONEY: this answer reports monetary values in {moeda}. Write every",
                f"  monetary amount with EXACTLY two decimals and the symbol AFTER the",
                f"  number, separated by a space: 192.022,60 {s}",
            ]
        else:
            linhas += [
                f"- MONEY: this answer reports monetary values in {moeda}. Write every",
                f"  monetary amount with EXACTLY two decimals and the symbol BEFORE the",
                f"  number: {s}192,022.60",
            ]
        linhas += [
            "- Do NOT convert between currencies. The number is already in the",
            f"  currency above; report it as it is.",
        ]
    else:
        linhas += [
            "- No monetary column was detected in this result. Do NOT attach a",
            "  currency symbol to any number.",
        ]

    return "\n".join(linhas) + "\n"
