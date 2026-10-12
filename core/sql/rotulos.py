"""Que coluna dá o NOME de uma coisa — e que coluna é só um número interno.

Produção, 12/10/2026, tenant skyfirstlabs, ligação «Operaciones» (``ops``):
«¿Cuál es la gasolinera más barata de gasóleo A en la ruta de Lisboa a
Madrid?» → «…es la de id 16440, con un precio de 1,69 €». O 16440 é o
IDEESS do MITECO: ninguém sabe que posto é. O nome estava ao lado, em
``gasolineras_precio.rotulo`` (marca) e ``localidad``/``municipio`` (onde).

Duas redes, as duas a partir daqui:

* o especialista vê as colunas de rótulo MARCADAS no esquema e a regra de
  as escolher junto com o id (``core/llm/specialist.py``);
* o formatador nunca deixa «id 16440» como sujeito quando a linha traz um
  rótulo (``core/llm/nomes.py``).

Decide-se pelo NOME da coluna, palavra a palavra (como ``core/llm/numeros``):
``rotulo``, ``nombre``, ``customer_name``, ``marca``… são rótulos;
``localidad``, ``municipio``, ``city``… dizem ONDE (qualificam o rótulo).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Sequence

#: Palavras de nome de coluna que dizem «isto é o nome da coisa».
PALAVRAS_DE_ROTULO = {
    "rotulo", "nombre", "nome", "name", "marca", "brand", "titulo", "title",
    "label", "etiqueta", "denominacion", "denominacao", "designacao",
    "razon", "social", "empresa", "company", "descripcion", "descricao",
    "description", "desc", "display", "alias", "apelido", "producto",
    "produto", "product", "cliente", "customer", "proveedor", "fornecedor",
    "supplier", "vendor", "estacion", "station", "tienda", "loja", "store",
}  # fmt: skip

#: Palavras que dizem ONDE — qualificam o rótulo («REPSOL (ALCORCÓN)»).
PALAVRAS_DE_LUGAR = {
    "localidad", "localidade", "municipio", "concelho", "ciudad", "cidade",
    "city", "town", "poblacion", "freguesia",
}  # fmt: skip

#: Palavras que tiram a coluna da lista mesmo ao lado de uma das de cima:
#: ``customer_id`` é um id, ``product_code`` é um código.
PALAVRAS_QUE_NAO_SAO_ROTULO = {
    "id", "ids", "code", "codigo", "cod", "sku", "uuid", "key", "hash",
    "count", "num", "numero", "qty", "total", "amount", "fecha", "date",
    "data", "url", "email", "tipo", "type", "status", "estado",
}  # fmt: skip

_TIPOS_DE_TEXTO = ("STR", "CHAR", "TEXT", "VARCHAR")


def _palavras(nome: str) -> set:
    t = unicodedata.normalize("NFKD", str(nome or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    # camelCase → camel_case (antes de baixar a caixa)
    t = re.sub(r"([a-z])([A-Z])", r"\1_\2", t).lower()
    return set(re.split(r"[^a-z0-9]+", t)) - {""}


def _e_texto(tipo: Optional[str]) -> bool:
    if tipo is None:
        return True  # sem tipo (linhas de resultado): decide o valor
    t = str(tipo).upper()
    return any(k in t for k in _TIPOS_DE_TEXTO)


def e_coluna_de_id(nome: str) -> bool:
    """Identificador interno: ``id``, ``*_id``, ``id_*``, ``IDEESS``,
    ``customerId``."""
    bruto = str(nome or "").rsplit(".", 1)[-1].lstrip("@")
    low = bruto.lower()
    return (
        low in ("id", "ideess", "uuid")
        or low.startswith("id_")
        or low.endswith("_id")
        or bool(re.match(r"^ID[A-Z_]", bruto))
        or bruto.endswith("Id")
    )


def e_coluna_de_rotulo(nome: str, tipo: Optional[str] = None) -> bool:
    p = _palavras(nome)
    if not p or not _e_texto(tipo) or e_coluna_de_id(nome):
        return False
    if p & PALAVRAS_QUE_NAO_SAO_ROTULO:
        return False
    return bool(p & PALAVRAS_DE_ROTULO)


def e_coluna_de_lugar(nome: str, tipo: Optional[str] = None) -> bool:
    p = _palavras(nome)
    if not p or not _e_texto(tipo) or e_coluna_de_id(nome):
        return False
    return bool(p & PALAVRAS_DE_LUGAR)


def marca_de_rotulo(nome: str, tipo: Optional[str] = None) -> str:
    """A marca que o esquema do especialista põe à frente da coluna."""
    if e_coluna_de_rotulo(nome, tipo):
        return "LABEL"
    if e_coluna_de_lugar(nome, tipo):
        return "LABEL: place"
    return ""


# ── Nas linhas do resultado ──────────────────────────────────────────────


def _texto(v: Any) -> Optional[str]:
    if isinstance(v, str) and v.strip() and not re.fullmatch(r"[\d.,\s:-]+", v):
        return v.strip()
    return None


def rotulo_da_linha(linha: Dict[str, Any]) -> Optional[str]:
    """«REPSOL (ALCORCÓN)»: o rótulo da linha e, se houver, o lugar entre
    parêntesis. None quando a linha não traz rótulo nenhum."""
    if not isinstance(linha, dict):
        return None
    nome = next(
        (t for c, v in linha.items() if e_coluna_de_rotulo(c) and (t := _texto(v))),
        None,
    )
    lugar = next(
        (t for c, v in linha.items() if e_coluna_de_lugar(c) and (t := _texto(v))),
        None,
    )
    if nome and lugar and lugar.casefold() not in nome.casefold():
        return f"{nome} ({lugar})"
    return nome or lugar


def ids_com_rotulo(linhas: Optional[Sequence[Dict[str, Any]]]) -> Dict[str, str]:
    """``{"16440": "REPSOL (ALCORCÓN)"}`` — cada valor de uma coluna de id
    cuja linha traz um rótulo. Um id que aparece com dois rótulos diferentes
    fica de fora (não se adivinha)."""
    out: Dict[str, str] = {}
    conflito: set = set()
    for linha in linhas or []:
        if not isinstance(linha, dict):
            continue
        rotulo = rotulo_da_linha(linha)
        if not rotulo:
            continue
        for c, v in linha.items():
            if not e_coluna_de_id(c) or v is None or isinstance(v, bool):
                continue
            chave = str(v).strip()
            if re.fullmatch(r"\d+(?:\.0+)?", chave):
                chave = chave.split(".")[0]
            if not chave:
                continue
            if chave in out and out[chave] != rotulo:
                conflito.add(chave)
            out.setdefault(chave, rotulo)
    for chave in conflito:
        out.pop(chave, None)
    return out


def colunas_de_rotulo(colunas: Iterable[Any]) -> List[str]:
    """Os nomes das colunas de rótulo/lugar de uma lista de colunas."""
    out: List[str] = []
    for c in colunas or []:
        nome = c.get("name") if isinstance(c, dict) else getattr(c, "name", None)
        tipo = (
            (c.get("type") or c.get("data_type"))
            if isinstance(c, dict)
            else getattr(c, "type", None)
        )
        if nome and marca_de_rotulo(nome, tipo):
            out.append(nome)
    return out
