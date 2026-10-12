"""Nomes na resposta: o rótulo em vez do id, e os nomes copiados dos dados.

Produção, 12/10/2026, tenant skyfirstlabs, ligação «Operaciones» (``ops``):

1. «¿Cuál es la gasolinera más barata de gasóleo A en la ruta de Lisboa a
   Madrid?» → «…es la de id 16440, con un precio de 1,69 €». A linha podia
   trazer o ``rotulo`` e a ``localidad``; a resposta deu o número interno.
   ``nomear_ids`` troca «id 16440» pelo rótulo da linha onde esse id está
   («REPSOL (ALCORCÓN)»). Sem rótulo na linha, fica como está — não se
   inventa nome nenhum.

2. «Lista las 5 gasolineras más baratas … Badajoz-Madrid» → «… dos precios de
   1,71 € en Alcobón». Alcobón não existe: os dados vêm do MITECO sem
   transformação (``localidad``/``municipio`` só com ``strip``) e o posto do
   A-5 é em Alcorcón. Foi o modelo a reescrever o nome. ``corrigir_nomes``
   troca uma palavra com maiúscula que é QUASE um valor das linhas
   (semelhança ≥ 0,75, sem empate) pelo valor exacto das linhas. O que já é
   igual (sem acentos nem maiúsculas) não se toca, nem as palavras da
   pergunta (são da pessoa).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.sql.correcao_de_literais import _levenshtein, normalizar
from core.sql.rotulos import ids_com_rotulo

#: Semelhança mínima (Levenshtein normalizado) para trocar um nome.
#: ALCOBON→ALCORCON dá 0,75 (duas edições em oito letras).
LIMIAR_NOME = 0.75
#: O segundo candidato tem de ficar pelo menos isto atrás.
MARGEM_NOME = 0.1
MIN_LETRAS_NOME = 4

# ── 1. O rótulo em vez do id ─────────────────────────────────────────────

_PALAVRA_ID = r"(?:id|ideess|identificador|identifier)"
_NUM_ID = r"(?:n\.?\s*[ºo°]\.?\s*|#|:|=)?\s*"

#: «(id 16440)» — entre parêntesis.
_ID_ENTRE_PARENTESIS = re.compile(
    rf"[  ]?\(\s*{_PALAVRA_ID}\s*{_NUM_ID}(\d{{1,15}})\s*\)", re.IGNORECASE
)
#: «con id 16440», «la de id 16440», «ID: 16440». O «con/com/with» (e o
#: artigo) vai com o id: «la gasolinera con id 16440» → «la gasolinera REPSOL».
_ID_SOLTO = re.compile(
    rf"(?:\b(?:con|com|with)\s+(?:(?:el|la|o|a|the)\s+)?)?"
    rf"\b{_PALAVRA_ID}\s*{_NUM_ID}(\d{{1,15}})\b",
    re.IGNORECASE,
)


def nomear_ids(texto: str, linhas: Optional[Sequence[Dict[str, Any]]]) -> str:
    """Troca «id 16440» pelo rótulo da linha desse id. Ver o topo."""
    if not texto or not linhas:
        return texto
    rotulos = ids_com_rotulo(linhas)
    if not rotulos:
        return texto

    def entre_parentesis(m: "re.Match[str]") -> str:
        rotulo = rotulos.get(m.group(1))
        if not rotulo:
            return m.group(0)
        nome = rotulo.split(" (")[0]
        # Só o que vem ANTES conta: no streaming o resto ainda não chegou, e
        # a decisão tem de ser a mesma pedaço a pedaço e no fim.
        if nome.casefold() in texto[: m.start()].casefold():
            return ""  # o nome já foi dito: o id sobra
        return f" ({rotulo})"

    def solto(m: "re.Match[str]") -> str:
        rotulo = rotulos.get(m.group(1))
        return rotulo if rotulo else m.group(0)

    texto = _ID_ENTRE_PARENTESIS.sub(entre_parentesis, texto)
    return _ID_SOLTO.sub(solto, texto)


# ── 2. Nomes copiados dos dados ──────────────────────────────────────────

#: Palavras com maiúscula que são só início de frase — nunca se trocam.
_COMUNS = {
    "entre", "estas", "estos", "esta", "este", "para", "pero", "como", "donde",
    "desde", "hasta", "sobre", "tambien", "ademas", "todas", "todos", "cada",
    "tiene", "tienen", "segun", "durante", "aunque", "mientras", "precio",
    "precios", "porque", "quando", "onde", "essa", "esse", "estes", "tambem",
    "todas", "cada", "with", "there", "these", "those", "this", "that", "from",
    "while", "price", "prices", "lista", "listado", "total", "media", "promedio",
}  # fmt: skip

_PALAVRA = re.compile(r"(?<![\w'-])([^\W\d_][\w'-]*)")
_NUMERICO = re.compile(r"^[\s\d.,:/+-]*$")


def _sem(a: str, b: str) -> float:
    na, nb = normalizar(a), normalizar(b)
    if not na or not nb:
        return 0.0
    return 1.0 - _levenshtein(na, nb) / max(len(na), len(nb))


def nomes_das_linhas(linhas: Optional[Sequence[Dict[str, Any]]]) -> List[str]:
    """Os valores de texto das linhas e as palavras deles (≥4 letras), pela
    ordem em que aparecem, sem repetidos."""
    vistos: Dict[str, None] = {}
    for linha in linhas or []:
        if not isinstance(linha, dict):
            continue
        for v in linha.values():
            if not isinstance(v, str):
                continue
            v = v.strip()
            if not v or len(v) > 60 or _NUMERICO.match(v):
                continue
            vistos.setdefault(v, None)
            for p in re.split(r"[\s/,()-]+", v):
                if len(p) >= MIN_LETRAS_NOME and not _NUMERICO.match(p):
                    vistos.setdefault(p, None)
    return list(vistos)


def _melhor(palavra: str, nomes: Sequence[str]) -> Optional[str]:
    pontuados: List[Tuple[float, str]] = []
    for n in nomes:
        if abs(len(normalizar(n)) - len(normalizar(palavra))) > 2:
            continue
        pontuados.append((_sem(palavra, n), n))
    if not pontuados:
        return None
    pontuados.sort(key=lambda p: p[0], reverse=True)
    melhor, nome = pontuados[0]
    if melhor < LIMIAR_NOME:
        return None
    for s, outro in pontuados[1:]:
        if normalizar(outro) == normalizar(nome):
            continue  # o mesmo nome escrito de outra maneira
        if melhor - s < MARGEM_NOME:
            return None
        break
    return nome


def corrigir_nomes(
    texto: str,
    linhas: Optional[Sequence[Dict[str, Any]]],
    pergunta: Optional[str] = None,
) -> str:
    """Troca um nome próprio mal escrito pelo valor das linhas. Ver o topo."""
    if not texto or not linhas:
        return texto
    nomes = nomes_das_linhas(linhas)
    if not nomes:
        return texto
    exactos = {normalizar(n) for n in nomes}
    da_pergunta = {normalizar(p) for p in _PALAVRA.findall(pergunta or "")}

    def trocar(m: "re.Match[str]") -> str:
        palavra = m.group(1)
        if not palavra[:1].isupper() or len(palavra) < MIN_LETRAS_NOME:
            return palavra
        n = normalizar(palavra)
        if n in exactos or n in da_pergunta or n in _COMUNS:
            return palavra
        alvo = _melhor(palavra, nomes)
        return alvo if alvo is not None else palavra

    return _PALAVRA.sub(trocar, texto)


def regras_de_nomes() -> str:
    """O bloco do prompt do formatador (em inglês, como o resto do prompt)."""
    return (
        "\nNAMES (NON-NEGOTIABLE):\n"
        "- Name every entity by its human label from the row (name, brand, "
        "place) — never by an internal id. 'la de id 16440' is wrong when the row "
        "has rotulo/nombre/localidad: write the label instead.\n"
        "- Copy proper nouns (places, brands, people, products) EXACTLY as they "
        "appear in the data, letter by letter. Never re-spell, translate or "
        "'correct' them.\n"
    )
