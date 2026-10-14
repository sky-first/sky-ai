# -*- coding: utf-8 -*-
"""Que tabelas FÍSICAS um SQL lê — pela árvore do sqlglot, não por regex.

Produção, 14/10/2026 (sandbox, fatia ``products`` da Cocina): o modelo
escreveu o SQL e, a seguir, uma frase («...the join step matches them...»).
O validador procurava tabelas com ``FROM|JOIN <identificador>`` no texto
inteiro e leu «join step» como a tabela ``step`` → «Table 'step' is not
allowed» → fatia perdida.

A regex tinha ainda o defeito contrário, mais grave: só olhava para o nível de
topo quando lá havia alguma tabela, por isso uma tabela não autorizada dentro
de um CTE ou de uma subconsulta nunca era verificada (``WITH x AS (SELECT ...
FROM hr.salaries) SELECT ... FROM x`` passava).

Aqui:

- ``tabelas_fisicas`` percorre TODAS as referências a tabelas da árvore (CTEs,
  subconsultas, JOINs) e tira só as que são o nome de um CTE visível naquele
  ponto (sem qualificação de schema, e só dentro do âmbito do ``WITH`` que o
  define). Comentários e literais não são tabelas. Devolve ``None`` quando o
  sqlglot não percebe o SQL — o chamador decide o que fazer (o validador volta
  à regex, mais estrita).
- ``cortar_prosa_final`` tira a prosa que o modelo escreve DEPOIS do SQL, só
  quando o SQL inteiro não é interpretável e o que fica é; e só se o que sai
  for prosa (nunca uma cláusula SQL estragada: deitá-la fora daria outra
  consulta, que corria e devolvia números errados).
"""

from __future__ import annotations

import re
from typing import Optional, Set

import sqlglot
from sqlglot import exp

from core.logging_utils import log_event


def dialecto_sqlglot(dialecto: Optional[str]) -> Optional[str]:
    from core.sql.semantic_checks import _dialect_for

    return _dialect_for(dialecto)


def _arvore(sql: str, dialecto: Optional[str]):
    """A árvore de UMA instrução, ou ``None`` (não percebida / várias)."""
    try:
        arvores = [a for a in sqlglot.parse(sql, read=dialecto_sqlglot(dialecto)) if a]
    except Exception:
        return None
    if len(arvores) != 1:
        return None
    return arvores[0]


def _ctes_de(no: exp.Expression) -> Set[str]:
    w = no.args.get("with_") or no.args.get("with")
    if not isinstance(w, exp.With):
        return set()
    return {(c.alias_or_name or "").lower() for c in w.expressions}


def _e_cte_visivel(tabela: exp.Table) -> bool:
    """O nome não qualificado é um CTE definido num ``WITH`` que o envolve?"""
    if tabela.args.get("db") or tabela.args.get("catalog"):
        return False  # «private.secret» é sempre a tabela física
    nome = (tabela.name or "").lower()
    pai = tabela.parent
    while pai is not None:
        if nome in _ctes_de(pai):
            return True
        pai = pai.parent
    return False


def tabelas_fisicas(sql: str, dialecto: Optional[str]) -> Optional[Set[str]]:
    """Nomes (``catalog.db.tabela`` / ``db.tabela`` / ``tabela``) das tabelas
    físicas que o SQL lê, ou ``None`` se o sqlglot não o interpreta."""
    arvore = _arvore(sql, dialecto)
    if arvore is None:
        return None
    out: Set[str] = set()
    for t in arvore.find_all(exp.Table):
        # Funções na posição de tabela (generate_series, unnest...): como a
        # regex de sempre, não são tabelas.
        if not isinstance(t.this, exp.Identifier) or not t.name:
            continue
        if _e_cte_visivel(t):
            continue
        out.add(".".join(p for p in (t.catalog, t.db, t.name) if p))
    return out


# ── prosa depois do SQL ───────────────────────────────────────────────────

# Palavras com que uma linha de SQL pode começar. Uma linha que comece por
# uma delas nunca é tratada como prosa.
_PALAVRAS_SQL = {
    "select",
    "with",
    "from",
    "where",
    "and",
    "or",
    "not",
    "group",
    "order",
    "having",
    "limit",
    "offset",
    "fetch",
    "union",
    "intersect",
    "except",
    "join",
    "inner",
    "left",
    "right",
    "full",
    "cross",
    "natural",
    "lateral",
    "on",
    "using",
    "as",
    "case",
    "when",
    "then",
    "else",
    "end",
    "window",
    "partition",
    "over",
    "qualify",
    "values",
    "in",
    "exists",
    "between",
    "like",
    "ilike",
    "is",
    "null",
    "distinct",
    "by",
    "asc",
    "desc",
    "nulls",
    "all",
    "any",
    "some",
    "filter",
    "within",
    "rows",
    "range",
    "returning",
}

_RE_MARCA = re.compile(r"^\s*(?:[*#>]+|\d+[.)])\s*")
_RE_PALAVRA = re.compile(r"^([^\W\d_]+)(?=[\s:,.!?]|$)", re.UNICODE)


def _e_prosa(linha: str) -> bool:
    s = linha.strip()
    if not s or s.startswith("--"):
        return False
    marcada = bool(_RE_MARCA.match(s))
    s = _RE_MARCA.sub("", s)
    m = _RE_PALAVRA.match(s)
    if not m or m.group(1).lower() in _PALAVRAS_SQL:
        return False
    palavras = re.findall(r"[^\W\d_]{2,}", s, re.UNICODE)
    return marcada or s.endswith(":") or len(palavras) >= 3


def cortar_prosa_final(sql: str, dialecto: Optional[str]) -> str:
    """O SQL sem a prosa que o modelo escreveu a seguir (ver o topo)."""
    if not sql or _arvore(sql, dialecto) is not None:
        return sql
    linhas = sql.splitlines()
    for i in range(1, len(linhas)):
        if not _e_prosa(linhas[i]):
            continue
        resto = linhas[i:]
        # Nada do que sai pode começar como uma cláusula SQL.
        if any(
            (_RE_PALAVRA.match(_RE_MARCA.sub("", r.strip())) or [None, ""])[1].lower()
            in _PALAVRAS_SQL
            for r in resto
            if r.strip() and not r.strip().startswith("--")
        ):
            return sql
        cabeca = "\n".join(linhas[:i]).rstrip().rstrip(";").rstrip()
        if cabeca and _arvore(cabeca, dialecto) is not None:
            log_event(
                "sql_prosa_final_cortada",
                {"linhas_cortadas": len(resto), "inicio": linhas[i].strip()[:60]},
            )
            return cabeca
        return sql
    return sql
