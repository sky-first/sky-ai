"""Rede de segurança: 0 linhas por um literal com gralha.

Produção, 11/10/2026: ``WHERE UPPER(gr.origem) = 'BAJAZOZ'`` — o modelo
escreveu a cidade em vez de a copiar, a consulta devolveu 0 linhas e a
resposta parecia uma recusa. Mesmo com os valores no prompt
(``valores_de_coluna``), um modelo pequeno pode voltar a escrever à mão.

Quando uma consulta devolve 0 linhas, cada filtro de texto
(``col = 'x'``, ``col IN (...)``, ``col LIKE/ILIKE '%x%'``, com ou sem
UPPER/LOWER/TRIM à volta da coluna) é comparado com os valores que a coluna
REALMENTE tem (``SELECT DISTINCT … LIMIT``). Se o literal não existe e há UM
candidato claramente melhor (comparação sem maiúsculas nem acentos), troca-se
o literal e corre-se outra vez — uma vez. Nunca quando é ambíguo, nunca numa
coluna de cardinalidade alta (o domínio lido estaria incompleto) e nunca
quando há filtros de linha (RLS): os valores viriam de linhas que a pessoa
não pode ver.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from core.logging_utils import log_event
from core.sql.valores_de_coluna import e_coluna_de_texto, valores_distintos

# Limiar e margem do «candidato claro». BAJAZOZ→BADAJOZ dá 0,71 (duas trocas
# em sete letras); a margem exige que o segundo melhor fique bem atrás.
LIMIAR = 0.7
MARGEM = 0.2
MIN_LETRAS = 4
# Domínio lido por coluna. Acima disto o domínio está incompleto e uma
# «melhor correspondência» não prova nada.
MAX_DOMINIO = 500
# Colunas consultadas por correcção (custo limitado).
MAX_COLUNAS = 6


def normalizar(texto: str) -> str:
    """Sem acentos, sem maiúsculas, espaços colapsados."""
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip().casefold()


def semelhanca(a: str, b: str) -> float:
    """Máximo entre o rácio do difflib e a semelhança de Levenshtein,
    ambos sobre a forma normalizada."""
    na, nb = normalizar(a), normalizar(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ratio = difflib.SequenceMatcher(None, na, nb).ratio()
    return max(ratio, 1.0 - _levenshtein(na, nb) / max(len(na), len(nb)))


def _levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    anterior = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        actual = [i]
        for j, cb in enumerate(b, 1):
            actual.append(
                min(anterior[j] + 1, actual[j - 1] + 1, anterior[j - 1] + (ca != cb))
            )
        anterior = actual
    return anterior[-1]


def melhor_candidato(literal: str, valores: Sequence[str]) -> Optional[str]:
    """O único valor claramente mais próximo, ou None se não houver ou se for
    ambíguo (dois acima do limiar sem margem, ou dois iguais normalizados)."""
    if len(normalizar(literal)) < MIN_LETRAS:
        return None
    pontuados = sorted(
        ((semelhanca(literal, v), v) for v in valores if v is not None),
        key=lambda p: p[0],
        reverse=True,
    )
    if not pontuados or pontuados[0][0] < LIMIAR:
        return None
    melhor, valor = pontuados[0]
    if len(pontuados) > 1:
        segundo, outro = pontuados[1]
        if normalizar(outro) == normalizar(valor) and outro != valor:
            return None  # «Mérida» e «MERIDA»: não há forma de escolher
        if melhor - segundo < MARGEM:
            return None
    return valor


# ── Leitura dos filtros ────────────────────────────────────────────────


@dataclass
class Filtro:
    tabela: str  # nome físico
    coluna: str
    literal: str  # como está no SQL (sem aspas)
    caixa: str  # "upper" | "lower" | ""
    operador: str  # "eq" | "like" | "ilike"
    texto_sql: str = ""  # literal com aspas, como aparece no SQL


@dataclass
class Correccao:
    sql: str
    trocas: List[Dict[str, str]] = field(default_factory=list)


def _fisica_da_tabela(t: Any) -> str:
    partes = [p for p in (t.args.get("catalog"), t.args.get("db")) if p is not None]
    nomes = [getattr(p, "name", str(p)) for p in partes] + [t.name]
    return ".".join(n for n in nomes if n)


def _resolver_tabela(fisica_sql: str, esquemas: Dict[str, Any]) -> Optional[Any]:
    alvo = fisica_sql.lower().replace('"', "").replace("`", "")
    if alvo in esquemas:
        return esquemas[alvo]
    curto = alvo.split(".")[-1]
    candidatos = [t for k, t in esquemas.items() if k.split(".")[-1] == curto]
    return candidatos[0] if len(candidatos) == 1 else None


def _colunas_de(tabela: Any) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for c in getattr(tabela, "columns", None) or []:
        nome = c.get("name") if isinstance(c, dict) else getattr(c, "name", None)
        tipo = (
            (c.get("type") or c.get("data_type") or "")
            if isinstance(c, dict)
            else (getattr(c, "type", "") or "")
        )
        if nome:
            out[str(nome).lower()] = tipo
    return out


def _desembrulhar(expr: Any) -> Tuple[Any, str]:
    """UPPER/LOWER/TRIM/UNACCENT/CAST à volta da coluna → (coluna, caixa)."""
    from sqlglot import exp

    caixa = ""
    actual = expr
    for _ in range(5):
        if isinstance(actual, exp.Upper):
            caixa = caixa or "upper"
            actual = actual.this
        elif isinstance(actual, exp.Lower):
            caixa = caixa or "lower"
            actual = actual.this
        elif isinstance(actual, (exp.Trim, exp.Cast, exp.Paren)):
            actual = actual.this
        elif isinstance(actual, exp.Anonymous) and str(actual.name).lower() in (
            "unaccent",
            "btrim",
            "initcap",
        ):
            actual = actual.expressions[0] if actual.expressions else None
        else:
            break
        if actual is None:
            break
    return actual, caixa


def _por_ordem(arvore: Any) -> List[Any]:
    """Comparações de texto pela ordem em que aparecem no SQL (o
    ``find_all`` do sqlglot percorre em largura)."""
    from sqlglot import exp

    return [
        no
        for no in arvore.walk(bfs=False)
        if isinstance(no, (exp.EQ, exp.Like, exp.ILike, exp.In))
    ]


def ler_filtros(sql: str, dialecto: str, tabelas: Iterable[Any]) -> List[Filtro]:
    """Filtros de igualdade/LIKE/ILIKE/IN entre uma coluna de TEXTO de uma
    tabela conhecida e um literal. O que não se percebe fica de fora."""
    import sqlglot
    from sqlglot import exp

    esquemas = {
        str(t.physical_name).lower(): t
        for t in tabelas or []
        if getattr(t, "physical_name", None)
    }
    try:
        arvore = sqlglot.parse_one(sql, read=dialecto or None)
    except Exception:
        return []
    if arvore is None:
        return []

    ctes = {c.alias_or_name.lower() for c in arvore.find_all(exp.CTE)}
    alias: Dict[str, Any] = {}
    nas_consulta: List[Any] = []
    for t in arvore.find_all(exp.Table):
        if t.name.lower() in ctes:
            continue
        esquema = _resolver_tabela(_fisica_da_tabela(t), esquemas)
        if esquema is None:
            continue
        nas_consulta.append(esquema)
        alias[(t.alias or t.name).lower()] = esquema
        alias[t.name.lower()] = esquema

    def tabela_da_coluna(col: Any) -> Optional[Any]:
        qual = (col.table or "").lower()
        nome = col.name.lower()
        if qual:
            t = alias.get(qual)
            return t if t is not None and nome in _colunas_de(t) else None
        donas = {id(t): t for t in nas_consulta if nome in _colunas_de(t)}
        return next(iter(donas.values())) if len(donas) == 1 else None

    filtros: List[Filtro] = []

    def registar(lado_col: Any, literal: Any, operador: str) -> None:
        if not isinstance(literal, exp.Literal) or not literal.is_string:
            return
        col, caixa = _desembrulhar(lado_col)
        if not isinstance(col, exp.Column):
            return
        tabela = tabela_da_coluna(col)
        if tabela is None:
            return
        tipo = _colunas_de(tabela).get(col.name.lower(), "")
        if not e_coluna_de_texto(tipo):
            return
        filtros.append(
            Filtro(
                tabela=str(tabela.physical_name),
                coluna=col.name,
                literal=literal.this,
                caixa=caixa,
                operador=operador,
                texto_sql=literal.sql(),
            )
        )

    for no in _por_ordem(arvore):
        operador = (
            "eq"
            if isinstance(no, (exp.EQ, exp.In))
            else "ilike" if isinstance(no, exp.ILike) else "like"
        )
        if isinstance(no, exp.In):
            for item in no.expressions:
                registar(no.this, item, "eq")
            continue
        esq, dir_ = no.this, no.expression
        if isinstance(esq, exp.Literal):
            esq, dir_ = dir_, esq
        registar(esq, dir_, operador)
    return filtros


# ── Correspondência ───────────────────────────────────────────────────


def _nucleo_like(literal: str) -> Optional[Tuple[str, str, str]]:
    """'%x%' → ('%', 'x', '%'). None se houver curingas no meio."""
    m = re.match(r"^(%?)(.*?)(%?)$", literal, re.S)
    if not m:
        return None
    pre, nucleo, pos = m.groups()
    if "%" in nucleo or "_" in nucleo or not nucleo.strip():
        return None
    return pre, nucleo, pos


def _aplica_caixa(valor: str, caixa: str) -> str:
    if caixa == "upper":
        return valor.upper()
    if caixa == "lower":
        return valor.lower()
    return valor


def _like_casa(pre: str, nucleo: str, pos: str, valor: str, sem_caixa: bool) -> bool:
    v, n = (valor.casefold(), nucleo.casefold()) if sem_caixa else (valor, nucleo)
    if pre and pos:
        return n in v
    if pre:
        return v.endswith(n)
    if pos:
        return v.startswith(n)
    return v == n


def _corrigir_um(f: Filtro, valores: Sequence[str]) -> Optional[str]:
    """Novo literal (sem aspas) para o filtro, ou None (já existe, ou não há
    candidato claro)."""
    if f.operador == "eq":
        if any(_aplica_caixa(v, f.caixa) == f.literal for v in valores):
            return None
        alvo = melhor_candidato(f.literal, valores)
        return _aplica_caixa(alvo, f.caixa) if alvo is not None else None

    partes = _nucleo_like(f.literal)
    if partes is None:
        return None
    pre, nucleo, pos = partes
    sem_caixa = f.operador == "ilike"
    if any(
        _like_casa(pre, nucleo, pos, _aplica_caixa(v, f.caixa), sem_caixa)
        for v in valores
    ):
        return None
    # Com curingas, o núcleo pode ser uma palavra do valor («%bajazoz%» em
    # «Badajoz centro»): compara-se com o valor e com cada palavra.
    pecas: List[str] = []
    for v in valores:
        pecas.append(v)
        if pre or pos:
            pecas.extend(p for p in re.split(r"[\s\-/,]+", v) if p)
    unicas = list(dict.fromkeys(pecas))
    alvo = melhor_candidato(nucleo, unicas)
    if alvo is None:
        return None
    return f"{pre}{_aplica_caixa(alvo, f.caixa)}{pos}"


def _citar(valor: str) -> str:
    return "'" + valor.replace("'", "''") + "'"


def corrigir_literais(
    sql: str,
    dialecto: str,
    tabelas: Iterable[Any],
    data_source: Any,
) -> Optional[Correccao]:
    """SQL com os literais corrigidos, ou None se não há nada claro a corrigir.

    Só faz ``SELECT DISTINCT`` limitados (no máximo ``MAX_COLUNAS``). Não
    executa a consulta corrigida — isso é de quem chama, uma vez.
    """
    tabelas = list(tabelas or [])
    filtros = ler_filtros(sql, dialecto, tabelas)
    if not filtros:
        return None

    dominios: Dict[Tuple[str, str], Optional[List[str]]] = {}
    novos: Dict[str, Optional[str]] = {}  # texto_sql → novo literal (None = conflito)
    trocas: List[Dict[str, str]] = []

    for f in filtros:
        chave = (f.tabela, f.coluna.lower())
        if chave not in dominios:
            if len(dominios) >= MAX_COLUNAS:
                continue
            try:
                vals = valores_distintos(data_source, f.tabela, f.coluna, MAX_DOMINIO)
            except Exception as exc:
                log_event(
                    "literal_fix_domain_error",
                    {"table": f.tabela, "column": f.coluna, "error": str(exc)[:160]},
                )
                vals = None
            # Domínio incompleto (cardinalidade alta) → não se decide nada.
            dominios[chave] = vals if vals and len(vals) <= MAX_DOMINIO else None
        valores = dominios[chave]
        if not valores:
            continue
        novo = _corrigir_um(f, valores)
        if novo is None or novo == f.literal:
            continue
        anterior = novos.get(f.texto_sql, novo)
        if f.texto_sql in novos and anterior != novo:
            novos[f.texto_sql] = None  # o mesmo literal pedia duas trocas
            continue
        novos[f.texto_sql] = novo
        trocas.append(
            {
                "table": f.tabela,
                "column": f.coluna,
                "from": f.literal,
                "to": novo,
                "_texto": f.texto_sql,
            }
        )

    aplicar = {k: v for k, v in novos.items() if v is not None}
    if not aplicar:
        return None
    novo_sql = sql
    for texto, valor in aplicar.items():
        if texto not in novo_sql:
            return None
        novo_sql = novo_sql.replace(texto, _citar(valor))
    trocas = [
        {k: v for k, v in t.items() if k != "_texto"}
        for t in trocas
        if t["_texto"] in aplicar
    ]
    return Correccao(sql=novo_sql, trocas=trocas)


# ── Para a resposta «não há resultados» ───────────────────────────────


def descrever_filtros(
    sql: Optional[str], dialecto: str = "postgres"
) -> List[Tuple[str, str]]:
    """Pares (coluna, valor) dos filtros de texto do SQL, sem precisar do
    esquema — para dizer à pessoa O QUE não encontrou."""
    if not sql:
        return []
    try:
        import sqlglot
        from sqlglot import exp

        arvore = sqlglot.parse_one(sql, read=dialecto or None)
    except Exception:
        return []
    pares: List[Tuple[str, str]] = []
    for no in _por_ordem(arvore):
        itens = (
            [(no.this, i) for i in no.expressions]
            if isinstance(no, exp.In)
            else [(no.this, no.expression)]
        )
        for esq, dir_ in itens:
            if isinstance(esq, exp.Literal):
                esq, dir_ = dir_, esq
            if not (isinstance(dir_, exp.Literal) and dir_.is_string):
                continue
            col, _ = _desembrulhar(esq)
            if not isinstance(col, exp.Column):
                continue
            valor = dir_.this.strip("%").strip()
            if valor and (col.name, valor) not in pares:
                pares.append((col.name, valor))
    return pares[:4]
