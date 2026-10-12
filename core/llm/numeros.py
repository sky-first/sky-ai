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
    # A moeda no nome é o sinal mais claro de todos (`cost_eur`,
    # `gasoleo_eur_l` — dados públicos, 11/10).
    "eur",
    "euro",
    "euros",
}

#: Palavras de um nome de coluna que dizem «por litro». Só contam numa
#: coluna de dinheiro: `gasoleo_eur_l` é um preço por litro, `fuel_liters`
#: é uma quantidade.
PALAVRAS_DE_LITRO = {"l", "lt", "litro", "litros", "litre", "litres", "liter", "liters"}


def e_preco_por_litro(nome_da_coluna: str) -> bool:
    """Se a coluna guarda um preço por litro — e só então a resposta diz «€/l».

    Decide-se pelo NOME, como o resto deste ficheiro: `media` de
    `gasoleo_historico_diario` também é €/l (diz o comentário da coluna), mas
    o nome não o diz e a correcção não o adivinha — fica «1,90 €».
    """
    return e_dinheiro(nome_da_coluna) and bool(
        _palavras(nome_da_coluna) & PALAVRAS_DE_LITRO
    )


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


# ── Unidades (12/10/2026) ────────────────────────────────────────────────
#
# Na análise «context» de um agente lia-se: «La mayor diferencia … está en el
# canal drive, con una diferencia de 36,81; aproximar el peor a la media
# generaría un ganho de 36,81». 36,81 quê? A coluna era ``service_sec``:
# segundos. Um número sem unidade obriga quem lê a adivinhar — e o backend,
# que sintetiza a partir destas respostas, copia o número nu.
#
# A unidade vem da COLUNA, como a moeda: pelo nome (``*_sec``, ``*_min``,
# ``dist_km``, ``*_pct``…), pela descrição quando o nome não diz
# («Duración en segundos») e pela linhagem do SQL — ``MAX(avg_service_sec) -
# AVG(avg_service_sec) AS diferencia`` continua a ser segundos. Divisões,
# multiplicações e contagens mudam a unidade: aí não se herda nada.

#: (palavras do nome da coluna, unidade). A primeira que casar ganha.
UNIDADES_POR_NOME: List[Tuple[set, str]] = [
    ({"ms", "millis", "milliseconds", "milisegundos", "milissegundos"}, "ms"),
    ({"sec", "secs", "second", "seconds", "segundo", "segundos", "seg", "segs"}, "s"),
    ({"min", "mins", "minute", "minutes", "minuto", "minutos"}, "min"),
    ({"hours", "hrs", "horas"}, "h"),
    ({"km", "kms", "kilometros", "quilometros", "kilometers", "kilometres"}, "km"),
    ({"pct", "percent", "percentage", "porcentaje", "percentagem", "pcnt"}, "%"),
    ({"kg", "kgs", "kilos", "kilogramos", "quilos"}, "kg"),
    ({"litros", "liters", "litres", "lts"}, "l"),
    ({"units", "unidades", "uds"}, "un"),
]

#: Na descrição (quando o nome não diz nada).
_UNIDADE_NA_DESCRICAO: List[Tuple["re.Pattern[str]", str]] = [
    (re.compile(r"\bmil[ie]?s+egundos?\b|\bmilliseconds?\b", re.I), "ms"),
    (re.compile(r"\bsegundos?\b|\bseconds?\b|\bsecs?\b", re.I), "s"),
    (re.compile(r"\bminutos?\b|\bminutes?\b|\bmins?\b", re.I), "min"),
    (re.compile(r"\bhoras\b|\bhours\b", re.I), "h"),
    (re.compile(r"\bkm\b|\bk[iu]l[oó]metros?\b|\bquil[oó]metros?\b", re.I), "km"),
    (re.compile(r"%|\bpercentagem\b|\bporcentaje\b|\bpercent(age)?\b", re.I), "%"),
    (re.compile(r"\blitros?\b|\blit(er|re)s?\b", re.I), "l"),
]

_PALAVRA_UNIDADES = {"pt": "unidades", "es": "unidades", "en": "units"}


def unidade_do_nome(nome: str) -> Optional[str]:
    """A unidade que o NOME da coluna diz, ou None. Dinheiro e
    identificadores não têm unidade aqui (o dinheiro tem a sua regra)."""
    p = _palavras(nome)
    if not p or e_dinheiro(nome) or _e_identificador(nome):
        return None
    for palavras, unidade in UNIDADES_POR_NOME:
        if p & palavras:
            return unidade
    return None


def unidade_da_descricao(descricao: Optional[str]) -> Optional[str]:
    d = descricao or ""
    # «€/l», «EUR por litro»: é um preço, não uma quantidade.
    if not d or re.search(r"€|\beur\b|\beuros?\b", d, re.I):
        return None
    for padrao, unidade in _UNIDADE_NA_DESCRICAO:
        if padrao.search(d):
            return unidade
    return None


def _unidades_pelo_sql(
    sql: Optional[str], unidade_de: Dict[str, Optional[str]]
) -> Dict[str, str]:
    """Aliases do SQL que herdam a unidade das colunas de onde vêm."""
    if not sql:
        return {}
    try:
        import sqlglot
        from sqlglot import exp

        arvore = sqlglot.parse_one(sql, read="postgres")
    except Exception:
        try:
            import sqlglot
            from sqlglot import exp

            arvore = sqlglot.parse_one(sql)
        except Exception:
            return {}
    if arvore is None:
        return {}
    conhecidas: Dict[str, Optional[str]] = {k.lower(): v for k, v in unidade_de.items()}
    herdadas: Dict[str, str] = {}
    aliases = list(arvore.find_all(exp.Alias))
    # O que muda a unidade: rácios, produtos, contagens, partes de datas.
    mudam = tuple(
        t
        for t in (
            getattr(exp, n, None) for n in ("Div", "IntDiv", "Mul", "Count", "Extract")
        )
        if t is not None
    )
    for _ in range(3):  # aliases de CTE usados mais acima
        mudou = False
        for a in aliases:
            nome = (a.alias or "").lower()
            if not nome or nome in herdadas:
                continue
            corpo = a.this
            if any(isinstance(n, mudam) for n in corpo.walk()):
                continue
            fontes = {c.name.lower() for c in corpo.find_all(exp.Column)}
            unidades = {
                conhecidas.get(f) or unidade_do_nome(f) or herdadas.get(f)
                for f in fontes
            } - {None}
            if len(unidades) == 1:
                herdadas[nome] = unidades.pop()
                mudou = True
        if not mudou:
            break
    return herdadas


def unidades_do_resultado(
    colunas: Optional[Iterable[str]],
    sql: Optional[str] = None,
    descricoes: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """``{coluna do resultado: unidade}`` — pelo nome, pela linhagem do SQL
    e pela descrição, por esta ordem."""
    descricoes = {str(k).lower(): v for k, v in (descricoes or {}).items()}
    unidade_de: Dict[str, Optional[str]] = {}
    for nome, desc in descricoes.items():
        if not e_dinheiro(nome) and not _e_identificador(nome):
            unidade_de[nome] = unidade_do_nome(nome) or unidade_da_descricao(desc)
    pelo_sql = _unidades_pelo_sql(sql, unidade_de)
    out: Dict[str, str] = {}
    for c in colunas or []:
        if e_dinheiro(c) or _e_identificador(c):
            continue
        u = (
            unidade_do_nome(c)
            or pelo_sql.get(str(c).lower())
            or unidade_da_descricao(descricoes.get(str(c).lower()))
        )
        if u:
            out[c] = u
    return out


def descricoes_das_colunas(
    tabelas: Optional[Iterable[Any]], escolhidas: Optional[Iterable[str]] = None
) -> Dict[str, str]:
    """``{coluna: descrição}`` das tabelas do agente — as escolhidas primeiro
    (o mesmo nome noutra tabela não pode ganhar a uma das escolhidas)."""
    escolhidas_set = {str(e).lower() for e in (escolhidas or []) if e}

    def escolhida(t: Any) -> bool:
        nomes = {
            str(getattr(t, a, "") or "").lower()
            for a in ("logical_name", "physical_name", "display_name")
        }
        return bool(nomes & escolhidas_set)

    ordenadas = sorted(list(tabelas or []), key=lambda t: 0 if escolhida(t) else 1)
    out: Dict[str, str] = {}
    for t in ordenadas:
        for c in getattr(t, "columns", None) or []:
            nome = c.get("name") if isinstance(c, dict) else getattr(c, "name", None)
            desc = (
                c.get("description")
                if isinstance(c, dict)
                else getattr(c, "description", None)
            )
            if nome and desc and str(nome).lower() not in out:
                out[str(nome).lower()] = str(desc)
    return out


def escrever_unidade(unidade: str, lingua: str) -> str:
    if unidade == "un":
        return _PALAVRA_UNIDADES.get(lingua, "units")
    return unidade


def regras_de_numeros(
    lingua: str,
    colunas: Optional[Iterable[str]] = None,
    moeda_pedida: Optional[str] = None,
    unidades: Optional[Dict[str, str]] = None,
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

    linhas += [
        "- UNITS: every number that measures something carries its unit (s, min,",
        "  h, km, l, %, units), taken from the column it comes from — and so do",
        "  differences, averages and totals of that column. A bare '36,81' is wrong.",
    ]
    for coluna, unidade in list((unidades or {}).items())[:12]:
        escrita = escrever_unidade(unidade, lingua)
        exemplo_u = "36,81" if lingua in ("pt", "es") else "36.81"
        linhas.append(f"  * {coluna} is in {escrita}: write «{exemplo_u} {escrita}»")

    return "\n".join(linhas) + "\n"


# ── A correcção depois do modelo ─────────────────────────────────────────

_ESPACOS = " \u00a0\u202f\u2009"

#: O espaço que o modelo põe entre o número e a moeda. Qualquer um destes
#: (espaço normal, inseparável, inseparável estreito, fino): o gpt-oss escreve
#: «1,90\u202f€» à francesa, e um marcador que a expressão não reconhecia
#: ficava DEPOIS do «€» que a correcção acrescentava — «1,90 € €» (11/10).
_ESP = f"[{_ESPACOS}]"
#: Um ou mais marcadores de moeda seguidos: «€», «EUR», «euro(s)». Engolidos
#: TODOS de uma vez — a correcção reescreve um só.
_MOEDA = r"(?:€|EUR\b|euros?\b)"

#: Um número escrito: agrupado (com espaço, ponto ou vírgula) ou corrido, com
#: decimais opcionais, e o marcador de moeda que o modelo lhe tenha colado.
#: Não pode estar agarrado a uma palavra, a uma data (``2026-08-01``), a uma
#: hora (``12:30``) nem a outro número.
_NUMERO = re.compile(
    rf"(?P<pre>(?:(?:€|\bEUR){_ESP}?)+)?"
    r"(?<![\w.,\-/:])"
    rf"(?P<n>\d{{1,3}}(?:[{_ESPACOS}.,]\d{{3}})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"(?![\w\-/:]|[.,]\d)"
    rf"(?P<pos>(?:{_ESP}?{_MOEDA})+)?",
    re.IGNORECASE,
)

#: A rede final: dois marcadores de moeda seguidos nunca são o que se quer
#: dizer («1,90 € €», «1,90 EUR €», «€ €1,90»). Fica um «€».
_MOEDA_REPETIDA = re.compile(
    rf"€(?:{_ESP}*{_MOEDA})+|(?:EUR\b|euros?\b){_ESP}*€", re.IGNORECASE
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


def valores_por_litro(
    linhas: Optional[Sequence[Dict[str, Any]]],
) -> List[float]:
    """Os valores (e média/mínimo/máximo) das colunas de preço por litro."""
    out: List[float] = []
    if not linhas or not isinstance(linhas[0], dict):
        return out
    for c in list(linhas[0].keys()):
        if not e_preco_por_litro(c):
            continue
        vals = [
            v
            for v in (_numero(r.get(c)) for r in linhas if isinstance(r, dict))
            if v is not None
        ]
        out += vals
        if len(vals) > 1:
            out += [sum(vals) / len(vals), min(vals), max(vals)]
    return out


def valores_com_unidade(
    linhas: Optional[Sequence[Dict[str, Any]]],
    unidades: Optional[Dict[str, str]],
) -> Tuple[List[Tuple[float, str]], List[float]]:
    """([(valor, unidade)], [valores sem unidade]) do resultado.

    Cada coluna com unidade dá os seus valores e os que o modelo costuma
    escrever a partir deles: soma, média, mínimo, máximo e as diferenças
    máximo−mínimo, máximo−média e média−mínimo («la mayor diferencia…»,
    «aproximar el peor a la media…»). Uma percentagem guardada como fracção
    (todos os valores ≤ 1) não leva «%»: 0,75 não é 0,75 %.
    """
    com: List[Tuple[float, str]] = []
    sem: List[float] = []
    if not linhas or not isinstance(linhas[0], dict):
        return com, sem
    for c in list(linhas[0].keys()):
        if _e_identificador(c) or e_dinheiro(c):
            continue
        vals = [
            v
            for v in (_numero(r.get(c)) for r in linhas if isinstance(r, dict))
            if v is not None
        ]
        if not vals:
            continue
        u = (unidades or {}).get(c)
        if u == "%" and max(abs(v) for v in vals) <= 1:
            u = None
        if not u:
            sem += vals
            continue
        derivados = list(vals)
        if len(vals) > 1:
            media = sum(vals) / len(vals)
            mx, mn = max(vals), min(vals)
            derivados += [sum(vals), media, mn, mx, mx - mn, mx - media, media - mn]
        com += [(v, u) for v in derivados]
    return com, sem


#: Palavras que, escritas logo a seguir ao número, já são a unidade.
_JA_TEM_UNIDADE = re.compile(
    r"^[" + _ESPACOS + r"]*(?:%|/|"
    r"(?:s|seg|segs|segundos?|seconds?|secs?|ms|milisegundos?|milliseconds?"
    r"|min|mins|minutos?|minutes?|h|hrs?|horas?|hours?"
    r"|km|kms|k[iu]l[oó]metros?|quil[oó]metros?|kilomet(?:er|re)s?"
    r"|l|lt|lts|litros?|lit(?:er|re)s?|kg|kgs|kilos?|quilos?"
    r"|unidades?|units?|uds?|por\s+ciento|percent|€|eur|euros?)\b)",
    re.IGNORECASE,
)

#: Palavras que podem vir a seguir a «36,81 s» sem a unidade estar a mais
#: («… de 36,81 s en el canal drive»). Um substantivo a seguir («las 5
#: gasolineras») quer dizer que o número conta outra coisa: não se mexe.
_DEPOIS_DA_UNIDADE = {
    "en", "y", "e", "o", "u", "de", "del", "da", "do", "das", "dos", "con",
    "com", "sin", "sem", "para", "por", "que", "frente", "contra", "respecto",
    "comparado", "comparada", "versus", "vs", "mas", "más", "menos", "mientras",
    "enquanto", "pero", "and", "or", "in", "on", "at", "for", "with", "of",
    "than", "while", "but", "a", "al", "ao", "la", "el", "los", "las", "the",
    "lo", "le", "les", "se", "is", "es", "é", "son", "sao", "são", "are",
}  # fmt: skip


def _sufixo_de_unidade(texto: str, fim: int, unidade: str, lingua: str) -> str:
    """« s» se a unidade cabe logo a seguir ao número; "" se já lá está ou
    se o que vem a seguir mostra que o número é outra coisa."""
    resto = texto[fim:]
    if _JA_TEM_UNIDADE.match(resto):
        return ""
    # «36,81 %» em pt/es (com espaço, como manda a norma); «36.81%» em inglês.
    sep = "" if unidade == "%" and lingua == "en" else " "
    if resto == "" or resto[0] in ".,;:!?)":
        return sep + escrever_unidade(unidade, lingua)
    m = re.match(r"^[" + _ESPACOS + r"]+([^\W\d_]+)\b", resto)
    if m and m.group(1).lower() in _DEPOIS_DA_UNIDADE:
        return sep + escrever_unidade(unidade, lingua)
    return ""


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


#: «Usted puede observar que el precio medio… es de 1,90 €» (11/10/2026): o
#: modelo anuncia o facto em vez de o dizer. Corta-se o anúncio no início de
#: uma frase e a frase começa pelo facto: «El precio medio… es de 1,90 €».
_ANUNCIO = re.compile(
    _INICIO + r"(?:"
    # es
    r"(?:como\s+)?(?:usted\s+)?puede\s+(?:observar|ver|notar|apreciar|comprobar)\s*,\s*"
    r"|(?:usted\s+)?puede\s+(?:observar|ver|notar|apreciar|comprobar)\s+que\s+"
    r"|se\s+puede\s+(?:observar|ver|apreciar|comprobar)\s+que\s+"
    r"|podemos\s+(?:observar|ver|notar|apreciar)\s+que\s+"
    # pt
    r"|(?:como\s+)?(?:voc[eê]\s+|o\s+senhor\s+)?pode\s+(?:observar|ver|notar|verificar|constatar)\s*,\s*"
    r"|(?:voc[eê]\s+|o\s+senhor\s+)?pode\s+(?:observar|ver|notar|verificar|constatar)\s+que\s+"
    r"|pode-se\s+(?:observar|ver|notar|verificar|constatar)\s+que\s+"
    r"|[ée]\s+poss[ií]vel\s+(?:observar|ver|notar|verificar|constatar)\s+que\s+"
    r"|podemos\s+(?:observar|ver|notar|verificar|constatar)\s+que\s+"
    # en
    r"|as\s+you\s+can\s+see\s*,\s*"
    r"|(?:you|we)\s+can\s+(?:see|observe|notice)\s+that\s+"
    r"|it\s+can\s+be\s+(?:seen|observed)\s+that\s+"
    r")(?=\w)(\w)",
    re.IGNORECASE,
)


def sem_anuncio(texto: str) -> str:
    """Tira «Usted puede observar que» / «Pode observar que» / «You can see
    that» do início das frases; a frase passa a começar pelo facto."""
    return _ANUNCIO.sub(lambda m: m.group(1) + m.group(2).upper(), texto)


def falar_com_quem_pergunta(texto: str) -> str:
    """Troca «El usuario ha facturado» por «Ha facturado» (e o mesmo em pt/en)
    e corta o anúncio («Usted puede observar que…») antes do facto."""
    texto = sem_anuncio(texto)
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
    unidades: Optional[Dict[str, str]] = None,
) -> str:
    """Reescreve os números da resposta no formato de quem lê. Ver o topo.

    ``unidades`` (``{coluna: unidade}``, ver ``unidades_do_resultado``): um
    número que é valor (ou soma/média/diferença) de uma coluna com unidade
    leva-a — «36,81» de ``service_sec`` sai «36,81 s»."""
    if not texto:
        return texto
    lingua = (lingua or "en").split("-")[0].lower()
    dinheiro, outros = valores_do_resultado(linhas)
    com_unidade, sem_unidade = valores_com_unidade(linhas, unidades)

    def unidade_de(r: float) -> Optional[str]:
        achadas = {u for v, u in com_unidade if _igual(r, v)}
        if len(achadas) != 1:
            return None
        # Também é valor de uma coluna sem unidade (uma contagem com o mesmo
        # número, por exemplo): ambíguo, não se acrescenta nada.
        if any(_igual(r, v) for v in sem_unidade) or any(
            _igual(r, v) for v in dinheiro
        ):
            return None
        return achadas.pop()

    moeda = (moeda_pedida or MOEDA_POR_LINGUA.get(lingua, "EUR")).upper()
    simbolo = SIMBOLO.get(moeda, moeda)
    por_litro = valores_por_litro(linhas)

    def dinheiro_de(v: float, m: "re.Match[str]") -> str:
        escrito = formatar_valor(v, lingua, True, simbolo)
        # «1,90 €/l» só quando a COLUNA o diz e o modelo não escreveu já a
        # unidade. Decide-se pelo carácter logo a seguir: pontuação ou fim
        # acrescentam «/l»; um espaço ou «/» deixam como está («1,90 € por
        # litro», «1,90 €/l»). O streaming nunca corta logo a seguir a um
        # número com moeda, por isso decide o mesmo que o texto inteiro.
        if lingua in ("pt", "es") and any(_igual(v, x) for x in por_litro):
            seguinte = texto[m.end() : m.end() + 1]
            if seguinte == "" or seguinte in ".,;:!?)":
                escrito += "/l"
        return escrito

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
                    return dinheiro_de(v, m)
        if not tem_moeda and com_unidade:
            for r in leituras:
                u = unidade_de(r)
                if u:
                    return formatar_valor(r, lingua) + _sufixo_de_unidade(
                        texto, m.end(), u, lingua
                    )
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

    return _MOEDA_REPETIDA.sub("€", _NUMERO.sub(trocar, texto))


def corrigir_resposta(
    texto: str,
    lingua: str,
    linhas: Optional[Sequence[Dict[str, Any]]] = None,
    moeda_pedida: Optional[str] = None,
    sql: Optional[str] = None,
    descricoes: Optional[Dict[str, str]] = None,
    pergunta: Optional[str] = None,
    unidades: Optional[Dict[str, str]] = None,
) -> str:
    """A resposta final: na segunda pessoa, entidades pelo nome e não pelo
    id, nomes próprios copiados dos dados, e números à maneira de quem lê,
    com moeda e unidade."""
    if not texto:
        return texto
    from core.llm.nomes import corrigir_nomes, nomear_ids

    if unidades is None:
        colunas = (
            list(linhas[0].keys()) if linhas and isinstance(linhas[0], dict) else []
        )
        unidades = unidades_do_resultado(colunas, sql, descricoes)
    texto = falar_com_quem_pergunta(texto)
    texto = nomear_ids(texto, linhas)
    texto = corrigir_nomes(texto, linhas, pergunta)
    return corrigir_numeros(texto, lingua, linhas, moeda_pedida, unidades)


#: O fim do texto que ainda pode ser metade de um número («6 153») ou de um
#: marcador de moeda («6.153,72 eu…»). Fica retido até chegar o resto.
_CAUDA_INCERTA = re.compile(r"[\d.,€" + _ESPACOS + r"EeUuRrOoSs]*$")
#: Uma frase com menos do que isto ainda pode ser «El usuario ha…» ou
#: «Como usted puede observar, …» (o anúncio mais comprido tem 33).
_INICIO_DE_FRASE = 40

#: Caudas retidas no streaming (ver ``CorrecaoEmFluxo._corte``).
_RETER = [
    # uma palavra ainda a meio
    re.compile(r"(?<![\w'-])[^\W\d_][\w'-]*$"),
    # «con el id 16», «(ID: », «id» — vai ser trocado pelo rótulo
    re.compile(
        r"(?:\b(?:con|com|with)\s+(?:(?:el|la|o|a|the)\s+)?)?[  ]?\(?\s*"
        r"\b(?:id|ideess|identificador|identifier)\s*"
        r"(?:n\.?\s*[ºo°]\.?\s*|#|:|=)?\s*\d*$",
        re.IGNORECASE,
    ),
    # «con», «con el» — pode vir «id» a seguir
    re.compile(r"\b(?:con|com|with)(?:\s+(?:el|la|o|a|the))?\s*$", re.IGNORECASE),
    # número + palavra a seguir ainda incompleta (decide a unidade)
    re.compile(rf"(?<![\w.,])\d[\d.,{_ESPACOS}]*[{_ESPACOS}]+[^\W\d_]*$"),
]


class CorrecaoEmFluxo:
    """A mesma correcção, pedaço a pedaço, para o caminho em streaming.

    O protocolo só tem ``chunk`` — não há «substituir o que já foi» — e a voz
    lê os mesmos pedaços, por isso o que sai tem de já ir certo. Retém-se só
    a cauda que ainda pode mudar (um número a meio, um início de frase).
    """

    def __init__(
        self,
        lingua: str,
        linhas=None,
        moeda_pedida: Optional[str] = None,
        sql: Optional[str] = None,
        descricoes: Optional[Dict[str, str]] = None,
        pergunta: Optional[str] = None,
    ) -> None:
        self.lingua = lingua
        self.linhas = linhas
        self.moeda_pedida = moeda_pedida
        self.pergunta = pergunta
        colunas = (
            list(linhas[0].keys()) if linhas and isinstance(linhas[0], dict) else []
        )
        # Calculadas uma vez: o SQL não muda a meio da resposta.
        self.unidades = unidades_do_resultado(colunas, sql, descricoes)
        self.bruto = ""
        self.enviado = ""

    def _processar(self, texto: str) -> str:
        return corrigir_resposta(
            texto,
            self.lingua,
            self.linhas,
            self.moeda_pedida,
            pergunta=self.pergunta,
            unidades=self.unidades,
        )

    def _corte(self) -> int:
        corte = len(self.bruto) - len(_CAUDA_INCERTA.search(self.bruto).group(0))
        inicio = 0
        for m in re.finditer(r"[.!?]\s+", self.bruto):
            inicio = m.end()
        if len(self.bruto) - inicio < _INICIO_DE_FRASE:
            corte = min(corte, inicio)
        # O que ainda pode mudar com o pedaço seguinte: uma palavra a meio
        # (um nome por corrigir), «id 1644…» (vai ser o rótulo) e a palavra
        # depois de um número (decide se leva unidade).
        for padrao in _RETER:
            m = padrao.search(self.bruto)
            if m:
                corte = min(corte, m.start())
        # Nunca cortar a meio de uma palavra («Mostole|s.»): a palavra
        # cortada parecia outro nome e era «corrigida».
        while (
            0 < corte < len(self.bruto)
            and self.bruto[corte - 1].isalpha()
            and self.bruto[corte].isalpha()
        ):
            corte -= 1
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
