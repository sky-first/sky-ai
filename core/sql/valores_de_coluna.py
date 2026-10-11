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
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Iterable, List, Optional

from core.logging_utils import log_event

# Cache dos domínios, chave «ligação|tabela física|coluna». ``None`` marca uma
# coluna já vista e de cardinalidade alta, para não voltar a consultá-la. Os
# valores mudam pouco; a casa canónica disto é o enriquecimento na descoberta.
_CACHE: Dict[str, Optional[List[str]]] = {}
_CACHE_LOCK = threading.Lock()

# Só se mostram colunas categóricas — até 25 valores distintos.
MAX_DISTINTOS = 25
# Tecto por TABELA escolhida (não por pedido): uma tabela larga não pode
# deixar a seguinte sem valores.
MAX_COLUNAS_POR_TABELA = 20


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


def valores_distintos(
    data_source: Any, fisica: str, coluna: str, limite: int
) -> Optional[List[str]]:
    """Até ``limite`` valores distintos não nulos. Devolve a lista com
    ``limite + 1`` elementos quando há mais (quem chama decide), ``[]`` para
    coluna vazia e levanta a excepção da fonte se a consulta falhar."""
    sql = (
        f"SELECT DISTINCT {coluna} AS v FROM {fisica} "
        f"WHERE {coluna} IS NOT NULL LIMIT {limite + 1}"
    )
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


def dominio_categorico(
    data_source: Any, fisica: str, coluna: str
) -> Optional[List[str]]:
    """Valores de uma coluna categórica, ou None (cardinalidade alta, vazia ou
    ilegível). Erros NÃO ficam em cache: uma falha passageira não pode apagar
    os valores dessa coluna até ao próximo arranque."""
    try:
        valores = valores_distintos(data_source, fisica, coluna, MAX_DISTINTOS)
    except Exception as exc:
        log_event(
            "sample_values_profile_error",
            {"physical": fisica, "column": coluna, "error": str(exc)[:160]},
        )
        raise
    if not valores or len(valores) > MAX_DISTINTOS:
        return None
    return valores


def _chave_da_ligacao(tabela: Any, data_source: Any, ligacao: Optional[str]) -> str:
    return str(
        ligacao
        or getattr(tabela, "data_connection_id", None)
        or getattr(data_source, "connection_id", None)
        or f"ds{id(data_source)}"
    )


def anotar_valores(
    tabelas: Iterable[Any],
    data_source: Any,
    ligacao: Optional[str] = None,
    max_colunas_por_tabela: int = MAX_COLUNAS_POR_TABELA,
) -> Dict[str, List[str]]:
    """Põe ``sample_values`` em cada coluna de texto categórica de CADA tabela.

    Muta os dicts das colunas (são os mesmos objectos que o esquema do
    especialista lê). Devolve ``{"tabela.coluna": valores}`` do que ficou
    anotado, para registo. Nunca levanta.
    """
    anotadas: Dict[str, List[str]] = {}
    for tabela in tabelas or []:
        fisica = getattr(tabela, "physical_name", None)
        if not fisica:
            continue
        chave_lig = _chave_da_ligacao(tabela, data_source, ligacao)
        consultadas = 0
        for col in getattr(tabela, "columns", None) or []:
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
            chave = f"{chave_lig}|{fisica}|{nome}"
            with _CACHE_LOCK:
                em_cache = chave in _CACHE
                valores = _CACHE.get(chave)
            if not em_cache:
                if consultadas >= max_colunas_por_tabela:
                    continue
                consultadas += 1
                try:
                    valores = dominio_categorico(data_source, fisica, nome)
                except Exception:
                    continue
                with _CACHE_LOCK:
                    _CACHE[chave] = valores
            if not valores:
                continue
            if isinstance(col, dict):
                col["sample_values"] = valores
            else:
                try:
                    setattr(col, "sample_values", valores)
                except Exception:
                    continue
            anotadas[f"{fisica}.{nome}"] = valores
    return anotadas


def limpar_cache() -> None:
    """Para os testes."""
    with _CACHE_LOCK:
        _CACHE.clear()
