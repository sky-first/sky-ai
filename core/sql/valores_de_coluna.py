"""Valores reais das colunas de texto — para o especialista copiar, não escrever.

Produção, 11/10/2026, tenant skyfirstlabs, ligação «Operaciones» (``ops``):
«Lista las 5 gasolineras con el gasóleo A más barato en la tabla
gasolineras_rota para la ruta Badajoz-Madrid». O especialista escolheu bem as
tabelas (gasolineras_rota + gasolineras_precio, #279) e escreveu
``WHERE UPPER(gr.origem) = 'BAJAZOZ'`` — gralha, 0 linhas, «no puedo
proporcionar esa lista».

Os registos mostravam ``SELECT DISTINCT rotulo … FROM ops.gasolineras_precio …
LIMIT 26`` para cada coluna de texto de gasolineras_precio e NADA para
gasolineras_rota. A amostragem corria na rota, ANTES do orquestrador, sobre
TODAS as tabelas da ligação, com um tecto de 40 colunas por pedido e pela
ordem do catálogo. As 12 colunas de texto de gasolineras_precio gastavam o que
restava do tecto; gasolineras_rota vem a seguir por ordem alfabética e ficava
de fora — exactamente a tabela onde estava o filtro. (E o caminho em streaming,
o da app, nem sequer amostrava.)

Agora a amostragem é feita no especialista, sobre as tabelas ESCOLHIDAS, com
tecto por tabela — todas as escolhidas ficam cobertas, em qualquer caminho.

── Latência (12/10/2026) ──────────────────────────────────────────────

«¿Cuál es la gasolinera más barata de gasóleo A en la ruta de Lisboa a
Madrid?» levou 50 s. A amostragem fazia 16 ``SELECT DISTINCT`` por pergunta,
UM A UM, e a cache vivia só no processo: cada pod novo (cada deploy), cada
worker do Celery (a análise «context» dos agentes) e a correcção de literais
(``LIMIT 501``, sem cache nenhuma) voltavam a ler tudo. Agora:

* a cache tem DOIS níveis — no processo e no Redis — com validade de 30 min,
  chave «tenant|ligação|tabela|coluna», e serve qualquer limite que caiba no
  que já foi lido (um domínio completo serve também a correcção de literais);
* as consultas que faltam correm em paralelo;
* colunas de texto livre (morada, horário, código postal, URL, fonte…) não se
  amostram, a não ser que a pergunta as nomeie — têm cardinalidade alta e
  custavam uma consulta para nada.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Iterable, List, Optional, Tuple

from core.logging_utils import log_event

# Só se mostram colunas categóricas — até 25 valores distintos.
MAX_DISTINTOS = 25
# Tecto por TABELA escolhida (não por pedido): uma tabela larga não pode
# deixar a seguinte sem valores.
MAX_COLUNAS_POR_TABELA = 20
# Validade da cache (os dois níveis). Os domínios mudam pouco; meia hora é o
# compromisso entre «não reler a cada pergunta» e «ver um valor novo hoje».
TTL_SEGUNDOS = 30 * 60
# Consultas de amostragem em simultâneo (por pedido).
MAX_EM_PARALELO = 6
# Depois de uma falha do Redis fica-se só com a cache local durante isto —
# um Redis em baixo não pode somar um timeout a cada coluna.
PAUSA_DO_REDIS = 60.0

_PREFIXO_REDIS = "sky:valores:v1:"

# Nível 1: no processo. chave → (expira_em, valores lidos, limite pedido).
# ``valores`` tem até ``limite + 1`` elementos: mais do que ``limite`` quer
# dizer «a coluna tem mais do que isto» (domínio incompleto).
_CACHE: Dict[str, Tuple[float, List[str], int]] = {}
_CACHE_LOCK = threading.Lock()

_NAO_DEFINIDO = object()
_redis_forcado: Any = _NAO_DEFINIDO  # ver ``usar_redis``
_redis_cliente: Any = None
_redis_pausado_ate = 0.0
_REDIS_LOCK = threading.Lock()

#: Contadores (para os registos e para os testes).
estatisticas = {"consultas": 0, "local": 0, "redis": 0}


def e_coluna_de_texto(tipo: str) -> bool:
    """Tipos de texto em todos os dialectos (STRING, varchar, text, …)."""
    t = (tipo or "").upper()
    return any(k in t for k in ("STR", "CHAR", "TEXT", "VARCHAR", "ENUM"))


def _tipo(col: Any) -> str:
    if isinstance(col, dict):
        return col.get("type") or col.get("data_type") or ""
    return getattr(col, "type", "") or ""


def _nome(col: Any) -> str:
    if isinstance(col, dict):
        return col.get("name") or ""
    return getattr(col, "name", "") or ""


def _descricao(col: Any) -> str:
    if isinstance(col, dict):
        return col.get("description") or ""
    return getattr(col, "description", "") or ""


# ── Redis (nível 2) ──────────────────────────────────────────────────────


def usar_redis(cliente: Any) -> None:
    """Fixa o cliente Redis (``None`` desliga o nível 2). Para os testes."""
    global _redis_forcado, _redis_pausado_ate
    with _REDIS_LOCK:
        _redis_forcado = cliente
        _redis_pausado_ate = 0.0


def _redis() -> Any:
    global _redis_cliente
    if time.monotonic() < _redis_pausado_ate:
        return None
    if _redis_forcado is not _NAO_DEFINIDO:
        return _redis_forcado
    if (os.getenv("SKY_VALORES_CACHE_REDIS") or "1").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return None
    with _REDIS_LOCK:
        if _redis_cliente is None:
            try:
                from config.settings import settings
                from core.redis_utils import make_redis_client

                _redis_cliente = make_redis_client(
                    settings.celery_broker_url,
                    socket_connect_timeout=1,
                    socket_timeout=1,
                )
            except Exception as exc:
                _pausar_redis(exc)
                return None
        return _redis_cliente


def _pausar_redis(exc: Exception) -> None:
    global _redis_pausado_ate
    _redis_pausado_ate = time.monotonic() + PAUSA_DO_REDIS
    log_event("sample_values_redis_unavailable", {"error": str(exc)[:160]})


def _chave_redis(chave: str) -> str:
    return _PREFIXO_REDIS + hashlib.sha1(chave.encode("utf-8")).hexdigest()


def _redis_ler(chaves: List[str]) -> Dict[str, Tuple[List[str], int]]:
    cliente = _redis()
    if cliente is None or not chaves:
        return {}
    try:
        brutos = cliente.mget([_chave_redis(c) for c in chaves])
    except Exception as exc:
        _pausar_redis(exc)
        return {}
    out: Dict[str, Tuple[List[str], int]] = {}
    for chave, bruto in zip(chaves, brutos or []):
        if not bruto:
            continue
        try:
            dado = json.loads(bruto)
            out[chave] = ([str(v) for v in dado["v"]], int(dado["l"]))
        except Exception:
            continue
    return out


def _redis_gravar(chave: str, valores: List[str], limite: int) -> None:
    cliente = _redis()
    if cliente is None:
        return
    try:
        cliente.setex(
            _chave_redis(chave),
            TTL_SEGUNDOS,
            json.dumps({"v": valores, "l": limite}, ensure_ascii=False),
        )
    except Exception as exc:
        _pausar_redis(exc)


# ── A cache ──────────────────────────────────────────────────────────────


def _servir(valores: List[str], lido: int, limite: int) -> Optional[List[str]]:
    """O que uma leitura com ``lido`` sabe dizer para ``limite``, ou None
    (não chega: era incompleta e mais curta do que o pedido)."""
    completo = len(valores) <= lido
    if completo or lido >= limite:
        return valores[: limite + 1]
    return None


def _guardar_local(chave: str, valores: List[str], limite: int) -> None:
    agora = time.monotonic()
    with _CACHE_LOCK:
        actual = _CACHE.get(chave)
        # Não se troca uma leitura maior, ainda válida, por uma mais curta.
        if actual and actual[0] > agora and actual[2] > limite:
            return
        _CACHE[chave] = (agora + TTL_SEGUNDOS, list(valores), limite)


def _da_cache(chaves: List[str], limite: int) -> Dict[str, List[str]]:
    """Valores em cache (local, depois Redis) para cada chave que os tenha."""
    agora = time.monotonic()
    achados: Dict[str, List[str]] = {}
    faltam: List[str] = []
    with _CACHE_LOCK:
        for chave in chaves:
            entrada = _CACHE.get(chave)
            if entrada and entrada[0] > agora:
                servido = _servir(entrada[1], entrada[2], limite)
                if servido is not None:
                    achados[chave] = servido
                    continue
            faltam.append(chave)
    estatisticas["local"] += len(achados)
    for chave, (valores, lido) in _redis_ler(faltam).items():
        servido = _servir(valores, lido, limite)
        if servido is None:
            continue
        achados[chave] = servido
        estatisticas["redis"] += 1
        _guardar_local(chave, valores, lido)
    return achados


def _guardar(chave: str, valores: List[str], limite: int) -> None:
    _guardar_local(chave, valores, limite)
    _redis_gravar(chave, valores, limite)


def chave_da_coluna(ligacao: str, fisica: str, coluna: str) -> str:
    """«tenant|ligação|tabela|coluna». O tenant entra por segurança: os ids
    das ligações são UUID, mas o Redis é partilhado por todos os clientes."""
    try:
        from core.tenant_context import current_tenant

        tenant = current_tenant().slug or "default"
    except Exception:
        tenant = "default"
    return f"{tenant}|{ligacao}|{fisica}|{coluna}".lower()


def _chave_da_ligacao(tabela: Any, data_source: Any, ligacao: Optional[str]) -> str:
    return str(
        ligacao
        or getattr(tabela, "data_connection_id", None)
        or getattr(data_source, "connection_id", None)
        or f"ds{id(data_source)}"
    )


def valores_distintos(
    data_source: Any, fisica: str, coluna: str, limite: int
) -> Optional[List[str]]:
    """Até ``limite`` valores distintos não nulos. Devolve a lista com
    ``limite + 1`` elementos quando há mais (quem chama decide), ``[]`` para
    coluna vazia e levanta a excepção da fonte se a consulta falhar.

    Vai SEMPRE à fonte; ``valores_em_cache`` é a versão com cache."""
    sql = (
        f"SELECT DISTINCT {coluna} AS v FROM {fisica} "
        f"WHERE {coluna} IS NOT NULL LIMIT {limite + 1}"
    )
    estatisticas["consultas"] += 1
    rows = data_source.run_query(sql) or []
    if hasattr(rows, "to_pylist"):
        rows = rows.to_pylist()
    out: List[str] = []
    for r in rows:
        v = None
        if isinstance(r, dict):
            v = r.get("v")
        elif hasattr(r, "_mapping"):
            v = r._mapping.get("v")
        elif isinstance(r, (list, tuple)) and r:
            v = r[0]
        if v is not None:
            out.append(str(v))
    return out


def valores_em_cache(
    data_source: Any,
    fisica: str,
    coluna: str,
    limite: int,
    tabela: Any = None,
) -> List[str]:
    """Como ``valores_distintos``, mas lê e grava a cache partilhada (a mesma
    da amostragem). Erros sobem e NÃO ficam em cache."""
    chave = chave_da_coluna(_chave_da_ligacao(tabela, data_source, None), fisica, coluna)
    achado = _da_cache([chave], limite)
    if chave in achado:
        return achado[chave]
    valores = valores_distintos(data_source, fisica, coluna, limite) or []
    _guardar(chave, valores, limite)
    return valores


def _categorico(valores: Optional[List[str]]) -> Optional[List[str]]:
    if not valores or len(valores) > MAX_DISTINTOS:
        return None
    return valores


def dominio_categorico(
    data_source: Any, fisica: str, coluna: str
) -> Optional[List[str]]:
    """Valores de uma coluna categórica, ou None (cardinalidade alta, vazia ou
    ilegível). Erros sobem: uma falha passageira não fica em cache."""
    try:
        valores = valores_distintos(data_source, fisica, coluna, MAX_DISTINTOS)
    except Exception as exc:
        log_event(
            "sample_values_profile_error",
            {"physical": fisica, "column": coluna, "error": str(exc)[:160]},
        )
        raise
    return _categorico(valores)


# ── Que colunas valem uma consulta ───────────────────────────────────────

#: Palavras de nome de coluna que dizem «texto livre»: moradas, horários,
#: códigos postais, URLs, contactos, fonte dos dados, hashes. Têm quase
#: sempre cardinalidade alta — a consulta era gasta para nada.
PALAVRAS_DE_TEXTO_LIVRE = {
    "direccion", "address", "morada", "endereco", "calle", "street",
    "horario", "schedule",
    "cp", "zip", "postal", "zipcode", "postcode",
    "url", "uri", "link", "web", "website",
    "email", "mail", "telefono", "telefone", "phone", "fax",
    "fonte", "fuente", "source",
    "hash", "uuid", "token", "json", "payload", "raw",
    "comment", "comments", "comentario", "comentarios", "notes", "notas",
    "observaciones", "observacoes",
}  # fmt: skip


def _palavras(texto: str) -> List[str]:
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return [p for p in re.split(r"[^a-z0-9]+", t) if p]


def e_texto_livre(nome: str) -> bool:
    return bool(set(_palavras(nome)) & PALAVRAS_DE_TEXTO_LIVRE)


def _pergunta_nomeia(nome: str, descricao: str, pergunta: set) -> bool:
    """A pergunta fala desta coluna (pelo nome ou por uma palavra da
    descrição, comparadas pelos 5 primeiros caracteres)."""
    if not pergunta:
        return False
    alvo = {p[:5] for p in _palavras(nome) if len(p) >= 3}
    alvo |= {p[:5] for p in _palavras(descricao) if len(p) >= 5}
    return bool(alvo & pergunta)


def anotar_valores(
    tabelas: Iterable[Any],
    data_source: Any,
    ligacao: Optional[str] = None,
    max_colunas_por_tabela: int = MAX_COLUNAS_POR_TABELA,
    pergunta: Optional[str] = None,
) -> Dict[str, List[str]]:
    """Põe ``sample_values`` em cada coluna de texto categórica de CADA tabela.

    Muta os dicts das colunas (são os mesmos objectos que o esquema do
    especialista lê). Devolve ``{"tabela.coluna": valores}`` do que ficou
    anotado, para registo. Nunca levanta.

    Ordem: cache local → Redis → consultas EM PARALELO para o que falta.
    """
    inicio = time.monotonic()
    da_pergunta = {p[:5] for p in _palavras(pergunta or "") if len(p) >= 3}
    anotadas: Dict[str, List[str]] = {}
    # (coluna, tabela física, chave da cache)
    alvos: List[Tuple[Any, str, str]] = []
    saltadas: List[str] = []
    for tabela in tabelas or []:
        fisica = getattr(tabela, "physical_name", None)
        if not fisica:
            continue
        chave_lig = _chave_da_ligacao(tabela, data_source, ligacao)
        candidatas: List[Tuple[int, int, Any]] = []
        for ordem, col in enumerate(getattr(tabela, "columns", None) or []):
            nome = _nome(col)
            if not nome or not e_coluna_de_texto(_tipo(col)):
                continue
            existentes = (
                col.get("sample_values")
                if isinstance(col, dict)
                else getattr(col, "sample_values", None)
            )
            if existentes:
                anotadas[f"{fisica}.{nome}"] = list(existentes)
                continue
            nomeada = _pergunta_nomeia(nome, _descricao(col), da_pergunta)
            if e_texto_livre(nome) and not nomeada:
                saltadas.append(f"{fisica}.{nome}")
                continue
            # As que a pergunta nomeia primeiro; depois pela ordem da tabela.
            candidatas.append((0 if nomeada else 1, ordem, col))
        candidatas.sort(key=lambda c: (c[0], c[1]))
        for _, _, col in candidatas[:max_colunas_por_tabela]:
            alvos.append((col, fisica, chave_da_coluna(chave_lig, fisica, _nome(col))))

    achados = _da_cache([a[2] for a in alvos], MAX_DISTINTOS)
    em_cache = len(achados)
    faltam = [a for a in alvos if a[2] not in achados]

    def ler(alvo: Tuple[Any, str, str]) -> Tuple[str, Optional[List[str]]]:
        col, fisica, chave = alvo
        try:
            valores = valores_distintos(data_source, fisica, _nome(col), MAX_DISTINTOS)
        except Exception as exc:
            log_event(
                "sample_values_profile_error",
                {"physical": fisica, "column": _nome(col), "error": str(exc)[:160]},
            )
            return chave, None
        valores = valores or []
        _guardar(chave, valores, MAX_DISTINTOS)
        return chave, valores

    if len(faltam) == 1:
        chave, valores = ler(faltam[0])
        if valores is not None:
            achados[chave] = valores
    elif faltam:
        # Cada tarefa leva a SUA cópia do contexto (tenant, registos): um
        # mesmo Context não pode correr em duas threads ao mesmo tempo.
        with ThreadPoolExecutor(max_workers=min(MAX_EM_PARALELO, len(faltam))) as ex:
            futuros = [
                ex.submit(contextvars.copy_context().run, ler, alvo) for alvo in faltam
            ]
            for futuro in futuros:
                chave, valores = futuro.result()
                if valores is not None:
                    achados[chave] = valores

    for col, fisica, chave in alvos:
        valores = _categorico(achados.get(chave))
        if not valores:
            continue
        if isinstance(col, dict):
            col["sample_values"] = valores
        else:
            try:
                setattr(col, "sample_values", valores)
            except Exception:
                continue
        anotadas[f"{fisica}.{_nome(col)}"] = valores

    log_event(
        "sample_values_timing",
        {
            "ms": round((time.monotonic() - inicio) * 1000),
            "columns": len(alvos),
            "cached": em_cache,
            "queried": len(faltam),
            "skipped_free_text": saltadas[:20],
        },
    )
    return anotadas


def limpar_cache() -> None:
    """Para os testes: esvazia a cache LOCAL (o Redis expira sozinho)."""
    with _CACHE_LOCK:
        _CACHE.clear()
    for k in estatisticas:
        estatisticas[k] = 0
