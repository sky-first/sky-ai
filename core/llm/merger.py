"""Merger do caminho multi-fonte: junta as fatias de cada ligação no DuckDB.

Produção, 13/10/2026 — tenant sandbox, «¿Qué tienda tuvo más pedidos el
último mes?» com ``orders`` (schema service) e ``stores`` (schema stores):

1. As fatias eram registadas no DuckDB como ``dataset_1``, ``dataset_2``…,
   mas o plano do orquestrador fala em ``orders`` e ``stores`` — e o modelo
   escreveu ``FROM orders AS o JOIN stores AS s``. DuckDB: «Table with name
   orders does not exist». Agora cada fatia é registada com o NOME LÓGICO da
   tabela e o prompt recebe exactamente esses nomes e as colunas reais.
2. A fatia ``stores`` tinha falhado (guardrail) e o merger correu na mesma
   com UMA fatia, a inventar a outra. Agora as fatias que falharam são
   conhecidas (``failed_slices``): com uma só fatia não há nada a juntar e
   ela passa directa, com aviso do que falta; sem nenhuma, a resposta diz
   honestamente que fontes falharam — nunca o «Algo falló» genérico.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.agents.generic_sql_agent import AgentState, AgentConfig
from core.llm.providers import LLMProvider
from core.logging_utils import log_event
from core.data_manager.duck_engine import DuckEngine
from core.llm.conteudo import texto_da_resposta

# ── Fatias: o que correu e o que falhou ────────────────────────────────


def resultado_da_fatia(
    table: Optional[str], res_state: Dict[str, Any]
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Classifica o estado devolvido pelo especialista de UMA fatia.

    Devolve ``(parcial, falha)`` — exactamente um dos dois é não-nulo.
    A falha leva o motivo para os registos; à pessoa só se diz QUE tabela
    faltou (o motivo técnico não lhe serve de nada).
    """
    table = table or res_state.get("chosen_table") or "?"
    data = res_state.get("data")
    if data is not None and _num_linhas(data) > 0:
        return (
            {
                "table": table,
                "data": data,
                "sql": res_state.get("sql"),
                "metadata": {
                    "source": "unknown",
                    "title": res_state.get("generated_title"),
                    "dialect": "unknown",
                },
            },
            None,
        )
    if res_state.get("impossible_reason"):
        motivo = str(res_state.get("impossible_reason"))
    elif res_state.get("error"):
        motivo = str(res_state.get("error"))
    elif res_state.get("sql"):
        motivo = "query ran and returned 0 rows"
    else:
        motivo = "no SQL was produced"
    return None, {"table": table, "reason": motivo[:300]}


def _tabela_do_catalogo(agent_config: AgentConfig, nome: str):
    return next(
        (
            t
            for t in agent_config.tables
            if (getattr(t, "display_name", None) or t.logical_name) == nome
        ),
        None,
    )


def tabelas_irmas(
    tbl_name: str, tbl_names: List[str], agent_config: AgentConfig
) -> List[str]:
    """As OUTRAS tabelas da mesma pergunta multi-fonte, «lógico (físico)».

    O especialista de cada fatia precisa de saber que existem — para não as
    juntar (o guardrail bloqueia e a fatia perde-se) e para trazer as
    colunas de junção que o merger vai usar.
    """
    irmas = []
    for nome in tbl_names:
        if nome == tbl_name:
            continue
        obj = _tabela_do_catalogo(agent_config, nome)
        fisico = getattr(obj, "physical_name", None) if obj else None
        irmas.append(f"{nome} ({fisico})" if fisico and fisico != nome else nome)
    return irmas


def executar_fatias_por_tabela(
    state: Dict[str, Any],
    agent_config: AgentConfig,
    chosen_tables: List[str],
    dispatch_map: Optional[Dict[str, Any]],
    data_source: Any,
    llm: LLMProvider,
    run_specialist: Callable[..., Dict[str, Any]],
    max_workers: int = 5,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Uma fatia por tabela, cada uma na SUA ligação, em paralelo.

    Devolve ``(partial_results, failed_slices)``. Usado pelos dois caminhos
    do grafo (modo SQL e o «data» do modo misto), que antes tinham cópias
    divergentes e deitavam fora as fatias falhadas sem dizer quais.
    """
    import concurrent.futures

    tarefas = []
    failed: List[Dict[str, Any]] = []
    for tbl_name in chosen_tables:
        tbl_obj = _tabela_do_catalogo(agent_config, tbl_name)
        if tbl_obj is None:
            failed.append({"table": tbl_name, "reason": "table not in agent config"})
            continue
        tbl_physical = tbl_obj.physical_name
        st = dict(state)
        st["chosen_table"] = tbl_name
        st["chosen_table_physical"] = tbl_physical
        st["chosen_tables"] = None
        # Só esta tabela no esquema do especialista: run_specialist filtra
        # pelo PLURAL chosen_tables_physical; vazio mostrava todas as fontes.
        st["chosen_tables_physical"] = [tbl_physical]
        st["join_relationships"] = None
        # Uma fatia: extrair a parte desta fonte em vez de recusar a
        # pergunta inteira; o merger junta as fatias depois.
        st["multi_source_subquery"] = True
        st["multi_source_sibling_tables"] = tabelas_irmas(
            tbl_name, chosen_tables, agent_config
        )
        conn_id = str(getattr(tbl_obj, "data_connection_id", "") or "")
        src = (dispatch_map or {}).get(conn_id) or data_source
        tarefas.append((tbl_name, st, src))

    partial: List[Dict[str, Any]] = []
    if not tarefas:
        return partial, failed
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max(1, min(len(tarefas), max_workers))
    ) as ex:
        futuros = {
            ex.submit(run_specialist, st, agent_config, src, llm): nome
            for nome, st, src in tarefas
        }
        for fut in concurrent.futures.as_completed(futuros):
            nome = futuros[fut]
            try:
                res_state = fut.result()
                log_event(
                    "multi_source_subquery_result",
                    {
                        "table": nome,
                        "has_data": bool(res_state.get("data")),
                        "rows": _num_linhas(res_state.get("data") or []),
                        "sql": (res_state.get("sql") or "")[:200],
                        "error": res_state.get("error"),
                        "impossible_reason": res_state.get("impossible_reason"),
                    },
                )
                parcial, falha = resultado_da_fatia(nome, res_state)
            except Exception as e:
                log_event("parallel_specialist_error", {"table": nome, "error": str(e)})
                parcial, falha = None, {"table": nome, "reason": str(e)[:300]}
            if parcial:
                partial.append(parcial)
            else:
                failed.append(falha)
    # Ordem estável (a do orquestrador), não a de quem acabou primeiro.
    ordem = {n: i for i, n in enumerate(chosen_tables)}
    partial.sort(key=lambda r: ordem.get(r.get("table"), len(ordem)))
    failed.sort(key=lambda r: ordem.get(r.get("table"), len(ordem)))
    return partial, failed


def _num_linhas(data: Any) -> int:
    try:
        import pyarrow as pa

        if isinstance(data, pa.Table):
            return data.num_rows
    except ImportError:
        pass
    try:
        return len(data)
    except TypeError:
        return 0


# ── Nomes no DuckDB ────────────────────────────────────────────────────


def _nome_duckdb(nome: str) -> str:
    """Nome lógico → identificador simples e seguro no DuckDB.

    ``orders`` fica ``orders``; ``service.orders`` fica ``orders`` (o
    schema não existe no DuckDB); «Pedidos 2026» fica ``pedidos_2026``.
    """
    base = (nome or "").strip().split(".")[-1].lower()
    base = re.sub(r"[^a-z0-9_]+", "_", base).strip("_")
    if not base:
        base = "fatia"
    if base[0].isdigit():
        base = f"t_{base}"
    return base


def nomes_das_fatias(partial_results: List[Dict[str, Any]]) -> List[str]:
    """Um nome DuckDB por fatia, pela ordem, sem repetidos."""
    usados: Dict[str, int] = {}
    nomes = []
    for i, res in enumerate(partial_results):
        base = _nome_duckdb(res.get("table") or f"dataset_{i + 1}")
        if base in usados:
            usados[base] += 1
            base = f"{base}_{usados[base]}"
        else:
            usados[base] = 1
        nomes.append(base)
    return nomes


def _colunas_e_amostra(rows: Any) -> Tuple[List[str], int, List[Dict[str, Any]]]:
    try:
        import pyarrow as pa

        if isinstance(rows, pa.Table):
            return rows.column_names, rows.num_rows, rows.slice(0, 2).to_pylist()
    except ImportError:
        pass
    rows = rows or []
    columns = list(rows[0].keys()) if rows else []
    return columns, len(rows), rows[:2]


def _generate_merger_prompt(
    question: str,
    partial_results: List[Dict[str, Any]],
    plan: str,
    nomes: Optional[List[str]] = None,
    failed_slices: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, str]]:
    """
    Creates the prompt for the Merger agent.
    Describes the partial data (tables) and asks for DuckDB SQL.
    The table names in the prompt are EXACTLY the names registered in DuckDB.
    """
    nomes = nomes or nomes_das_fatias(partial_results)

    data_summary = []
    for nome, res in zip(nomes, partial_results):
        meta = res.get("metadata", {}) or {}
        columns, row_count, sample_data = _colunas_e_amostra(res.get("data", []))
        data_summary.append(
            f"--- TABLE `{nome}` ---\n"
            f"Original table: {res.get('table', 'Unknown')}\n"
            f"Title: {meta.get('title', 'Unknown')}\n"
            f"Columns (exact names): {columns}\n"
            f"Row Count: {row_count}\n"
            f"Sample Data: {sample_data}\n"
        )
    data_block = "\n".join(data_summary)

    missing_block = ""
    if failed_slices:
        faltam = ", ".join(f"`{f.get('table')}`" for f in failed_slices)
        missing_block = (
            f"\nNOT AVAILABLE (these slices failed and are NOT loaded): {faltam}. "
            "Do not reference them.\n"
        )

    tabelas = ", ".join(f"`{n}`" for n in nomes)
    system_msg = {
        "role": "system",
        "content": (
            "You are a Data Engineer Expert specializing in DuckDB SQL.\n"
            "You have multiple in-memory tables loaded with data from different sources.\n"
            "Your task is to write a single DuckDB SQL query to join/aggregate these tables to answer the user's question.\n\n"
            "Technical Requirements:\n"
            f"1. The ONLY tables that exist are: {tabelas}. Use exactly these names, "
            "without schema prefixes. Any other table name fails.\n"
            "2. Ensure all column names referenced actually exist in the tables.\n"
            "3. Output ONLY the valid SQL query (inside ```sql ... ```). No explanations.\n"
            "4. Start with `SELECT` (or `WITH`).\n"
            "5. Handle type mismatches (e.g., cast string to int if needed) using DuckDB syntax.\n"
            "6. The data is already filtered by each source query: do not re-apply "
            "date filters with functions on columns that are not in the tables.\n"
            "7. Join the tables ONLY on columns they share (ids such as store_id). "
            "Never CROSS JOIN, comma-join or `ON TRUE` two of these tables: it "
            "multiplies rows and the numbers come out wrong.\n"
        ),
    }

    user_msg = {
        "role": "user",
        "content": (
            f"User Question: {question}\n\n"
            f"Plan Context: {plan}\n\n"
            f"Available Tables (DuckDB) — the ONLY ones: {tabelas}\n{data_block}\n"
            f"{missing_block}\n"
            "Generate the DuckDB SQL query."
        ),
    }

    return [system_msg, user_msg]


def _extract_sql_code(text: str) -> str:
    """Extracts code from ```sql ... ``` blocks (or an unlabelled ``` block)."""
    match = re.search(r"```sql\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search(r"```\s*(.*?)```", text, re.DOTALL)
    if match and re.match(r"\s*(select|with)\b", match.group(1), re.I):
        return match.group(1).strip()
    # Fallback: sem markdown, o texto tal como veio (o DuckDB decide).
    return text.strip()


def tabelas_desconhecidas(sql: str, nomes: List[str]) -> List[str]:
    """Tabelas que o SQL usa e que não estão registadas (CTEs não contam).

    Se o SQL não se deixar ler, devolve ``[]`` e o DuckDB decide.
    """
    try:
        import sqlglot
        from sqlglot import exp

        arvore = sqlglot.parse_one(sql, read="duckdb")
    except Exception:
        return []
    ctes = {c.alias_or_name.lower() for c in arvore.find_all(exp.CTE)}
    conhecidas = {n.lower() for n in nomes} | ctes
    fora = []
    for t in arvore.find_all(exp.Table):
        nome = (t.name or "").lower()
        if not nome:
            continue
        completo = ".".join(p for p in (t.db, t.name) if p)
        if nome not in conhecidas or t.db:
            if completo not in fora:
                fora.append(completo)
    return fora


def _chaves_da_fatia(nome: str, columns: List[str]) -> set:
    """Nomes de coluna por onde a fatia se pode ligar às outras.

    Inclui ``<tabela_no_singular>_id`` quando a fatia tem ``id`` — para que
    ``stores.id`` ligue a ``orders.store_id``.
    """
    chaves = {c.lower() for c in columns}
    if "id" in chaves:
        base = _nome_duckdb(nome)
        singular = base[:-1] if base.endswith("s") else base
        chaves.add(f"{singular}_id")
        chaves.add(f"{base}_id")
    return chaves


def grupos_sem_ligacao(
    partial_results: List[Dict[str, Any]], nomes: List[str]
) -> List[List[str]]:
    """Agrupa as fatias pelas colunas que partilham; >1 grupo = sem caminho.

    Medido com os modelos de produção (13/10/2026, «ventas por tienda y
    familia de producto»): ``orders`` vinha agregada por loja e
    ``order_items`` por prato — nenhuma coluna em comum. Sem caminho de
    junção o modelo inventava (CROSS JOIN, ou UNION com NULLs e «todas as
    lojas com 0 €»). Decide-se SEM o modelo: não há junção possível.
    """
    chaves = [
        _chaves_da_fatia(n, _colunas_e_amostra(r.get("data", []))[0])
        for n, r in zip(nomes, partial_results)
    ]
    grupo = list(range(len(nomes)))

    def raiz(i: int) -> int:
        while grupo[i] != i:
            grupo[i] = grupo[grupo[i]]
            i = grupo[i]
        return i

    for i in range(len(nomes)):
        for j in range(i + 1, len(nomes)):
            if chaves[i] & chaves[j]:
                grupo[raiz(i)] = raiz(j)
    grupos: Dict[int, List[str]] = {}
    for i, n in enumerate(nomes):
        grupos.setdefault(raiz(i), []).append(n)
    return list(grupos.values())


def juncoes_sem_chave(sql: str, nomes: List[str]) -> List[str]:
    """Fatias juntadas sem chave (CROSS JOIN, vírgula, ``ON TRUE``, ``ON 1=1``).

    Medido com os modelos de produção (13/10/2026): sem coluna comum entre
    as fatias, o modelo fazia ``CROSS JOIN`` e devolvia um número inventado
    com ar de certo. Só conta quando o lado juntado é uma FATIA registada —
    juntar a um CTE/subconsulta de uma linha (ex.: o total, para
    percentagens) é legítimo.
    """
    try:
        import sqlglot
        from sqlglot import exp

        arvore = sqlglot.parse_one(sql, read="duckdb")
    except Exception:
        return []
    fatias = {n.lower() for n in nomes}
    ctes = {c.alias_or_name.lower() for c in arvore.find_all(exp.CTE)}
    sem_chave = []
    for j in arvore.find_all(exp.Join):
        alvo = j.this
        if not isinstance(alvo, exp.Table):
            continue
        nome = (alvo.name or "").lower()
        if nome not in fatias or nome in ctes:
            continue
        on = j.args.get("on")
        tem_chave = bool(j.args.get("using")) or (
            on is not None and any(True for _ in on.find_all(exp.Column))
        )
        if not tem_chave and nome not in sem_chave:
            sem_chave.append(nome)
    return sem_chave


def _pedir_sql(llm: LLMProvider, prompt: List[Dict[str, str]]) -> str:
    response = llm.invoke(prompt)
    text_response = texto_da_resposta(response)
    return _extract_sql_code(text_response)


def _run_merger_por_tabela(
    state: AgentState, agent_config: AgentConfig, llm: LLMProvider
) -> AgentState:
    """
    Merger Node (caminho de sempre, uma fatia por tabela — #289):
    - Consolidates partial_results from multiple Specialists.
    - Uses LLM to generate DuckDB SQL (tables named after the logical tables).
    - Executes the SQL using DuckEngine, with one retry on a wrong table/SQL.
    - Never invents missing slices: one slice passes through with a notice,
      none gives an honest failure (state["merge_failure"]).
    """
    question = state.get("question", "")
    partial_results = state.get("partial_results", []) or []
    failed_slices = state.get("failed_slices") or []
    plan = state.get("plan", "")

    log_event(
        "merger_start",
        {
            "agent_id": agent_config.id,
            "num_datasets": len(partial_results),
            "failed_slices": [f.get("table") for f in failed_slices],
            "question": question[:100],
        },
    )

    if not partial_results:
        if failed_slices:
            # A causa é conhecida: nenhuma fonte devolveu a sua parte.
            state["merge_failure"] = {
                "kind": "no_slices",
                "failed": [f.get("table") for f in failed_slices],
                "ok": [],
            }
            state["data"] = []
            log_event(
                "merger_no_slices",
                {"failed_slices": failed_slices},
            )
        else:
            state["error"] = "Merger received no partial results."
        return state

    if len(partial_results) == 1:
        # Nada a juntar. Pedir SQL ao modelo era convidá-lo a inventar a
        # tabela que falta (foi o que aconteceu em produção).
        unica = partial_results[0]
        state["data"] = unica.get("data")
        state["sql"] = unica.get("sql")
        title = (unica.get("metadata") or {}).get("title")
        if title:
            state["generated_title"] = title
        log_event(
            "merger_single_slice_passthrough",
            {
                "table": unica.get("table"),
                "failed_slices": [f.get("table") for f in failed_slices],
            },
        )
        return state

    nomes = nomes_das_fatias(partial_results)
    grupos = grupos_sem_ligacao(partial_results, nomes)
    if len(grupos) > 1:
        state["merge_failure"] = {
            "kind": "merge_failed",
            "failed": [f.get("table") for f in failed_slices],
            "ok": [r.get("table") for r in partial_results],
        }
        state["debug_error"] = f"Merger: slices share no join column: {grupos}"
        state["data"] = []
        log_event("merger_no_join_key", {"groups": grupos})
        return state

    prompt = _generate_merger_prompt(
        question, partial_results, plan, nomes=nomes, failed_slices=failed_slices
    )
    try:
        sql_query = _pedir_sql(llm, prompt)
    except Exception as e:
        state["error"] = f"Merger LLM generation failed: {str(e)}"
        return state

    engine = None
    try:
        engine = DuckEngine()
        for nome, res in zip(nomes, partial_results):
            engine.register_data(nome, res.get("data", []))

        final_data = None
        erro = None
        for tentativa in range(2):
            fora = tabelas_desconhecidas(sql_query, nomes)
            sem_chave = [] if fora else juncoes_sem_chave(sql_query, nomes)
            if fora:
                erro = (
                    f"Unknown table(s) {fora}. The only tables that exist are "
                    f"{nomes} (no schema prefix)."
                )
            elif sem_chave:
                erro = (
                    f"Table(s) {sem_chave} joined without a key (CROSS JOIN, comma "
                    "or ON TRUE): that multiplies rows and invents numbers. Join "
                    "on a column the tables share; if they share none, they "
                    "cannot be combined."
                )
            else:
                try:
                    final_data = engine.execute(sql_query)
                    erro = None
                except Exception as e:
                    erro = str(e)
            if erro is None:
                break
            log_event(
                "merger_execution_error",
                {"error": erro[:500], "sql": sql_query, "attempt": tentativa + 1},
            )
            if tentativa == 0:
                try:
                    sql_query = _pedir_sql(
                        llm,
                        prompt
                        + [
                            {
                                "role": "assistant",
                                "content": f"```sql\n{sql_query}\n```",
                            },
                            {
                                "role": "user",
                                "content": (
                                    f"That query failed in DuckDB: {erro[:500]}\n"
                                    f"Rewrite it using ONLY the tables {nomes} and "
                                    "their listed columns. Output only the SQL."
                                ),
                            },
                        ],
                    )
                except Exception as e:
                    erro = f"Merger LLM retry failed: {e}"
                    break

        if erro is not None:
            # Causa conhecida: as partes vieram, a junção é que não. Dizê-lo.
            state["merge_failure"] = {
                "kind": "merge_failed",
                "failed": [f.get("table") for f in failed_slices],
                "ok": [r.get("table") for r in partial_results],
            }
            state["debug_error"] = f"Merger DuckDB execution failed: {erro}"
            state["data"] = []
            return state

        state["data"] = final_data
        state["generated_title"] = (
            f"Consolidated Report ({len(partial_results)} Sources)"
        )
        state["sql"] = sql_query  # Save the merger SQL for debugging/explanation
        log_event("merger_success", {"final_rows": len(final_data), "sql": sql_query})

    except Exception as e:
        state["error"] = f"Merger DuckDB execution failed: {str(e)}"
        log_event("merger_execution_error", {"error": str(e), "sql": sql_query})
    finally:
        if engine:
            engine.close()

    return state


# ══ Caminho novo: uma fatia por LIGAÇÃO (flag MULTI_FONTE_POR_LIGACAO) ══
#
# Conjuntos registados como ``dataset_N`` (cada um pode juntar várias tabelas
# da mesma ligação), pistas de junção vistas nos DADOS, descrições das
# colunas e uma correcção com o erro do DuckDB. Ver core/llm/multi_fonte.py.

# Linhas de amostra por conjunto no prompt. Duas não chegavam para o modelo
# ver que uma cidade vem 'BADAJOZ' de um lado e 'Badajoz' do outro, nem que
# uma data vem como instante (2026-09-01T06:00:00+00:00) e a outra como dia.
AMOSTRA = 5


def _sem_acentos(s: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", s or "")
        if not unicodedata.combining(c)
    ).lower()


def _colunas_e_amostra_n(rows: Any) -> Tuple[List[str], int, List[Dict[str, Any]]]:
    try:
        import pyarrow as pa

        if isinstance(rows, pa.Table):
            return rows.column_names, rows.num_rows, rows.slice(0, AMOSTRA).to_pylist()
    except ImportError:  # pragma: no cover
        pass
    rows = rows or []
    cols = list(rows[0].keys()) if rows else []
    return cols, len(rows), rows[:AMOSTRA]


_SINONIMOS = (
    {"origin", "origem", "origen"},
    {"destination", "destino"},
    {"city", "cidade", "ciudad", "origin", "origem", "destination", "destino"},
    {"date", "data", "fecha", "dia", "day"},
    {"province", "provincia"},
    {"country", "pais"},
)


def _parece_instante(v: Any) -> bool:
    import datetime as _dt

    if isinstance(v, _dt.datetime):
        return True
    return isinstance(v, str) and bool(re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:", v))


def _parece_dia(v: Any) -> bool:
    import datetime as _dt

    if isinstance(v, _dt.date) and not isinstance(v, _dt.datetime):
        return True
    return isinstance(v, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", v))


def pistas_entre_conjuntos(
    resumos: List[Tuple[str, List[str], List[Dict[str, Any]]]],
) -> List[str]:
    """Pistas de junção entre ``dataset_i``, vistas nos DADOS (não no esquema).

    Mesmo nome, sinónimo entre línguas, instante × dia (CAST AS DATE) e texto
    com maiúsculas/acentos diferentes dos dois lados (comparar normalizado).
    """
    pistas: List[str] = []
    for i in range(len(resumos)):
        for j in range(i + 1, len(resumos)):
            ai, ci, si = resumos[i]
            aj, cj, sj = resumos[j]
            for x in ci:
                for y in cj:
                    nx, ny = _sem_acentos(x), _sem_acentos(y)
                    mesmo = nx == ny
                    sin = any(nx in g and ny in g for g in _SINONIMOS)
                    if not (mesmo or sin):
                        continue
                    vx = next((r.get(x) for r in si if r.get(x) is not None), None)
                    vy = next((r.get(y) for r in sj if r.get(y) is not None), None)
                    expr_x, expr_y = f"{ai}.{x}", f"{aj}.{y}"
                    nota = ""
                    if _parece_instante(vx) and _parece_dia(vy):
                        expr_x = f"CAST({ai}.{x} AS DATE)"
                        expr_y = f"CAST({aj}.{y} AS DATE)"
                        nota = " (one side is a timestamp, the other a day)"
                    elif _parece_dia(vx) and _parece_instante(vy):
                        expr_x = f"CAST({ai}.{x} AS DATE)"
                        expr_y = f"CAST({aj}.{y} AS DATE)"
                        nota = " (one side is a timestamp, the other a day)"
                    elif (
                        isinstance(vx, str)
                        and isinstance(vy, str)
                        and not (_parece_dia(vx) or _parece_instante(vx))
                    ):
                        expr_x = f"lower(strip_accents({ai}.{x}))"
                        expr_y = f"lower(strip_accents({aj}.{y}))"
                        nota = " (text: compare case- and accent-insensitively)"
                    elif _parece_dia(vx) and _parece_dia(vy):
                        expr_x = f"CAST({ai}.{x} AS DATE)"
                        expr_y = f"CAST({aj}.{y} AS DATE)"
                    p = f"{expr_x} = {expr_y}{nota}"
                    if p not in pistas:
                        pistas.append(p)
    return pistas[:12]


# Regras de raciocínio que o modelo errava no portão (14/10/2026, Sonnet
# 4.6, P3/P6/P10) — gerais, valem para qualquer par de fontes. As mesmas
# regras vão no contrato da fatia (core/llm/multi_fonte.py): quando a fatia
# já filtrou mal, o merger já não tem as linhas para corrigir.
REGRAS_DE_RACIOCINIO = (
    "10. OR across columns: when the question asks for a match in one column OR "
    "another (origin or destination, sender or receiver), match the key against "
    "EITHER column (`b.key IN (a.col1, a.col2)` or EXISTS) and count each item once "
    "(COUNT(DISTINCT id)). Require ALL columns only when the question says 'and' / "
    "'both'.\n"
    "11. Geographic level: rows of a wider area (national rows with region NULL, a "
    "country total such as 'ESPAÑA') are NOT rows of a narrower area, and the other "
    "way round. Use exactly the level the question names: 'a regional holiday of X' "
    "is a row whose region is X, not a national holiday. When datasets use "
    "different levels (city vs province vs region), map the cities to their "
    "province/region explicitly.\n"
    "12. A property of a whole entity stored as several rows (a route made of "
    "several sections, an order made of lines) holds only if it holds for ALL its "
    "rows ('the route has no toll' = every section is toll-free -> bool_and), or "
    "for ANY row when the question says so (bool_or). Aggregate per entity first; "
    "never keep an entity because one of its rows matches.\n"
    "13. Count and sum over the client's own entities (its routes, trips, "
    "vehicles). A public dataset that also lists routes or places only describes "
    "them; never let it decide which of the client's entities exist.\n"
    # Produção 14/10/2026: «¿Qué clientes dejan más por kilómetro?» — sem
    # trip_id numa das fatias, o merger repartiu os km «por proporção» e
    # respondeu com números inventados como se fossem medidos.
    "14. Never estimate, apportion or distribute a measure 'proportionally' (by "
    "share of trips, of rows, of totals) to make up for a missing join key: a "
    "made-up number presented as measured is worse than no number. When the keys "
    "ARE there, join on them and aggregate to what the question asks (e.g. per "
    "route), as rule 9 says.\n"
)


def _generate_merger_prompt_por_ligacao(
    question: str,
    partial_results: List[Dict[str, Any]],
    plan: str,
    failed_slices: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, str]]:
    """
    Creates the prompt for the Merger agent.
    Describes the partial data (tables) and asks for DuckDB SQL.
    """

    data_summary = []
    resumos: List[Tuple[str, List[str], List[Dict[str, Any]]]] = []
    for i, res in enumerate(partial_results):
        meta = res.get("metadata", {}) or {}
        alias = f"dataset_{i+1}"
        columns, row_count, sample_data = _colunas_e_amostra_n(res.get("data", []))
        resumos.append((alias, columns, sample_data))
        descricoes = meta.get("descricoes") or {}
        col_txt = []
        for c in columns:
            d = str(descricoes.get(c) or "").strip()
            col_txt.append(f"{c} — {d[:100]}" if d else c)
        summary = (
            f"--- TABLE '{alias}' ---\n"
            f"Original Source: {meta.get('source', 'Unknown')}\n"
            f"Source tables: {res.get('table') or 'Unknown'}\n"
            f"Title: {meta.get('title', 'Unknown')}\n"
            f"Columns: {columns}\n"
            + (
                "Column meaning:\n  - " + "\n  - ".join(col_txt) + "\n"
                if descricoes
                else ""
            )
            + (
                f"Row Count: {row_count} (WARNING: hit the row limit, may be TRUNCATED)\n"
                if meta.get("possivelmente_cortada")
                else f"Row Count: {row_count} (the table is COMPLETE, not a sample)\n"
            )
            + f"Sample Data (first {min(AMOSTRA, row_count)} rows): "
            f"{json.dumps(sample_data, default=str, ensure_ascii=False)}\n"
            + (
                f"SQL that produced it: {str(res.get('sql'))[:600]}\n"
                if res.get("sql")
                else ""
            )
        )
        data_summary.append(summary)

    data_block = "\n".join(data_summary)
    pistas = pistas_entre_conjuntos(resumos)
    pistas_block = (
        "Likely join keys (verify against the samples):\n- "
        + "\n- ".join(pistas)
        + "\n\n"
        if pistas
        else ""
    )

    system_msg = {
        "role": "system",
        "content": (
            "You are a Data Engineer Expert specializing in DuckDB SQL.\n"
            "You have multiple in-memory tables loaded with data from different sources.\n"
            "Your task is to write a single DuckDB SQL query to join/aggregate these tables to answer the user's question.\n\n"
            "Technical Requirements:\n"
            "1. Use the table names provided (e.g., `dataset_1`, `dataset_2`).\n"
            "2. Ensure all column names referenced actually exist in the tables.\n"
            "3. Output ONLY the valid SQL query (inside ```sql ... ```). No explanations.\n"
            "4. Start with `SELECT` or `WITH`.\n"
            "5. Handle type mismatches (e.g., cast string to int if needed) using DuckDB syntax.\n"
            "6. Text keys may differ in case/accents between sources ('BADAJOZ' vs 'Badajoz'): "
            "compare with lower(strip_accents(x)).\n"
            "7. A timestamp and a calendar day join with CAST(ts AS DATE) = CAST(day AS DATE).\n"
            "8. Pre-aggregate each dataset to the join grain before joining, so measures are not "
            "multiplied by the join (fan-out).\n"
            "9. The final result must be small and answer the question directly (the final "
            "number(s), or one row per item the question asks for).\n"
            + REGRAS_DE_RACIOCINIO
        ),
    }

    missing_block = ""
    if failed_slices:
        faltam = ", ".join(f"`{f.get('table')}`" for f in failed_slices)
        missing_block = (
            f"NOT AVAILABLE (these slices failed and are NOT loaded): {faltam}. "
            "Do not reference them.\n\n"
        )

    user_msg = {
        "role": "user",
        "content": (
            f"User Question: {question}\n\n"
            f"Plan Context: {plan}\n\n"
            f"Available Tables (DuckDB):\n{data_block}\n\n"
            f"{pistas_block}"
            f"{missing_block}"
            "Generate the DuckDB SQL query."
        ),
    }

    return [system_msg, user_msg]


def _run_merger_por_ligacao(
    state: AgentState, agent_config: AgentConfig, llm: LLMProvider
) -> AgentState:
    """Merger do caminho novo (flag MULTI_FONTE_POR_LIGACAO).

    - 0 ou 1 conjuntos: nada a juntar — igual ao caminho de sempre (passa a
      única fatia directa, ou diz que fontes falharam; nunca pede ao modelo
      que invente a que falta).
    - 2+: prompt com descrições, pistas de junção e regras de raciocínio;
      com um erro do DuckDB, UMA correcção com a mensagem de erro.
    """
    question = state.get("question", "")
    partial_results = state.get("partial_results", []) or []
    failed_slices = state.get("failed_slices") or []
    plan = state.get("plan", "")

    if len(partial_results) <= 1:
        return _run_merger_por_tabela(state, agent_config, llm)

    log_event(
        "merger_start",
        {
            "agent_id": agent_config.id,
            "num_datasets": len(partial_results),
            "failed_slices": [f.get("table") for f in failed_slices],
            "question": question[:100],
            "path": "por_ligacao",
        },
    )

    prompt = _generate_merger_prompt_por_ligacao(
        question, partial_results, plan, failed_slices=failed_slices
    )
    try:
        sql_query = _pedir_sql(llm, prompt)
    except Exception as e:
        state["error"] = f"Merger LLM generation failed: {str(e)}"
        return state

    engine = None
    try:
        engine = DuckEngine()
        for i, res in enumerate(partial_results):
            engine.register_data(f"dataset_{i+1}", res.get("data", []))

        try:
            final_data = engine.execute(sql_query)
        except Exception as primeiro:
            log_event(
                "merger_execution_retry",
                {"error": str(primeiro)[:300], "sql": sql_query[:600]},
            )
            correcao = prompt + [
                {"role": "assistant", "content": f"```sql\n{sql_query}\n```"},
                {
                    "role": "user",
                    "content": (
                        f"DuckDB rejected that query:\n{str(primeiro)[:600]}\n\n"
                        "Fix it. Use only the columns listed for each dataset. "
                        "Output ONLY the corrected SQL inside ```sql ... ```."
                    ),
                },
            ]
            sql_query = _pedir_sql(llm, correcao)
            final_data = engine.execute(sql_query)

        state["data"] = final_data
        state["generated_title"] = (
            f"Consolidated Report ({len(partial_results)} Sources)"
        )
        state["sql"] = sql_query
        log_event("merger_success", {"final_rows": len(final_data), "sql": sql_query})
    except Exception as e:
        # As partes vieram, a junção é que não: dizê-lo (MULTI_SOURCE_*).
        state["merge_failure"] = {
            "kind": "merge_failed",
            "failed": [f.get("table") for f in failed_slices],
            "ok": [r.get("table") for r in partial_results],
        }
        state["debug_error"] = f"Merger DuckDB execution failed: {e}"
        state["data"] = []
        log_event("merger_execution_error", {"error": str(e), "sql": sql_query})
    finally:
        if engine:
            engine.close()

    return state


def run_merger(
    state: AgentState, agent_config: AgentConfig, llm: LLMProvider
) -> AgentState:
    """Merger multi-fonte.

    Com a flag ``MULTI_FONTE_POR_LIGACAO(_TENANTS)`` activa no pedido (o nó
    marca ``state["multi_fonte_por_ligacao"]``): conjuntos por ligação,
    pistas de junção, regras de raciocínio e uma correcção com o erro do
    DuckDB. Sem ela, o merger de sempre (uma fatia por tabela, #289).
    """
    if state.get("multi_fonte_por_ligacao"):
        return _run_merger_por_ligacao(state, agent_config, llm)
    return _run_merger_por_tabela(state, agent_config, llm)
