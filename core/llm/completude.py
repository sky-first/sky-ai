"""O resultado está completo — e os nomes estão nele.

Produção, 12/10/2026, tenant skyfirstlabs, ligação «Operaciones» (``ops``):
«Lista las 5 gasolineras con el gasóleo A más barato en la tabla
gasolineras_rota para la ruta Badajoz-Madrid». As 5 linhas traziam ``rotulo``
e ``localidad`` (BALLENOIL / PETROPRIX, Móstoles, Mérida, Esparragalejo). A
resposta começava «El precio más bajo … que aparece en la muestra…» e acabava
«No se pueden proporcionar los nombres completos de las cinco estaciones
solicitadas.» Duas mentiras com ar de prudência:

1. **«No se pueden proporcionar los nombres».** O prompt do formatador
   mandava «NEVER output raw data rows, lists of names» e «IF asked to 'list
   rows': REFUSE and provide ONLY aggregated insights». A pergunta dizia
   «Lista…»: o modelo obedeceu e, para justificar, inventou uma falta. Os
   nomes estavam nas colunas que ``core/sql/rotulos.py`` (#282) marca como
   [LABEL].

2. **«en la muestra».** O prompt chamava ao resultado «DATA PREVIEW» e
   «Sample of the data», e falava de resultados «limited to the top rows».
   Um top-5 PEDIDO pela pessoa não é uma amostra: é a resposta inteira.
   «Amostra» só quando o resultado tem mais linhas do que as mostradas (aí há
   o SAMPLE NOTICE de ``formatter._full_result_stats``).

As duas redes, como nos números: as regras no prompt (``regras_do_resultado``)
e a correcção determinística por cima (``corrigir_completude``), porque o
modelo nem sempre obedece.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from core.sql.rotulos import e_coluna_de_lugar, e_coluna_de_rotulo


def _colunas(linhas: Optional[Sequence[Dict[str, Any]]]) -> List[str]:
    out: List[str] = []
    for linha in (linhas or [])[:50]:
        if isinstance(linha, dict):
            for c in linha:
                if c not in out:
                    out.append(c)
    return out


def colunas_de_nome(linhas: Optional[Sequence[Dict[str, Any]]]) -> List[str]:
    """As colunas do RESULTADO que dão o nome (ou o lugar) de cada linha e
    trazem pelo menos um valor."""
    out = []
    for c in _colunas(linhas):
        if not (e_coluna_de_rotulo(c) or e_coluna_de_lugar(c)):
            continue
        if any(
            isinstance(l, dict) and isinstance(l.get(c), str) and l.get(c).strip()
            for l in linhas or []
        ):
            out.append(c)
    return out


def regras_do_resultado(
    linhas: Optional[Sequence[Dict[str, Any]]], mostradas: int
) -> str:
    """O bloco do prompt (em inglês, como o resto): completude e nomes."""
    total = len(linhas or [])
    if not total:
        return ""
    partes = []
    if total <= mostradas:
        partes.append(
            f"RESULT: the query returned {total} row(s) and ALL of them are shown. "
            "This is the COMPLETE answer to the question — a top-N or a list the "
            "person asked for is not a sample. Never call it a sample, 'muestra' "
            "or 'amostra', and never say the rows are partial."
        )
    nomes = colunas_de_nome(linhas)
    if nomes:
        partes.append(
            "NAMES ARE IN THE ROWS: the columns "
            + ", ".join(nomes)
            + " [LABEL] hold the name/place of each row. When the question asks to "
            "list, rank or name items, name EVERY returned row by them (e.g. "
            "'BALLENOIL (Móstoles), 1,69 €'). Never write that names, details or "
            "data are unavailable, missing or cannot be provided — they are right "
            "there."
        )
    return ("\n" + "\n".join(partes) + "\n") if partes else ""


# ── A correcção determinística ───────────────────────────────────────────

#: Frases que dizem que algo FALTA ou não se pode dar.
_FALTA = re.compile(
    r"\b(?:"
    # es
    r"no\s+(?:se\s+)?(?:puede[n]?|pude|podemos|es\s+posible)\s+(?:proporcionar|ofrecer|dar|indicar|mostrar|facilitar|identificar|listar)"
    r"|no\s+(?:est[aá]n?|figuran?|aparecen?|se\s+incluyen?|se\s+dispone|dispongo|tengo|tenemos|contamos)\b"
    r"|no\s+(?:hay|existen?)\s+(?:datos|informaci[oó]n|nombres?)\s+(?:sobre|de|del|de\s+los|de\s+las)"
    r"|(?:sin|falta[n]?)\s+(?:los\s+|las\s+)?(?:nombres?|datos|detalles)"
    # pt
    r"|n[aã]o\s+(?:[eé]\s+poss[ií]vel|consigo|conseguimos|posso|podemos|se\s+pode[m]?|pode[m]?)\s+(?:fornecer|indicar|dar|mostrar|apresentar|identificar|listar)"
    r"|n[aã]o\s+(?:est[aã]o?|constam?|aparecem?|figuram?|tenho|temos|disponho|disp[oõ]e)\b"
    r"|(?:sem|faltam?)\s+(?:os\s+|as\s+)?(?:nomes?|dados|detalhes)"
    # en
    r"|(?:cannot|can\s*not|can't|unable\s+to|not\s+able\s+to)\s+(?:provide|give|list|show|identify|name)"
    r"|(?:is|are)\s+not\s+(?:available|included|provided|present|shown)"
    r"|(?:no|missing)\s+(?:names?|details?)\b"
    r")",
    re.IGNORECASE,
)

#: O que a frase diz que falta: nomes, ou dados/detalhe em geral.
_NOMES = re.compile(
    r"\b(?:nombres?|nomes?|names?|denominaci[oó]n|designa[cç][aã]o|r[oó]tulos?|marcas?|brands?|identidad|identifica[cç][aã]o)\b",
    re.IGNORECASE,
)
#: «que aparece en la muestra», «na amostra», «in the sample»… (só quando o
#: resultado está completo).
_AMOSTRA = re.compile(
    r"(?:[,]?\s*(?:que\s+(?:aparecen?|figuran?|se\s+muestran?|aparecem?|constam?)\s+)?"
    r"(?:en|de|dentro\s+de)\s+(?:la|esta|dicha)\s+muestra\b"
    r"|[,]?\s*(?:que\s+(?:aparecem?|constam?|figuram?)\s+)?"
    r"(?:na|nesta|da|desta|dessa|nessa)\s+amostra\b"
    r"|[,]?\s*(?:that\s+(?:appears?|is\s+shown|are\s+shown)\s+)?"
    r"(?:in|from|of)\s+(?:the|this)\s+sample\b)",
    re.IGNORECASE,
)

_FRASE = re.compile(r"[^.!?\n]+[.!?]*\s*|\n+")


def _sem_frases_de_falta(texto: str) -> str:
    """Só as frases que dizem faltar NOMES: é o que se pode verificar nas
    linhas. «No hay datos de 2025» pode ser verdade (pediu-se 2024-2025 e só
    veio 2024) — essa fica."""
    frases = [f for f in _FRASE.findall(texto) if f]
    manter: List[str] = []
    cortadas = 0
    for f in frases:
        if _FALTA.search(f) and _NOMES.search(f):
            cortadas += 1
            continue
        manter.append(f)
    if not cortadas or not "".join(manter).strip():
        return texto  # nada a cortar, ou a resposta ficava vazia
    return "".join(manter).rstrip()


def corrigir_completude(
    texto: str,
    linhas: Optional[Sequence[Dict[str, Any]]],
    completo: bool = True,
) -> str:
    """Tira as frases que dizem faltar o que as linhas têm e, num resultado
    completo, a «muestra»/«amostra»/«sample» que não existe. Ver o topo."""
    if not texto or not linhas:
        return texto
    if colunas_de_nome(linhas):
        texto = _sem_frases_de_falta(texto)
    if completo:
        texto = _AMOSTRA.sub("", texto)
        texto = re.sub(r"[ \t]{2,}", " ", texto)
        texto = re.sub(r"\s+([,.;:])", r"\1", texto)
    return texto
