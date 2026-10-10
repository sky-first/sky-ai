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

── A rede depois do modelo (10/10/2026) ─────────────────────────────────────

As regras vão ANTES, no prompt — mas o modelo de produção não as segue
sempre. No projecto de restauração, «¿Cuánto he facturado?» deu:

    El usuario ha facturado un total de 6 153 185,72.

Espaços nos milhares e nenhum euro, com as regras no prompt. Por isso há
agora uma correcção DETERMINÍSTICA por cima do texto final
(`corrigir_resposta`). Não é a passagem cega de expressões regulares que
estragava datas e identificadores: só mexe num número quando

* ele é, lido de qualquer maneira, um VALOR do resultado (ou a soma, média,
  mínimo ou máximo de uma coluna de dinheiro) — e então sabe-se o que é; ou
* traz um marcador de moeda colado («15.5 €») — e então é dinheiro; ou
* tem separadores e só uma leitura possível («6 153 185,72»).

Números corridos sem separador (anos, códigos, identificadores), datas e
percentagens ficam como estão. A regra do Lucas: estamos na Europa —
dinheiro leva sempre «€», «6.153.185,72 €» em pt/es e «€6,153,185.72» em
inglês.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

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
    # Castelhano e o resto do vocabulário de dinheiro (10/10: «facturado»
    # não estava na lista e a resposta saiu sem euro).
    "facturado",
    "facturacion",
    "facturación",
    "faturacao",
    "faturação",
    "importe",
    "ingresos",
    "ingreso",
    "ventas",
    "vendas",
    "sales",
    "precio",
    "coste",
    "costo",
    "margen",
    "beneficio",
    "ganancia",
    "income",
    "turnover",
    "gmv",
    "aov",
    "pvp",
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
    "hours",
    "horas",
    "año",
    "cantidad",
    "units",
    "unidades",
    "orders",
    "pedidos",
    "encomendas",
    "customers",
    "clientes",
    "items",
    "artigos",
    "stores",
    "tiendas",
    "lojas",
    "headcount",
    "sec",
    "seconds",
    "segundos",
    "minutes",
    "minutos",
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
#: A Sky vende-se na Europa: em inglês também são euros (regra do Lucas,
#: 10/10/2026). A moeda definida pela pessoa continua a ganhar.
MOEDA_POR_LINGUA = {"pt": "EUR", "es": "EUR", "en": "EUR"}

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
    return MOEDA_POR_LINGUA.get(lingua, "EUR")


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
    # O espanhol usa os mesmos separadores do portugues — ponto nos milhares,
    # virgula nos decimais — e tambem o euro. Nao e uma coincidencia
    # feliz: e a convencao europeia, e a Sky vende-se na Europa.
    if lingua in ("pt", "es"):
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
        if lingua in ("pt", "es"):
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


# ── A correcção depois do modelo ─────────────────────────────────────────

_ESPACOS = "    "

#: Um número escrito: agrupado (com espaço, ponto ou vírgula) ou corrido, com
#: decimais opcionais, e o marcador de moeda que o modelo lhe tenha colado.
#: Não pode estar agarrado a uma palavra, a uma data (``2026-08-01``), a uma
#: hora (``12:30``) nem a outro número.
_NUMERO = re.compile(
    r"(?P<pre>(?:€|\bEUR)[  ]?)?"
    r"(?<![\w.,\-/:])"
    r"(?P<n>\d{1,3}(?:[    .,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"(?![\w\-/:]|[.,]\d)"
    r"(?P<pos>[  ]?(?:€|EUR\b|euros?\b))?",
    re.IGNORECASE,
)

_PERCENTAGEM = re.compile(r"^\s?%")


def _e_identificador(nome: str) -> bool:
    p = _palavras(nome)
    return bool(p & {"id", "ids", "year", "ano", "año", "sku", "code", "codigo"})


def _numero(valor: Any) -> Optional[float]:
    if isinstance(valor, bool) or valor is None:
        return None
    if isinstance(valor, (int, float, Decimal)):
        return float(valor)
    if isinstance(valor, str) and re.fullmatch(r"[+-]?\d+(?:\.\d+)?", valor.strip()):
        return float(valor)
    return None


def valores_do_resultado(
    linhas: Optional[Sequence[Dict[str, Any]]],
) -> Tuple[List[float], List[float]]:
    """(valores de dinheiro, outros valores numéricos) do resultado.

    Os de dinheiro incluem a soma, a média, o mínimo e o máximo de cada
    coluna de dinheiro — é o que o modelo costuma escrever quando resume.
    Identificadores e anos ficam de fora: nunca se reformatam.
    """
    dinheiro: List[float] = []
    outros: List[float] = []
    if not linhas or not isinstance(linhas[0], dict):
        return dinheiro, outros
    for c in list(linhas[0].keys()):
        if _e_identificador(c):
            continue
        vals = [
            v
            for v in (_numero(r.get(c)) for r in linhas if isinstance(r, dict))
            if v is not None
        ]
        if not vals:
            continue
        if e_dinheiro(c):
            dinheiro += vals
            if len(vals) > 1:
                dinheiro += [sum(vals), sum(vals) / len(vals), min(vals), max(vals)]
        else:
            outros += vals
    return dinheiro, outros


def _leituras(token: str) -> List[float]:
    """As leituras possíveis de um número escrito, sem adivinhar a língua."""
    s = re.sub(f"[{_ESPACOS}]", "", token)
    out: List[float] = []
    for milhares, decimal in ((".", ","), (",", ".")):  # pt/es, depois en
        inteira, _, frac = s.partition(decimal)
        if decimal in frac:
            continue
        grupos = inteira.split(milhares)
        # Um separador de milhares tem sempre três algarismos à direita:
        # «15.5» nunca é cento e cinquenta e cinco.
        if any(len(g) != 3 for g in grupos[1:]):
            continue
        v = float("".join(grupos) + ("." + frac if frac else ""))
        if v not in out:
            out.append(v)
    return out


def _igual(a: float, b: float) -> bool:
    return abs(a - b) <= 0.005 + 1e-9 * abs(b)


def formatar_valor(
    valor: float, lingua: str, dinheiro: bool = False, simbolo: str = "€"
) -> str:
    """Um número escrito à maneira de quem lê.

    pt/es: ``6.153.185,72 €``; en: ``€6,153,185.72``. Dinheiro leva sempre
    duas casas; contagens nenhuma; inteiros abaixo de 10 000 que não são
    dinheiro ficam sem separador (``2026`` é um ano tantas vezes quanto é
    uma contagem).
    """
    europeu = lingua in ("pt", "es")
    negativo = valor < 0
    v = abs(valor)
    if dinheiro:
        s = f"{v:,.2f}"
    elif float(v).is_integer():
        s = f"{int(v)}" if v < 10000 else f"{int(v):,}"
    else:
        s = f"{v:,.2f}"
    if europeu:
        s = s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    sinal = "-" if negativo else ""
    if dinheiro:
        return f"{sinal}{s} {simbolo}" if europeu else f"{sinal}{simbolo}{s}"
    return f"{sinal}{s}"


_INICIO = r"(^|(?<=[.!?]\s))"

#: «El usuario ha facturado…» — a resposta fala COM quem pergunta, nunca
#: SOBRE ele. Só no início de uma frase, onde a troca é segura: em pt e es o
#: verbo na terceira pessoa é já a forma de cortesia («Ha facturado»).
_SUJEITO_ES_PT = re.compile(
    _INICIO + r"(?:(?:el|la) usuari[oa]|o (?:utilizador|usu[aá]rio)) (\w+)",
    re.IGNORECASE,
)
_SUJEITO_EN = [
    (re.compile(_INICIO + r"the user has\b", re.IGNORECASE), "You have"),
    (re.compile(_INICIO + r"the user had\b", re.IGNORECASE), "You had"),
    (re.compile(_INICIO + r"the user is\b", re.IGNORECASE), "You are"),
    (re.compile(_INICIO + r"the user was\b", re.IGNORECASE), "You were"),
    (re.compile(_INICIO + r"the user's\b", re.IGNORECASE), "Your"),
    (re.compile(_INICIO + r"the user (?=\w+ed\b)", re.IGNORECASE), "You "),
]


def falar_com_quem_pergunta(texto: str) -> str:
    """Troca «El usuario ha facturado» por «Ha facturado» (e o mesmo em pt/en)."""
    texto = _SUJEITO_ES_PT.sub(
        lambda m: m.group(1) + m.group(2)[:1].upper() + m.group(2)[1:], texto
    )
    for padrao, troca in _SUJEITO_EN:
        texto = padrao.sub(lambda m, t=troca: m.group(1) + t, texto)
    return texto


def corrigir_numeros(
    texto: str,
    lingua: str,
    linhas: Optional[Sequence[Dict[str, Any]]] = None,
    moeda_pedida: Optional[str] = None,
) -> str:
    """Reescreve os números da resposta no formato de quem lê. Ver o topo."""
    if not texto:
        return texto
    lingua = (lingua or "en").split("-")[0].lower()
    dinheiro, outros = valores_do_resultado(linhas)
    moeda = (moeda_pedida or MOEDA_POR_LINGUA.get(lingua, "EUR")).upper()
    simbolo = SIMBOLO.get(moeda, moeda)

    def trocar(m: "re.Match[str]") -> str:
        token = m.group("n")
        if _PERCENTAGEM.match(texto[m.end("n") :]):
            return m.group(0)
        tem_moeda = bool(m.group("pre") or m.group("pos"))
        leituras = _leituras(token)
        if not leituras:
            return m.group(0)
        com_separador = bool(re.search(f"[.,{_ESPACOS}]", token))
        for r in leituras:
            for v in dinheiro:
                if _igual(r, v):
                    return formatar_valor(v, lingua, True, simbolo)
        for r in leituras:
            for v in outros:
                if _igual(r, v):
                    return formatar_valor(v, lingua, tem_moeda, simbolo)
        # Arredondado pelo modelo («6.153.186 €») — só em valores grandes,
        # para uma contagem de 12 nunca virar o preço de 12,40 €.
        if not re.search(r"[.,]\d{1,2}$", token):
            for r in leituras:
                for v in dinheiro:
                    if abs(v) >= 1000 and abs(r - v) < 0.5:
                        return formatar_valor(v, lingua, True, simbolo)
        if len(leituras) == 1 and (com_separador or tem_moeda):
            return formatar_valor(leituras[0], lingua, tem_moeda, simbolo)
        if tem_moeda:
            # Ambíguo («1.234 €»): lê-se como se escreve na língua da resposta.
            r = leituras[0] if lingua in ("pt", "es") else leituras[-1]
            return formatar_valor(r, lingua, True, simbolo)
        return m.group(0)

    return _NUMERO.sub(trocar, texto)


def corrigir_resposta(
    texto: str,
    lingua: str,
    linhas: Optional[Sequence[Dict[str, Any]]] = None,
    moeda_pedida: Optional[str] = None,
) -> str:
    """A resposta final: números à maneira de quem lê, e na segunda pessoa."""
    if not texto:
        return texto
    return corrigir_numeros(
        falar_com_quem_pergunta(texto), lingua, linhas, moeda_pedida
    )


#: O fim do texto que ainda pode ser metade de um número («6 153») ou de um
#: marcador de moeda («6.153,72 eu…»). Fica retido até chegar o resto.
_CAUDA_INCERTA = re.compile(r"[\d.,€" + _ESPACOS + r"EeUuRrOoSs]*$")
#: Uma frase com menos do que isto ainda pode ser «El usuario ha…».
_INICIO_DE_FRASE = 28


class CorrecaoEmFluxo:
    """A mesma correcção, pedaço a pedaço, para o caminho em streaming.

    O protocolo só tem ``chunk`` — não há «substituir o que já foi» — e a voz
    lê os mesmos pedaços, por isso o que sai tem de já ir certo. Retém-se só
    a cauda que ainda pode mudar (um número a meio, um início de frase).
    """

    def __init__(
        self, lingua: str, linhas=None, moeda_pedida: Optional[str] = None
    ) -> None:
        self.lingua = lingua
        self.linhas = linhas
        self.moeda_pedida = moeda_pedida
        self.bruto = ""
        self.enviado = ""

    def _processar(self, texto: str) -> str:
        return corrigir_resposta(texto, self.lingua, self.linhas, self.moeda_pedida)

    def _corte(self) -> int:
        corte = len(self.bruto) - len(_CAUDA_INCERTA.search(self.bruto).group(0))
        inicio = 0
        for m in re.finditer(r"[.!?]\s+", self.bruto):
            inicio = m.end()
        if len(self.bruto) - inicio < _INICIO_DE_FRASE:
            corte = min(corte, inicio)
        return corte

    def _emitir(self, processado: str) -> str:
        if not processado.startswith(self.enviado):
            return ""
        delta = processado[len(self.enviado) :]
        self.enviado = processado
        return delta

    def receber(self, pedaco: str) -> str:
        self.bruto += pedaco or ""
        return self._emitir(self._processar(self.bruto[: self._corte()]))

    def terminar(self) -> str:
        final = self._processar(self.bruto)
        if final.startswith(self.enviado):
            return self._emitir(final)
        # Não deve acontecer; se acontecer, não se perde o resto do texto.
        resto = (
            self.bruto[len(self.enviado) :]
            if len(self.bruto) > len(self.enviado)
            else ""
        )
        self.enviado += resto
        return resto

    @property
    def texto(self) -> str:
        return self.enviado
