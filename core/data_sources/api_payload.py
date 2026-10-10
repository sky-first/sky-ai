"""Autenticação e leitura das respostas de uma API REST ligada pelo cliente.

Há uma cópia gémea deste ficheiro no sky-backend
(``src/connectors/_api_payload.py``). O backend testa a ligação e mostra a
pré-visualização; aqui responde-se às perguntas. Se as duas cópias
divergirem, a ligação passa no teste e a resposta sai diferente — mudar as
duas ao mesmo tempo.

Porquê (Anexo C do ESTUDO_DADOS_PUBLICOS_2026-10, defeitos D1 e D3):

* D1 — a web grava ``auth_type`` / ``auth_header`` / ``auth_value``; o
  backend lia ``config["auth"]`` e o motor lia ``api_key`` / ``headers``.
  Nenhum lia os campos da web, e não havia forma de pôr a chave na query
  string (TomTom ``?key=``, Open-Meteo pago ``&apikey=``).
* D3 — XML (DGT DATEX2) e CSV (BCE SDMX) rebentavam com ``JSONDecodeError``;
  JSON com a lista debaixo de uma chave fora da lista fixa (MITECO
  ``ListaEESSPrecio``) chegava como 1 linha com tudo aninhado.

Só biblioteca padrão (``json``, ``csv``, ``xml.etree``).
"""

from __future__ import annotations

import csv
import io
import json
import re
import xml.etree.ElementTree as ET  # nosec B405 — DOCTYPE/ENTITY recusados antes do parse
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Tuple

# ──────────────────────────────────────────────────────────────────────
# Autenticação (D1)
# ──────────────────────────────────────────────────────────────────────

AuthParts = Tuple[Dict[str, str], Dict[str, str], Optional[Tuple[str, str]], List[str]]


def _query_param_name(name: str) -> Optional[str]:
    """``?key`` ou ``query:key`` no campo do cabeçalho = parâmetro na query."""
    name = (name or "").strip()
    if name.startswith("?"):
        return name[1:].strip() or None
    if name.lower().startswith("query:"):
        return name[6:].strip() or None
    return None


def resolve_auth(config: Dict[str, Any]) -> AuthParts:
    """Junta as três formas de configurar a autenticação de uma API.

    Devolve ``(headers, query_params, basic, segredos)``. ``segredos`` é a
    lista de valores a esconder em mensagens de erro e logs.

    Formas aceites (podem coexistir; a da web ganha por ser a que o
    utilizador vê):

    1. ``headers`` — dicionário livre de cabeçalhos;
       ``api_key`` — vira ``Authorization: Bearer`` (legado do motor).
    2. ``auth`` — ``{"type": "bearer"|"apikey"|"basic"|"none", "token",
       "header_name", "username", "password", "in": "header"|"query",
       "param_name"}`` (contrato do conector no backend).
    3. Campos da web — ``auth_type`` ∈ {none, api_key, bearer_token,
       basic_auth}, ``auth_header``, ``auth_value``. Para pôr a chave na
       query string: ``auth_in="query"`` (nome em ``auth_header``) ou
       escrever ``?key`` no campo do cabeçalho.
       ``basic_auth``: ``auth_value`` = ``utilizador:senha``, ou
       utilizador em ``auth_header`` e senha em ``auth_value``.
    """
    headers: Dict[str, str] = {
        str(k): str(v)
        for k, v in (config.get("headers") or {}).items()
        if v is not None
    }
    params: Dict[str, str] = {}
    basic: Optional[Tuple[str, str]] = None
    secrets: List[str] = [str(v) for v in headers.values() if v]

    legacy_key = config.get("api_key")
    if legacy_key:
        headers["Authorization"] = f"Bearer {legacy_key}"
        secrets.append(str(legacy_key))

    auth = config.get("auth") or {}
    if isinstance(auth, dict):
        atype = str(auth.get("type") or "none").lower()
        token = auth.get("token")
        if atype == "bearer" and token:
            headers["Authorization"] = f"Bearer {token}"
            secrets.append(str(token))
        elif atype == "apikey" and token:
            if str(auth.get("in") or "header").lower() == "query":
                params[
                    auth.get("param_name") or auth.get("header_name") or "api_key"
                ] = str(token)
            else:
                headers[auth.get("header_name") or "X-API-Key"] = str(token)
            secrets.append(str(token))
        elif atype == "basic" and auth.get("username"):
            basic = (str(auth["username"]), str(auth.get("password") or ""))
            if auth.get("password"):
                secrets.append(str(auth["password"]))

    web_type = str(config.get("auth_type") or "none").lower().replace("-", "_")
    value = config.get("auth_value")
    header_name = str(config.get("auth_header") or "").strip()
    if value and web_type != "none":
        value = str(value).strip()
        secrets.append(value)
        if web_type in ("bearer_token", "bearer"):
            token = value[7:].strip() if value.lower().startswith("bearer ") else value
            headers["Authorization"] = f"Bearer {token}"
        elif web_type in ("api_key", "apikey"):
            qname = _query_param_name(header_name)
            if not qname and str(config.get("auth_in") or "").lower() == "query":
                qname = header_name or "api_key"
            if qname:
                params[qname] = value
            else:
                headers[header_name or "X-API-Key"] = value
        elif web_type in ("basic_auth", "basic"):
            if ":" in value and not header_name:
                user, _, pwd = value.partition(":")
            else:
                user, pwd = header_name, value
            if user:
                basic = (user, pwd)
                if pwd:
                    secrets.append(pwd)

    return headers, params, basic, [s for s in secrets if s and len(s) >= 4]


def redact(text: Any, secrets: Iterable[str]) -> str:
    """Tira os segredos de uma mensagem antes de a registar ou devolver.

    O ``httpx`` põe o URL inteiro na mensagem de erro — com a chave, quando
    ela vai na query string.
    """
    out = str(text)
    for s in secrets:
        if s:
            out = out.replace(s, "***")
    return out


# ──────────────────────────────────────────────────────────────────────
# Respostas → linhas (D3)
# ──────────────────────────────────────────────────────────────────────

# Nomes que, entre várias listas, dizem «esta é a lista principal».
_LIST_KEYS = (
    "data",
    "items",
    "results",
    "records",
    "rows",
    "features",
    "entries",
    "elements",
    "hits",
    "docs",
    "value",
    "users",
    "orders",
)

_TEXT_LIMIT = 2000


def detect_format(content_type: str, text: str) -> str:
    """``json`` | ``xml`` | ``csv`` | ``text`` — pelo Content-Type e, sem ele,
    pelo próprio conteúdo (há APIs que mandam CSV como ``text/plain`` e
    SDMX como ``application/vnd.sdmx.data+csv``)."""
    ct = (content_type or "").lower()
    if "json" in ct:
        return "json"
    if "xml" in ct and "html" not in ct:
        return "xml"
    if "csv" in ct or "comma-separated" in ct or "tab-separated" in ct:
        return "csv"
    head = text.lstrip("﻿ \t\r\n")[:200]
    if head[:1] in ("{", "["):
        return "json"
    if head[:1] == "<":
        low = head.lower()
        if low.startswith("<!doctype html") or low.startswith("<html"):
            return "text"
        return "xml"
    if _looks_like_csv(text):
        return "csv"
    return "text"


def _looks_like_csv(text: str) -> bool:
    lines = [ln for ln in text.splitlines()[:6] if ln.strip()][:5]
    if len(lines) < 2:
        return False
    for delim in (",", ";", "	", "|"):
        try:
            widths = {len(r) for r in csv.reader(lines, delimiter=delim)}
        except csv.Error:
            continue
        if len(widths) == 1 and widths.pop() >= 2:
            return True
    return False


def parse_records(
    body: bytes | str,
    content_type: str = "",
    records_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Transforma o corpo de uma resposta numa lista de linhas (dicts).

    * JSON — encontra a lista principal sozinho (ver ``_main_json_list``) e
      achata um nível (``{"rates": {"USD": 1.1}}`` → ``rates.USD``).
    * XML — escolhe o elemento repetido mais numeroso (``situation`` no
      DATEX2) e cada folha vira coluna, com o nome mais curto que não
      colida (``latitude``, ``to.pointCoordinates.latitude``…).
    * CSV — separador detectado (``,`` ``;`` tab ``|``).
    * Outro — ``[{"text": …}]`` cortado a 2.000 caracteres.

    ``records_path`` (opcional, por ligação ou por endpoint) diz onde está a
    lista quando a detecção não acerta: ``"ListaEESSPrecio"``,
    ``"response.docs"``, ``"situation.situationRecord"`` (XML, por nomes
    locais, sem prefixo).
    """
    if isinstance(body, bytes):
        raw = body
        text = body.decode("utf-8", errors="replace")
    else:
        text = body
        raw = body.encode("utf-8")
    if not text.strip():
        return []

    fmt = detect_format(content_type, text)
    if fmt == "json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Content-Type a mentir: tenta pelo conteúdo.
            fmt = detect_format("", text)
            if fmt == "json":
                return [{"text": text[:_TEXT_LIMIT]}]
        else:
            return json_records(data, records_path)
    if fmt == "xml":
        return xml_records(raw, records_path)
    if fmt == "csv":
        return csv_records(text)
    return [{"text": text[:_TEXT_LIMIT]}]


# ── JSON ────────────────────────────────────────────────────────────


def _walk_json(data: Any, path: str) -> Any:
    node = data
    for part in [p for p in path.split(".") if p]:
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.lstrip("-").isdigit():
            node = node[int(part)]
        else:
            raise ValueError(
                f"records_path '{path}' não existe na resposta (parou em '{part}')"
            )
    return node


def _is_list_of_dicts(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and isinstance(value[0], dict)


def _main_json_list(data: Any) -> Any:
    """A lista de registos dentro de um envelope, se for inequívoca.

    Procura listas de objectos no 1.º e 2.º nível. Uma só → é essa
    (MITECO: ``ListaEESSPrecio``). Várias → a que tiver um nome conhecido
    (``data``, ``items``, ``results``…). Senão fica o objecto inteiro como
    uma linha — o OSRM devolve ``routes`` e ``waypoints`` e escolher às
    cegas perdia a rota.
    """
    if not isinstance(data, dict):
        return data
    candidates: List[Tuple[str, list]] = []
    for key, value in data.items():
        if _is_list_of_dicts(value):
            candidates.append((key, value))
        elif isinstance(value, dict):
            for key2, value2 in value.items():
                if _is_list_of_dicts(value2):
                    candidates.append((key2, value2))
    if len(candidates) == 1:
        return candidates[0][1]
    for name in _LIST_KEYS:
        for key, value in candidates:
            if key.lower() == name:
                return value
    return data


def _flatten_one_level(row: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, dict):
            for key2, value2 in value.items():
                out[f"{key}.{key2}"] = value2
        else:
            out[key] = value
    return out


def json_records(data: Any, records_path: Optional[str] = None) -> List[Dict[str, Any]]:
    node = _walk_json(data, records_path) if records_path else _main_json_list(data)
    if isinstance(node, list):
        return [
            _flatten_one_level(item) if isinstance(item, dict) else {"value": item}
            for item in node
        ]
    if isinstance(node, dict):
        return [_flatten_one_level(node)]
    if node is None:
        return []
    return [{"value": node}]


# ── XML ─────────────────────────────────────────────────────────────

_XML_DANGER = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)


def _local(tag: Any) -> str:
    tag = str(tag)
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag.split(":")[-1]


def _main_repeated(root: ET.Element) -> List[ET.Element]:
    """O grupo de irmãos com o mesmo nome mais numeroso.

    Conta por pai (não globalmente): no DATEX2, ``pointCoordinates`` aparece
    2× por incidência e ganharia a contagem global. Contentores (elementos
    com filhos) têm prioridade sobre folhas repetidas.
    """
    best: List[ET.Element] = []
    best_leaf: List[ET.Element] = []
    for parent in root.iter():
        children = list(parent)
        if len(children) < 2:
            continue
        counts = Counter(_local(c.tag) for c in children)
        name, n = counts.most_common(1)[0]
        if n < 2:
            continue
        group = [c for c in children if _local(c.tag) == name]
        if any(len(c) for c in group):
            if len(group) > len(best):
                best = group
        elif len(group) > len(best_leaf):
            best_leaf = group
    if best:
        return best
    if best_leaf:
        return best_leaf
    return [root]


def _xml_walk(root: ET.Element, path: str) -> List[ET.Element]:
    parts = [p for p in path.split(".") if p]
    if parts and parts[0] == _local(root.tag):
        parts = parts[1:]
    nodes = [root]
    for part in parts:
        nodes = [c for n in nodes for c in n if _local(c.tag) == part]
    if not nodes:
        raise ValueError(f"records_path '{path}' não existe na resposta XML")
    return nodes


def _xml_leaves(
    elem: ET.Element, prefix: Tuple[str, ...], out: List[Tuple[Tuple[str, ...], str]]
):
    for attr, val in elem.attrib.items():
        out.append((prefix + ("@" + _local(attr),), val))
    children = list(elem)
    if not children:
        text = (elem.text or "").strip()
        if text and prefix:
            out.append((prefix, text))
        return
    for child in children:
        _xml_leaves(child, prefix + (_local(child.tag),), out)


def xml_records(raw: bytes, records_path: Optional[str] = None) -> List[Dict[str, Any]]:
    # Sem DTD não há entidades: fecha a porta ao «billion laughs» e a
    # entidades externas, sem depender do defusedxml.
    if _XML_DANGER.search(raw):
        raise ValueError("XML com DOCTYPE/ENTITY recusado")
    root = ET.fromstring(raw)  # nosec B314 — DOCTYPE/ENTITY recusados acima
    elems = _xml_walk(root, records_path) if records_path else _main_repeated(root)

    per_record: List[List[Tuple[Tuple[str, ...], str]]] = []
    all_paths: Dict[Tuple[str, ...], None] = {}
    for elem in elems:
        leaves: List[Tuple[Tuple[str, ...], str]] = []
        _xml_leaves(elem, (), leaves)
        if not leaves and (elem.text or "").strip():
            leaves.append(((_local(elem.tag),), elem.text.strip()))
        per_record.append(leaves)
        for p, _ in leaves:
            all_paths.setdefault(p, None)

    names = _short_names(list(all_paths))
    rows: List[Dict[str, Any]] = []
    for leaves in per_record:
        row: Dict[str, Any] = {}
        for p, val in leaves:
            key = names[p]
            if key in row:
                prev = row[key]
                row[key] = (prev if isinstance(prev, list) else [prev]) + [val]
            else:
                row[key] = val
        rows.append(row)
    return rows


def _short_names(paths: List[Tuple[str, ...]]) -> Dict[Tuple[str, ...], str]:
    """Nome de coluna curto e sem colisões para cada caminho de folha.

    A folha sozinha (``roadName``) quando é única; senão a folha com o
    antepassado mais próximo que a distingue (``to.latitude`` /
    ``from.latitude``); em último caso o caminho inteiro. Calculado sobre
    TODOS os registos, para a mesma folha ter o mesmo nome em todas as
    linhas.
    """
    by_leaf: Dict[str, List[Tuple[str, ...]]] = {}
    for p in paths:
        by_leaf.setdefault(p[-1], []).append(p)
    names: Dict[Tuple[str, ...], str] = {}
    for p in paths:
        leaf = p[-1]
        rivals = [q for q in by_leaf[leaf] if q != p]
        if not rivals:
            names[p] = leaf
            continue
        for anc in reversed(p[:-1]):
            if not any(anc in q[:-1] for q in rivals):
                names[p] = f"{anc}.{leaf}"
                break
        else:
            names[p] = ".".join(p)
    return names


# ── CSV ─────────────────────────────────────────────────────────────


def csv_records(text: str) -> List[Dict[str, Any]]:
    text = text.lstrip("﻿")
    sample = text[:20000]
    try:
        dialect: Any = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows: List[Dict[str, Any]] = []
    for row in reader:
        clean = {
            (k.strip() if isinstance(k, str) else k): v
            for k, v in row.items()
            if k is not None and k != ""
        }
        if any(v not in (None, "") for v in clean.values()):
            rows.append(clean)
    return rows


# ── records_path por endpoint ───────────────────────────────────────


def records_path_for(config: Dict[str, Any], endpoint: str) -> Optional[str]:
    """``records_path`` do endpoint declarado que casa com o pedido, ou o da
    ligação. Os caminhos declarados podem ter ``{marcadores}``."""
    wanted = "/" + (endpoint or "").split("?", 1)[0].strip("/")
    for ep in config.get("endpoints") or []:
        if not isinstance(ep, dict) or not ep.get("records_path"):
            continue
        declared = "/" + str(ep.get("path") or "").split("?", 1)[0].strip("/")
        pattern = re.sub(r"\\\{[^}]*\\\}", "[^/]+", re.escape(declared))
        if re.fullmatch(pattern, wanted):
            return str(ep["records_path"])
    return config.get("records_path") or None
