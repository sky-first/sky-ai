# -*- coding: utf-8 -*-
"""Perguntas que cruzam várias ligações: uma fatia por LIGAÇÃO, não por tabela.

Portão da Fase 0 das «Fontes do sistema» (desenho §3.7, decisão 4): perguntas
mistas — dados do cliente × dados públicos — passam pelo caminho multi-ligação
(``dispatch_map`` + merger DuckDB). A avaliação com as 10 perguntas do Anexo C
(``scripts/portao_fontes``) mostrou três defeitos estruturais, todos daqui:

1. **Uma fatia por tabela.** «Litros de Setembro em Badajoz–Madrid» precisa de
   ``ops.trips`` JOIN ``ops.routes`` — duas tabelas da MESMA ligação. Partido
   por tabela, cada metade era pedida sozinha: a de ``trips`` não sabe que rota
   é Badajoz–Madrid e a de ``routes`` não tem litros. O JOIN que o Postgres do
   cliente faz em 1 ms ficava a cargo do merger, sobre fatias já cortadas.
   Agora as tabelas escolhidas agrupam-se por ligação e cada ligação recebe
   UMA sub-pergunta com todas as suas tabelas: o SQL nativo junta o que é da
   mesma base, e o merger só junta o que não pode ser junto de outra forma.
2. **A fatia não sabia com que ia ser cruzada.** O especialista via a pergunta
   inteira e só as suas tabelas; agregava tudo (``SUM(fuel_litres)``) e deitava
   fora a chave (a data, a cidade) de que o merger precisava. Agora recebe o
   «contrato da fatia»: que outras fontes há, as colunas delas e as chaves
   prováveis de junção — devolve as linhas ao grão da chave.
3. **LIMIT 100.** O prompt do especialista exige ``LIMIT 100`` (uma tabela) ou
   ``150`` (várias). Uma fatia ao grão do dia (365 linhas num ano) era cortada
   em silêncio e o merger somava 100 dias. Para fatias o tecto é o do
   validador (5000) — ver ``LIMITE_DA_FATIA``.
"""

from __future__ import annotations

import concurrent.futures
import os
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from core.logging_utils import log_event

# ── Flag ──────────────────────────────────────────────────────────────────
#
# O caminho multi-ligação serve TODOS os clientes. Até o portão ser medido
# com os modelos de produção, a fatia por ligação (e o contrato, o LIMIT 5000,
# o merger novo e a reparação de fan-out) só liga para quem a flag disser:
#
#   MULTI_FONTE_POR_LIGACAO=true            → todos os clientes
#   MULTI_FONTE_POR_LIGACAO_TENANTS=sandbox → só estes slugs (vírgulas)
#
# Sem nenhuma das duas, o caminho de sempre (uma fatia por tabela), intacto.
_VERDADE = {"1", "true", "yes", "on", "sim"}


def multi_fonte_por_ligacao_ativo(slug: Optional[str] = None) -> bool:
    if (os.environ.get("MULTI_FONTE_POR_LIGACAO") or "").strip().lower() in _VERDADE:
        return True
    clientes = {
        s.strip()
        for s in (os.environ.get("MULTI_FONTE_POR_LIGACAO_TENANTS") or "").split(",")
        if s.strip()
    }
    if not clientes:
        return False
    if slug is None:
        try:
            from core.tenant_context import current_tenant

            slug = current_tenant().slug
        except Exception:
            return False
    return slug in clientes


# O tecto do AdvancedSQLValidator (max_limit=5000). Uma fatia tem de caber
# inteira no merger: cortá-la dá números errados sem aviso.
LIMITE_DA_FATIA = 5000

# Colunas que aparecem em quase todas as tabelas e não são chave de nada.
_COLUNAS_GENERICAS = {
    "id",
    "fonte",
    "licenca",
    "nota",
    "descricao",
    "description",
    "name",
    "nome",
    "created_at",
    "updated_at",
    "actualizado_em",
    "visto_em",
    "calculado_em",
    "estado",
    "status",
    "lat",
    "lon",
    "versao",
}

# Sinónimos entre as línguas das bases (a sementeira é em inglês, o mundo em
# português). Grupo → nomes de coluna que querem dizer o mesmo.
_SINONIMOS: Tuple[Tuple[str, ...], ...] = (
    ("origin", "origem", "origen", "cidade", "ciudad", "city"),
    ("destination", "destino", "cidade", "ciudad", "city"),
    ("province", "provincia", "província"),
    ("country", "pais", "país"),
    ("road", "carretera", "estrada", "corredor"),
    ("municipality", "municipio", "município", "localidad"),
)

_RE_DATA = re.compile(r"\b(date|data|fecha|dia|day)\b", re.I)
_TIPOS_DATA = ("date",)
_TIPOS_TEMPO = ("timestamp", "datetime", "timestamptz")


def _sem_acentos(s: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", s or "")
        if not unicodedata.combining(c)
    ).lower()


def _rotulo(t: Any) -> str:
    return getattr(t, "display_name", None) or getattr(t, "logical_name", "")


def _colunas(t: Any) -> List[Dict[str, Any]]:
    cols = getattr(t, "columns", None) or []
    out = []
    for c in cols:
        if isinstance(c, dict):
            out.append(c)
        else:  # objectos com atributos
            out.append(
                {
                    "name": getattr(c, "name", ""),
                    "type": getattr(c, "type", "") or getattr(c, "data_type", ""),
                    "description": getattr(c, "description", "") or "",
                }
            )
    return out


@dataclass
class Fatia:
    """As tabelas escolhidas de UMA ligação."""

    connection_id: str
    tabelas: List[Any] = field(default_factory=list)
    rotulo_fonte: str = ""

    @property
    def rotulos(self) -> List[str]:
        return [_rotulo(t) for t in self.tabelas]

    @property
    def fisicas(self) -> List[str]:
        return [t.physical_name for t in self.tabelas]


def agrupar_por_ligacao(
    escolhidas: Sequence[str], agent_config: Any, dispatch_map: Optional[dict] = None
) -> List[Fatia]:
    """Agrupa as tabelas escolhidas pela ligação a que pertencem, por ordem."""
    por_ligacao: Dict[str, Fatia] = {}
    for nome in escolhidas or []:
        t = next((x for x in agent_config.tables if _rotulo(x) == nome), None)
        if t is None:
            continue
        cid = str(getattr(t, "data_connection_id", "") or "")
        if cid not in por_ligacao:
            src = (dispatch_map or {}).get(cid)
            por_ligacao[cid] = Fatia(
                connection_id=cid,
                rotulo_fonte=str(getattr(src, "label", "") or cid or "principal"),
            )
        if t not in por_ligacao[cid].tabelas:
            por_ligacao[cid].tabelas.append(t)
    return list(por_ligacao.values())


# ── chaves de junção ──────────────────────────────────────────────────────


def _grupo(nome: str) -> Optional[int]:
    n = _sem_acentos(nome)
    for i, g in enumerate(_SINONIMOS):
        if n in g:
            return i
    return None


def _e_data(col: Dict[str, Any]) -> bool:
    tipo = str(col.get("type") or "").lower()
    return any(k in tipo for k in _TIPOS_DATA) and not any(
        k in tipo for k in _TIPOS_TEMPO
    )


def _e_tempo(col: Dict[str, Any]) -> bool:
    tipo = str(col.get("type") or "").lower()
    return any(k in tipo for k in _TIPOS_TEMPO)


def _referencias(desc: str) -> List[str]:
    """«= ops.routes.origin» / «FK gasolineras_precio.id_estacion» → colunas."""
    out = []
    for m in re.finditer(
        r"(?:=|FK)\s*([a-z_][\w]*(?:\.[a-z_][\w]*){1,2})", desc or "", re.I
    ):
        out.append(m.group(1).lower())
    return out


def _e_a_tabela(entidade: str, rotulo: str, fisica: str) -> bool:
    """«trip» é a tabela ``trips`` / ``ops.trips``; «category» é ``categories``."""
    if not entidade:
        return False
    nomes = {
        _sem_acentos(str(rotulo or "")).split(".")[-1],
        _sem_acentos(str(fisica or "")).split(".")[-1].strip('"`[]'),
    }
    formas = {entidade, entidade + "s", entidade + "es"}
    if entidade.endswith("y"):
        formas.add(entidade[:-1] + "ies")
    return bool(nomes & formas)


def pistas_de_juncao(a: Sequence[Any], b: Sequence[Any]) -> List[str]:
    """Pares de colunas prováveis para juntar as tabelas ``a`` com as ``b``.

    Por ordem de confiança: referência documentada na descrição da coluna
    («= ops.routes.origin», como o esquema ``mundo`` escreve), mesmo nome,
    sinónimo entre línguas (origin ~ origem), e data civil × instante
    (``CAST(departed_at AS DATE) = data``). Cada par de colunas aparece uma
    vez; cada coluna de data recebe só o PRIMEIRO instante de cada tabela
    (a ordem das colunas é a do esquema: ``departed_at`` antes de
    ``arrived_at``) — doze variantes da mesma data afogavam o resto.
    """
    documentadas: List[str] = []
    nomes: List[str] = []
    datas: List[str] = []
    vistos: set = set()

    def add(lista: List[str], x: str, y: str, texto: str) -> None:
        chave = frozenset((x.lower(), y.lower()))
        if chave in vistos:
            return
        vistos.add(chave)
        lista.append(texto)

    for ta in a:
        for tb in b:
            ca, cb = _colunas(ta), _colunas(tb)
            na, nb = _rotulo(ta), _rotulo(tb)
            fa = str(getattr(ta, "physical_name", na)).lower()
            fb = str(getattr(tb, "physical_name", nb)).lower()
            # 1) referências documentadas
            for cols_x, tab_x, tab_y, cols_y, fis_y in (
                (ca, na, nb, cb, fb),
                (cb, nb, na, ca, fa),
            ):
                for c in cols_x:
                    for ref in _referencias(str(c.get("description") or "")):
                        alvo_tab, _, alvo_col = ref.rpartition(".")
                        if fis_y.endswith(alvo_tab.split(".")[-1]) and any(
                            str(y.get("name")).lower() == alvo_col for y in cols_y
                        ):
                            x, y = f"{tab_x}.{c.get('name')}", f"{tab_y}.{alvo_col}"
                            add(documentadas, x, y, f"{x} = {y}")
            # 1b) chave estrangeira pela convenção de nomes: «trip_id» de
            # ``shipments`` é o «id» de ``trips``. Produção 14/10/2026: «id»
            # está nas colunas genéricas e por isso esta chave NUNCA era
            # sugerida — a fatia de ``ops`` agregava por rota, a de
            # ``freight`` por cliente, e o merger ficava sem nada com que as
            # cruzar: «gasóleo en vacío» recusado, «€ por km» estimado por
            # proporção (números inventados).
            for cols_x, tab_x, cols_y, tab_y, fis_y in (
                (ca, na, cb, nb, fb),
                (cb, nb, ca, na, fa),
            ):
                if not any(
                    _sem_acentos(str(y.get("name") or "")) == "id" for y in cols_y
                ):
                    continue
                for c in cols_x:
                    xn = _sem_acentos(str(c.get("name") or ""))
                    if xn.endswith("_id") and _e_a_tabela(xn[:-3], tab_y, fis_y):
                        x, y = f"{tab_x}.{c.get('name')}", f"{tab_y}.id"
                        add(
                            documentadas,
                            x,
                            y,
                            f"{x} = {y} (foreign key: keep {c.get('name')} / "
                            f"the {tab_y} id in the SELECT)",
                        )
            # 2) mesmo nome / 3) sinónimo
            for c in ca:
                xn = str(c.get("name") or "")
                if not xn or _sem_acentos(xn) in _COLUNAS_GENERICAS:
                    continue
                for d in cb:
                    yn = str(d.get("name") or "")
                    if not yn or _sem_acentos(yn) in _COLUNAS_GENERICAS:
                        continue
                    x, y = f"{na}.{xn}", f"{nb}.{yn}"
                    if _sem_acentos(xn) == _sem_acentos(yn):
                        add(nomes, x, y, f"{x} = {y}")
                    elif _grupo(xn) is not None and _grupo(xn) == _grupo(yn):
                        add(
                            nomes, x, y, f"{x} = {y} (same meaning, different language)"
                        )
            # 4) data civil × instante (um instante por tabela)
            for cols_x, tab_x, cols_y, tab_y in ((ca, na, cb, nb), (cb, nb, ca, na)):
                instante = next((d for d in cols_y if _e_tempo(d)), None)
                if instante is None:
                    continue
                for c in cols_x:
                    if _e_data(c):
                        x, y = (
                            f"{tab_x}.{c.get('name')}",
                            f"{tab_y}.{instante.get('name')}",
                        )
                        add(datas, x, y, f"{x} = CAST({y} AS DATE) (day grain)")
    return (documentadas + nomes + datas)[:12]


def _resumo_tabela(t: Any, max_cols: int = 25) -> str:
    cols = []
    for c in _colunas(t)[:max_cols]:
        nome = c.get("name")
        tipo = c.get("type") or ""
        desc = str(c.get("description") or "").strip()
        cols.append(f"{nome} {tipo}".strip() + (f" — {desc[:80]}" if desc else ""))
    return f"  • {_rotulo(t)} ({getattr(t, 'physical_name', '')}): " + "; ".join(cols)


# ── As definições da casa (15/10/2026) ───────────────────────────────────
#
# O backend põe nas instruções as métricas e o glossário do espaço
# («# Trusted metrics», «# Glossary»). Só o orquestrador e o formatador as
# liam: quem ESCREVE o SQL — as fatias e o merger — nunca as via. Resultado
# no sandbox «Logística y Transporte», 15/10:
#
#   * «¿Qué rutas tienen el mayor porcentaje de portes fuera de plazo?» —
#     a fatia de Operaciones contou «arrived_at > planned_arrival», sem a
#     tolerância do cliente (que vive em Carga): Porto→Madrid 94,38 %
#     quando a métrica «Portes fuera de plazo» dá 64,3 %, e 18 rotas acima
#     de 55 % quando a verdade é ≤ 6,9 %;
#   * «¿Qué vehículos no se pagan?» — a fatia de Operaciones devolveu
#     portagens por rota em vez das viagens, e o merger acabou a filtrar
#     «fixed_cost_month = 0»: 0 linhas e «todos generan una aportación
#     positiva», quando a métrica dá 03-GH-19 com −15.936 €.

_SECCAO_DE_CONHECIMENTO = re.compile(
    r"^#[ \t]*(?:Trusted metrics|Glossary)[^\n]*\n(.*?)(?=^#|\Z)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)


def _tokens_de(texto: str) -> set:
    return {
        t for t in re.split(r"[^\w]+", _sem_acentos(texto or "").lower()) if len(t) >= 4
    }


def definicoes_do_espaco(
    instrucoes: Optional[str], pergunta: Optional[str] = None, limite: int = 3500
) -> str:
    """As métricas e os termos do glossário do espaço, para quem escreve SQL.

    Só as linhas das secções de métricas e de glossário (o resto das
    instruções são pedidos de estilo). Se não couberem todas em ``limite``
    caracteres, primeiro as que partilham palavras com a pergunta; a ordem
    original mantém-se."""
    linhas: List[str] = []
    for bloco in _SECCAO_DE_CONHECIMENTO.findall(instrucoes or ""):
        for linha in bloco.splitlines():
            linha = linha.strip()
            if linha.startswith(("-", "*")) and len(linha) > 3:
                linhas.append(linha)
    if not linhas:
        return ""
    if sum(len(x) + 1 for x in linhas) > limite:
        da_pergunta = _tokens_de(pergunta or "")
        ordem = sorted(
            range(len(linhas)),
            key=lambda i: (-len(_tokens_de(linhas[i]) & da_pergunta), i),
        )
        escolhidas, total = set(), 0
        for i in ordem:
            if total + len(linhas[i]) + 1 > limite:
                continue
            escolhidas.add(i)
            total += len(linhas[i]) + 1
        linhas = [linhas[i] for i in sorted(escolhidas)]
    return "\n".join(linhas)


def contrato_da_fatia(
    fatia: Fatia, outras: Sequence[Fatia], definicoes: str = ""
) -> str:
    """O que a fatia tem de devolver para o merger a conseguir cruzar."""
    outras_tabs = [t for f in outras for t in f.tabelas]
    linhas = [
        "MULTI-SOURCE SLICE CONTRACT (mandatory):",
        f"This query is ONE slice of a question that spans {len(outras) + 1} separate "
        "databases. You only see the tables of THIS database. A later step (DuckDB, in "
        "memory) joins your result with the results of the other databases:",
    ]
    for f in outras:
        for t in f.tabelas:
            linhas.append(_resumo_tabela(t))
    pistas = pistas_de_juncao(fatia.tabelas, outras_tabs)
    if pistas:
        linhas.append("Likely join keys between your tables and theirs:")
        linhas += [f"  - {p}" for p in pistas]
    linhas += [
        "Rules for this slice:",
        "1. Do NOT answer the whole question and do NOT refuse it: return what THIS "
        "database contributes (its measures, filtered by what belongs to it).",
        "2. KEEP the join key columns in the SELECT, unchanged in meaning (city names, "
        "dates as DATE, ids). Without them the other databases cannot be matched.",
        "3. Pre-aggregate at the join-key grain (GROUP BY the key columns) instead of "
        "returning raw rows; e.g. litres per route, trips per day.",
        "4. Apply the filters that belong to THIS database (period, route, vehicle "
        "class...). Never filter on values that only exist in the other databases.",
        "5. You MAY join the tables of THIS database with each other, but use only "
        "the ones the question needs.",
        f"6. End with LIMIT {LIMITE_DA_FATIA} (not 100): the slice must arrive whole.",
        # Portão 14/10/2026 (P6): «festivo regional de Extremadura» trazia também
        # os nacionais (regiao IS NULL) — 32 viagens em vez de 6.
        "7. Geographic level: use exactly the level the question names. Rows of a "
        "wider area (national rows with region NULL, a country total) are NOT rows of "
        "a narrower one: 'a regional holiday of X' is region = X only, never "
        "'region = X OR region IS NULL'. Include national rows only when the question "
        "asks for them ('national or regional', 'any holiday').",
        # P3: «rota sem portagem» filtrava troços (gratuita = TRUE) e deixava
        # passar Lisboa–Madrid, que tem um troço pago.
        "8. A property of a whole entity that THIS database stores as several rows "
        "(a route made of sections, an order made of lines) must hold for ALL its rows "
        "('the route has no toll' = every section toll-free). GROUP BY the entity key "
        "exactly as the other databases know it (the join key columns, e.g. origin and "
        "destination), NOT by finer columns of yours (section, corridor, segment id), "
        "and return the property as a column computed with bool_and()/bool_or()/MIN()/"
        "MAX(). Do not filter on it (no WHERE on the rows, no HAVING): a row filter "
        "keeps an entity when only some of its rows match, and the join step needs "
        "the flag to apply the condition itself.",
        # P10: a fatia pública usava gasolineras_rota como lista de rotas e o
        # merger só via 5 das 7 rotas do cliente.
        "9. Never stand in for an entity that lives in another database (do not use "
        "a list of routes, places or products from THIS database as if it were the "
        "client's list). Return your facts at the grain of the shared key (e.g. per "
        "city, per day); the join step matches them to the client's entities. When "
        "the question says 'X or Y' (origin or destination), keep the key itself "
        "(the city), not a pair.",
        # Produção 14/10/2026: a fatia `products` (Cocina) escreveu um JOIN a
        # uma subconsulta sobre a própria tabela e uma frase depois do SQL;
        # chumbou no validador e a resposta saiu sem a família de produto.
        "10. A table of THIS database that only describes entities (products, "
        "stores, customers, employees) comes WHOLE: its key and only the descriptive "
        "columns the question needs (e.g. id, name, family), with no JOIN, no "
        "subquery, no GROUP BY and no filter based on another table (a period in the "
        "question never applies to it). The join step keeps only the entities that "
        "match.",
        "11. Output only the SQL after the TITLE line: no explanations, notes or "
        "plain text after the SQL.",
        # Produção 14/10/2026: «¿Cuánto gasóleo quemamos en vacío?» — a fatia
        # de viagens agrupou por rota e deitou fora o id da viagem; o merger
        # não conseguia saber que viagens não tinham porte. «¿Qué clientes
        # dejan más por kilómetro?» — a fatia de portes agrupou por cliente
        # sem trip_id e o merger repartiu os km por proporção.
        "12. When a likely join key is a foreign key (x_id = other_table.id), that "
        "key IS the grain: keep it in the SELECT and GROUP BY it (or return one row "
        "per key), never only by a coarser attribute (route, client, month). A "
        "coarser GROUP BY destroys the link and the join step can no longer match "
        "rows, nor find the ones that have NO match in the other database (e.g. trips "
        "without any shipment). When another database points AT your table "
        "(their trip_id = your trips.id), your own id is a join key too: return one "
        "row per id (with your other foreign keys, e.g. vehicle_id, as columns) "
        "instead of grouping by one of your foreign keys.",
        # Prova 15/10/2026, «¿Qué vehículos no se pagan?»: a fatia da frota
        # filtrava «fixed_cost_month = 0» e a dos portes «revenue = 0» — cada
        # uma tentou decidir sozinha uma condição que compara as duas.
        "13. A condition that compares measures living in different databases "
        "(revenue vs cost, 'pays for itself', 'loses money', margin, 'more than') "
        "can only be decided by the join step. Never filter on it here (no WHERE, "
        "no HAVING on your measures): return every entity with ALL the measures of "
        "THIS database that enter the comparison (costs: fixed cost, workshop cost, "
        "hours × cost per hour…; revenue), aggregated per join key.",
        # Produção 16/10/2026, «¿Cuáles son los 10 productos más vendidos este
        # año?» (Alimentación): order_lines.lot_id → lots.id → products. A
        # fatia do armazém devolveu «SUM(lots.quantity) GROUP BY product_id
        # WHERE received_on este ano» — sem o id do lote, o merger não tinha
        # ponte entre as vendas (por lote) e o catálogo e respondeu «Lote 81:
        # 5.790 unidades», ou somou as quantidades RECEBIDAS como se fossem
        # vendidas.
        "15. A table of THIS database that another database points at (their lot_id "
        "= your lots.id) and that itself points at a third one (your product_id = "
        "their products.id) is the BRIDGE between them: return it at its own grain — "
        "one row per id, with its foreign keys (e.g. id AS lot_id, product_id) and "
        "only the descriptive columns the question needs. No GROUP BY by one of its "
        "foreign keys, and no period filter on its own dates: the period in the "
        "question belongs to the facts (the orders), not to the bridge. Its own "
        "measures (quantity received, stock) are NOT the measure the question asks "
        "for (units sold) unless the question names them.",
        "16. Never pick a top-N (ORDER BY … LIMIT 10) in a slice whose rows the join "
        "step still has to combine or regroup (per lot when the question asks per "
        "product): the ranking is decided AFTER the join. Keep LIMIT "
        f"{LIMITE_DA_FATIA}.",
    ]
    if definicoes:
        # 15/10/2026: «fuera de plazo» contado sem a tolerância do cliente.
        linhas += [
            "17. The BUSINESS DEFINITIONS below are how this company computes its "
            "terms. When the question uses one of them ('fuera de plazo', 'no se "
            "paga', 'vacío'…), the condition is exactly the one in the definition — "
            "never a simpler version (e.g. 'late' is NOT arrived > planned when the "
            "definition adds the client's tolerance). If the definition needs a column "
            "that lives in another database (the client's tolerance, the revenue, the "
            "workshop cost), do NOT decide the condition here and do NOT compute a "
            "partial version of it: return its inputs from THIS database (timestamps, "
            "measures, the ids that link to the other databases) at the key grain, and "
            "the join step applies the definition.",
            "BUSINESS DEFINITIONS (from the space's trusted metrics and glossary):",
            definicoes,
        ]
    return "\n".join(linhas)


# ── o que a fatia devolveu: defeitos que o merger já não consegue corrigir ─
#
# As regras 12, 15 e 16 do contrato são pedidos ao modelo; nem sempre as
# cumpre (produção 16/10/2026, «10 productos más vendidos»: a fatia do
# armazém agregou por product_id e deitou fora o id do lote; a do comercial
# cortou em LIMIT 10 lotes antes de se saber que produtos eram). O merger
# fica sem a ponte e responde por lote — ou com a medida errada — e alterna
# de pedido para pedido. Estes defeitos vêem-se no RESULTADO, sem LLM: as
# colunas que a fatia devolveu e as que as outras devolveram.

_LIMIT_FINAL = re.compile(r"\bLIMIT\s+(\d+)\s*;?\s*$", re.IGNORECASE)


def _colunas_do_resultado(dados: Any) -> List[str]:
    if isinstance(dados, list) and dados and isinstance(dados[0], dict):
        return [str(c) for c in dados[0].keys()]
    return []


def _nome_curto(t: Any) -> Tuple[str, str]:
    return (
        _sem_acentos(str(_rotulo(t) or "")).split(".")[-1],
        _sem_acentos(str(getattr(t, "physical_name", "") or ""))
        .split(".")[-1]
        .strip('"`[]'),
    )


def _identifica(coluna: str, tabela: Any, fk: str) -> bool:
    """A coluna do resultado é o id desta tabela? (``id``, a própria chave
    estrangeira que a aponta, ou ``<entidade>_id`` da tabela)."""
    c = _sem_acentos(coluna)
    if c in {"id", _sem_acentos(fk)}:
        return True
    rotulo, fisica = _nome_curto(tabela)
    return c.endswith("_id") and _e_a_tabela(c[:-3], rotulo, fisica)


def defeitos_da_fatia(
    fatia: Fatia,
    resultado: Dict[str, Any],
    outros: Sequence[Tuple[Fatia, Dict[str, Any]]],
) -> List[str]:
    """Porque é que o resultado desta fatia não deixa o merger juntar, ou []."""
    defeitos: List[str] = []
    colunas = _colunas_do_resultado(resultado.get("data"))
    if not colunas:
        return defeitos
    # (a) outra fatia devolveu «x_id» que aponta para uma tabela DESTA, e
    # esta não devolveu o id dessa tabela: não há com que juntar.
    vistos: set = set()
    for _outra, r_outra in outros:
        for c in _colunas_do_resultado(r_outra.get("data")):
            cn = _sem_acentos(c)
            if not cn.endswith("_id"):
                continue
            for t in fatia.tabelas:
                rotulo, fisica = _nome_curto(t)
                if not _e_a_tabela(cn[:-3], rotulo, fisica):
                    continue
                if any(_identifica(x, t, c) for x in colunas):
                    continue
                # Só é PONTE perdida se a fatia usou a tabela como ponte:
                # devolveu uma chave estrangeira DELA (lots.product_id) sem o
                # id. Uma tabela-irmã que a fatia nem usou (drivers, ao lado
                # de vehicles) não conta — exigir-lhe o id fazia o modelo
                # cruzar vehicles × drivers (8 × 6 = 48 linhas, prova 16/10).
                fks_de_t = {
                    _sem_acentos(str(col.get("name") or ""))
                    for col in _colunas(t)
                    if _sem_acentos(str(col.get("name") or "")).endswith("_id")
                }
                if not fks_de_t & {_sem_acentos(x) for x in colunas}:
                    continue
                if (cn, rotulo) in vistos:
                    continue
                vistos.add((cn, rotulo))
                defeitos.append(
                    f"another database returned {c} (= your {_rotulo(t)}.id), but your "
                    f"result has no {_rotulo(t)} id column (it returned {colunas}): the "
                    f"join step cannot link the two. Return one row per {_rotulo(t)}.id "
                    f"(SELECT id AS {c}, plus its other foreign keys as columns) — no "
                    "GROUP BY by another column, no period filter on its own dates "
                    "(rules 12 and 15)."
                )
    # (b) top-N cortado antes da junção.
    if outros:
        m = _LIMIT_FINAL.search(str(resultado.get("sql") or "").strip())
        if m:
            n = int(m.group(1))
            linhas = len(resultado.get("data") or [])
            if n < LIMITE_DA_FATIA and linhas >= n:
                defeitos.append(
                    f"your query ended with LIMIT {n} and returned exactly {linhas} "
                    "rows: the slice was cut before the other databases were joined, "
                    "and the ranking is only known after the join. Return every row "
                    f"at the join-key grain and end with LIMIT {LIMITE_DA_FATIA} "
                    "(rule 16)."
                )
    return defeitos


def _corrigir_fatias_com_defeito(
    resultados: List[Dict[str, Any]],
    por_ligacao: Dict[str, Tuple[Fatia, Dict[str, Any], Any]],
    agent_config: Any,
    llm: Any,
    run_specialist: Callable,
) -> List[Dict[str, Any]]:
    """UMA nova tentativa, em paralelo, para cada fatia com defeito; fica a
    nova só se trouxer linhas e menos defeitos."""
    pares = [(por_ligacao[r["connection_id"]][0], r) for r in resultados]
    a_corrigir = []
    for i, (f, r) in enumerate(pares):
        outros = [p for j, p in enumerate(pares) if j != i]
        defeitos = defeitos_da_fatia(f, r, outros)
        if defeitos:
            a_corrigir.append((i, f, r, outros, defeitos))
    if not a_corrigir:
        return resultados

    def _de_novo(item):
        i, f, r, outros, defeitos = item
        _, st, src = por_ligacao[f.connection_id]
        log_event(
            "multi_fonte_fatia_com_defeito",
            {
                "connection_id": f.connection_id,
                "tables": f.rotulos,
                "defeitos": [d[:200] for d in defeitos],
                "sql": str(r.get("sql") or "")[:300],
            },
        )
        st2 = dict(st)
        st2["feedback_da_fatia"] = feedback_da_fatia(r.get("sql"), " ".join(defeitos))
        try:
            novo = run_specialist(st2, agent_config, src, llm)
        except Exception as exc:  # noqa: BLE001 — fica a primeira
            log_event(
                "multi_fonte_fatia_correcao_erro",
                {"connection_id": f.connection_id, "error": str(exc)[:300]},
            )
            return i, None
        if not novo.get("data"):
            return i, None
        restantes = defeitos_da_fatia(f, novo, outros)
        aceite = len(restantes) < len(defeitos)
        log_event(
            "multi_fonte_fatia_correcao",
            {
                "connection_id": f.connection_id,
                "aceite": aceite,
                "rows": len(novo.get("data") or []),
                "sql": str(novo.get("sql") or "")[:300],
            },
        )
        return i, (novo if aceite else None)

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(len(a_corrigir), 5)
    ) as ex:
        for i, novo in ex.map(_de_novo, a_corrigir):
            if novo is None:
                continue
            r = dict(resultados[i])
            r["data"] = novo["data"]
            r["sql"] = novo.get("sql")
            meta = dict(r.get("metadata") or {})
            meta["title"] = novo.get("generated_title") or meta.get("title")
            meta["possivelmente_cortada"] = len(novo["data"]) >= LIMITE_DA_FATIA
            r["metadata"] = meta
            resultados[i] = r
    return resultados


# ── execução ──────────────────────────────────────────────────────────────


def _rotulo_da_fonte(src: Any, cid: str) -> str:
    return str(getattr(src, "label", "") or cid or "principal")


def feedback_da_fatia(sql: Optional[str], erro: str) -> str:
    """O que a nova tentativa de uma fatia recebe: o SQL que falhou e porquê."""
    return (
        "PREVIOUS ATTEMPT FAILED - this is your second and last attempt.\n"
        f"The SQL you wrote:\n{(sql or '(no SQL)')[:1500]}\n"
        f"was rejected with this error:\n{str(erro)[:400]}\n"
        "Write a corrected query for THIS slice: a single SELECT/WITH statement "
        "that reads only the tables of this database, keeps the join key columns "
        "and follows the slice contract. Output the SQL only (after the TITLE "
        "line): no explanations, notes or plain text after the SQL."
    )


def _correr_com_nova_tentativa(
    run_specialist: Callable,
    fatia: Fatia,
    st: Dict[str, Any],
    agent_config: Any,
    src: Any,
    llm: Any,
) -> Dict[str, Any]:
    """Corre a fatia; se falhar por erro de validação/execução, mais UMA vez
    com o erro como feedback ao especialista.

    Produção 14/10/2026: a fatia ``products`` chumbou no validador («Table
    'step' is not allowed») e foi dada como perdida à primeira — a resposta
    saiu sem a família de produto. Um ``IMPOSSIBLE`` não é erro (o guardrail
    tem a sua própria nova tentativa) e uma excepção (fonte em baixo) também
    não: nesses casos não se tenta outra vez.
    """
    r = run_specialist(dict(st), agent_config, src, llm)
    if r.get("data") or r.get("impossible_reason") or not r.get("error"):
        return r
    log_event(
        "multi_fonte_fatia_nova_tentativa",
        {
            "connection_id": fatia.connection_id,
            "tables": fatia.rotulos,
            "error": str(r.get("error"))[:300],
        },
    )
    st2 = dict(st)
    st2["feedback_da_fatia"] = feedback_da_fatia(r.get("sql"), r.get("error"))
    try:
        r2 = run_specialist(st2, agent_config, src, llm)
    except Exception as exc:
        log_event(
            "multi_fonte_fatia_nova_tentativa_erro",
            {"connection_id": fatia.connection_id, "error": str(exc)[:300]},
        )
        return r
    log_event(
        "multi_fonte_fatia_nova_tentativa_resultado",
        {
            "connection_id": fatia.connection_id,
            "has_data": bool(r2.get("data")),
            "error": r2.get("error"),
        },
    )
    return r2


def executar_fatias(
    state: Dict[str, Any],
    agent_config: Any,
    escolhidas: Sequence[str],
    dispatch_map: Optional[dict],
    data_source: Any,
    llm: Any,
    run_specialist: Optional[Callable] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Uma sub-pergunta por ligação, em paralelo.

    Devolve ``(partial_results, fontes_publicas, failed_slices)``. Cada
    parcial leva a ligação, as tabelas e as descrições das colunas — o merger
    usa-as para explicar ao modelo o que cada conjunto é e como se junta.
    ``failed_slices`` (``[{table, reason}]``, como no caminho de sempre) diz
    que ligações não trouxeram dados: o merger não as inventa e a resposta
    di-lo (MULTI_SOURCE_PARTIAL / MULTI_SOURCE_*).
    """
    if run_specialist is None:
        from core.llm.specialist import run_specialist as _rs

        run_specialist = _rs

    fatias = agrupar_por_ligacao(escolhidas, agent_config, dispatch_map)
    definicoes = definicoes_do_espaco(state.get("instructions"), state.get("question"))
    tarefas = []
    por_ligacao: Dict[str, Tuple[Fatia, Dict[str, Any], Any]] = {}
    for f in fatias:
        outras = [o for o in fatias if o is not f]
        st = dict(state)
        st["chosen_tables"] = f.rotulos
        st["chosen_tables_physical"] = f.fisicas
        st["chosen_table"] = f.rotulos[0]
        st["chosen_table_physical"] = f.fisicas[0]
        st["join_relationships"] = None
        st["multi_source_subquery"] = True
        st["contrato_da_fatia"] = contrato_da_fatia(f, outras, definicoes)
        st["is_multi_source"] = False
        src = (dispatch_map or {}).get(f.connection_id) or data_source
        tarefas.append((f, st, src))
        por_ligacao[f.connection_id] = (f, st, src)

    resultados: List[Dict[str, Any]] = []
    fontes: List[Dict[str, Any]] = []
    falhadas: List[Dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(max(len(tarefas), 1), 5)
    ) as ex:
        futuros = {
            ex.submit(
                _correr_com_nova_tentativa,
                run_specialist,
                f,
                st,
                agent_config,
                src,
                llm,
            ): (f, src)
            for (f, st, src) in tarefas
        }
        for fut in concurrent.futures.as_completed(futuros):
            f, src = futuros[fut]
            try:
                r = fut.result()
            except Exception as exc:  # uma fonte em baixo não deita a resposta
                log_event(
                    "multi_fonte_fatia_erro",
                    {"connection_id": f.connection_id, "error": str(exc)[:300]},
                )
                falhadas.append(
                    {
                        "table": ", ".join(f.rotulos),
                        "connection_id": f.connection_id,
                        "reason": str(exc)[:300],
                    }
                )
                continue
            log_event(
                "multi_source_subquery_result",
                {
                    "connection_id": f.connection_id,
                    "tables": f.rotulos,
                    "has_data": bool(r.get("data")),
                    "rows": len(r.get("data") or []),
                    "sql": (r.get("sql") or "")[:300],
                    "error": r.get("error"),
                    "impossible_reason": r.get("impossible_reason"),
                },
            )
            if r.get("fontes_publicas"):
                fontes += list(r["fontes_publicas"])
            if not r.get("data"):
                if r.get("impossible_reason"):
                    motivo = str(r.get("impossible_reason"))
                elif r.get("error"):
                    motivo = str(r.get("error"))
                elif r.get("sql"):
                    motivo = "query ran and returned 0 rows"
                else:
                    motivo = "no SQL was produced"
                falhadas.append(
                    {
                        "table": ", ".join(f.rotulos),
                        "connection_id": f.connection_id,
                        "reason": motivo[:300],
                    }
                )
                continue
            # Uma fatia que bate no tecto pode estar cortada: o merger tem de
            # o saber (e a resposta também) em vez de somar um subconjunto
            # como se fosse tudo.
            cortada = len(r["data"]) >= LIMITE_DA_FATIA
            if cortada:
                log_event(
                    "multi_fonte_fatia_no_limite",
                    {"connection_id": f.connection_id, "rows": len(r["data"])},
                )
            resultados.append(
                {
                    "table": ", ".join(f.rotulos),
                    "tables": f.rotulos,
                    "connection_id": f.connection_id,
                    "data": r["data"],
                    "sql": r.get("sql"),
                    "metadata": {
                        "source": _rotulo_da_fonte(src, f.connection_id),
                        "title": r.get("generated_title"),
                        "dialect": str(
                            getattr(getattr(src, "dialect", None), "value", "") or ""
                        ),
                        "descricoes": {
                            str(c.get("name")): str(c.get("description") or "")
                            for t in f.tabelas
                            for c in _colunas(t)
                            if c.get("description")
                        },
                        "possivelmente_cortada": cortada,
                    },
                }
            )
    # ordem estável (a do agrupamento), para o merger e para os testes
    ordem = {f.connection_id: i for i, f in enumerate(fatias)}
    resultados.sort(key=lambda r: ordem.get(r["connection_id"], 99))
    if len(resultados) >= 2:
        resultados = _corrigir_fatias_com_defeito(
            resultados, por_ligacao, agent_config, llm, run_specialist
        )
    falhadas.sort(key=lambda r: ordem.get(r["connection_id"], 99))
    from core.llm.fontes_publicas import juntar

    return resultados, juntar(fontes), falhadas
