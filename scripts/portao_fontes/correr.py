# -*- coding: utf-8 -*-
"""Corre o portão: 10 perguntas mistas pelo caminho multi-ligação.

Uso (a partir de sky-poc-ai/, com o venv):

    # tecto estrutural, sem modelo (determinístico; é o que a CI corre)
    OLLAMA_BASE_URL=http://localhost:11434 python -m scripts.portao_fontes.correr --llm oraculo

    # a arquitectura de origin/main (uma fatia por TABELA), para comparar:
    # correr a partir de uma worktree de main com PORTAO_CODIGO a apontar
    # para essa worktree (o harness é o mesmo; o motor é o de main)
    python -m scripts.portao_fontes.correr --llm oraculo --arquitectura antiga

    # os modelos de produção pela MESMA fábrica que o pod usa (AI_PROVIDER,
    # OPENAI_BASE_URL, OPENAI_API_KEY e LLM_MODEL_* do ambiente)
    AI_PROVIDER=openai OPENAI_BASE_URL=https://bedrock-mantle.eu-west-1.api.aws/v1 ...       python -m scripts.portao_fontes.correr --llm openai --formatter --vezes 2

    # Bedrock Converse pela fábrica (precisa de `aws sso login --profile sky-production`);
    # modelos de BEDROCK_MODEL_ORCHESTRATOR / _SPECIALIST / _MERGER / _FORMATTER
    AI_PROVIDER=bedrock AWS_PROFILE=sky-production BEDROCK_MODEL_ORCHESTRATOR=... \
      python -m scripts.portao_fontes.correr --llm bedrock --formatter --vezes 2

O merger usa o modelo do merger do grafo (``create_llm_merger``): o
especialista, salvo ``BEDROCK_MODEL_MERGER`` / ``LLM_MODEL_MERGER``. Com
``--json`` cada linha leva tokens por modelo, segundos e esperas do limite
de pedidos.

Critério (desenho §3.7): ≥ 8/10 com o número certo. Uma pergunta passa quando
TODAS as colunas de ``verificar`` aparecem no resultado final (tolerância de
0,5 % ou 0,01 em absoluto). Com ``--formatter`` exige-se também a citação da
fonte e da hora na resposta.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional

_codigo = os.environ.get("PORTAO_CODIGO")
if _codigo:  # correr o MESMO harness contra outro código (ex.: main)
    sys.path.insert(0, _codigo)
os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float, Decimal)):
        return float(v)
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


def _bate(esperado: float, obtido: float) -> bool:
    return abs(esperado - obtido) <= max(0.01, abs(esperado) * 0.005)


def fatias_por_tabela(
    state, cfg, escolhidas, dispatch_map, data_source, llm, run_specialist
):
    """A arquitectura de sempre (sem a flag): uma sub-pergunta por TABELA.

    É a de main (core/llm/merger.executar_fatias_por_tabela, #289). Com
    PORTAO_CODIGO a apontar para um código anterior ao #289, cai na cópia
    antiga (resultados pela ordem em que acabam, falhas deitadas fora).
    """
    try:
        from core.llm.merger import executar_fatias_por_tabela
    except ImportError:
        executar_fatias_por_tabela = None
    if executar_fatias_por_tabela is not None:
        return executar_fatias_por_tabela(
            state, cfg, escolhidas, dispatch_map, data_source, llm, run_specialist
        )
    tarefas = []
    for nome in escolhidas:
        t = next(
            (x for x in cfg.tables if (x.display_name or x.logical_name) == nome), None
        )
        fis = t.physical_name if t else None
        st = dict(state)
        st["chosen_table"] = nome
        st["chosen_table_physical"] = fis
        st["chosen_tables"] = None
        st["chosen_tables_physical"] = [fis] if fis else None
        st["join_relationships"] = None
        st["multi_source_subquery"] = True
        cid = str(getattr(t, "data_connection_id", "") or "")
        tarefas.append((st, (dispatch_map or {}).get(cid) or data_source))
    out = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        futs = [ex.submit(run_specialist, st, cfg, src, llm) for st, src in tarefas]
        for f in concurrent.futures.as_completed(futs):
            r = f.result()
            if r.get("data"):
                out.append(
                    {
                        "table": r.get("chosen_table"),
                        "data": r.get("data"),
                        "sql": r.get("sql"),
                        "metadata": {
                            "source": "unknown",
                            "title": r.get("generated_title"),
                            "dialect": "unknown",
                        },
                    }
                )
    return out, []


def _llms(qual: str, arquitectura: str):
    if qual == "oraculo":
        from scripts.portao_fontes.oraculo import Oraculo

        o = Oraculo(arquitectura)
        return o, o, o, o
    if qual == "openai" or os.getenv("BEDROCK_MODEL_ORCHESTRATOR"):
        # A MESMA fábrica de produção: AI_PROVIDER, OPENAI_BASE_URL e
        # LLM_MODEL_* (ou BEDROCK_MODEL_*) vêm do ambiente (em produção,
        # AI_PROVIDER=openai com o endpoint compatível da Bedrock,
        # gpt-oss-120b + qwen3-coder-30b).
        from core.llm.factory import (
            create_llm_formatter,
            create_llm_merger,
            create_llm_orchestrator,
            create_llm_specialist,
            modelo_do_merger_definido,
        )

        _instrumentar()
        llm_e = create_llm_specialist()
        # O merger do grafo: modelo próprio se definido; senão, no caminho
        # novo, o especialista; no de sempre, o orquestrador (_llm_do_merger).
        llm_o = create_llm_orchestrator()
        if modelo_do_merger_definido():
            llm_m = create_llm_merger()
        else:
            llm_m = llm_e if arquitectura == "nova" else llm_o
        return llm_o, llm_e, llm_m, create_llm_formatter()
    from core.llm.providers import BedrockChatProvider

    reg = os.getenv("BEDROCK_REGION", "eu-west-1")
    orq = os.getenv("PORTAO_ORQ", "openai.gpt-oss-120b-1:0")
    esp = os.getenv("PORTAO_ESP", "qwen.qwen3-coder-30b-a3b-v1:0")
    llm_o = BedrockChatProvider(model=orq, region=reg, temperature=0.0)
    llm_e = BedrockChatProvider(model=esp, region=reg, temperature=0.0)
    llm_f = BedrockChatProvider(model=orq, region=reg, temperature=0.2)
    # O merger do grafo usa o LLM do orquestrador (merger_node).
    return llm_o, llm_e, llm_o, llm_f


#: Tokens, segundos e esperas por pergunta (só com a fábrica).
_CONTAGEM: Dict[str, Dict[str, float]] = {}
_ESPERAS: List[float] = []


def _instrumentar() -> None:
    """Conta tokens/segundos por modelo no ``_generate`` das classes LangChain
    (Converse da Bedrock e ChatOpenAI) e as esperas do limite de pedidos."""
    import threading

    import core.llm.providers as prov

    trinco = threading.Lock()
    classes = []
    try:
        classes.append(prov._converse_com_repeticao())
    except Exception:  # sem langchain-aws
        pass
    try:
        from langchain_openai import ChatOpenAI

        classes.append(ChatOpenAI)
    except Exception:
        pass
    for cls in classes:
        if cls.__dict__.get("_portao_instrumentado"):
            continue
        original = cls._generate

        def _generate(self, *a, __orig=original, **k):
            t0 = time.perf_counter()
            r = __orig(self, *a, **k)
            msg = r.generations[0].message
            um = getattr(msg, "usage_metadata", None) or {}
            if not um:  # ChatOpenAI antigo: só no llm_output
                tu = (getattr(r, "llm_output", None) or {}).get("token_usage") or {}
                um = {
                    "input_tokens": tu.get("prompt_tokens"),
                    "output_tokens": tu.get("completion_tokens"),
                }
            modelo = (
                getattr(self, "model_id", None)
                or getattr(self, "model_name", None)
                or "?"
            )
            with trinco:
                c = _CONTAGEM.setdefault(
                    modelo, {"chamadas": 0, "in": 0, "out": 0, "s": 0.0}
                )
                c["chamadas"] += 1
                c["in"] += int(um.get("input_tokens") or 0)
                c["out"] += int(um.get("output_tokens") or 0)
                c["s"] += time.perf_counter() - t0
            return r

        cls._generate = _generate
        cls._portao_instrumentado = True
    if getattr(prov, "_dormir", None) and not getattr(prov._dormir, "_portao", False):
        dormir = prov._dormir

        def _dormir(seg):
            with trinco:
                _ESPERAS.append(seg)
            dormir(seg)

        _dormir._portao = True
        prov._dormir = _dormir


def correr_pergunta(
    amb, p, llms, arquitectura: str, com_formatter: bool
) -> Dict[str, Any]:
    from core.llm.orchestrator import run_orchestrator
    from core.llm.specialist import run_specialist
    from core.llm.merger import run_merger

    llm_o, llm_e, llm_m, llm_f = llms
    t0 = time.time()
    esperado = amb.esperado(p.esperado_sql)[0]
    r: Dict[str, Any] = {
        "id": p.id,
        "pergunta": p.texto,
        "esperado": {k: _num(esperado[k]) for k in p.verificar},
    }
    st = {
        "question": p.texto,
        "detected_language": "es",
        "locale": "es",
        "user_locale": "es",
        "chat_history": [],
        "retrieval_context": [],
        "crew_ids": [],
        "space_id": "",
    }
    st = run_orchestrator(st, amb.config, llm_o, db=None, embedding_provider=None)
    r["escolhidas"] = st.get("chosen_tables")
    r["multi_ligacao"] = bool(st.get("is_multi_source"))
    if not st.get("chosen_tables"):
        r.update(
            ok=False,
            porque="o orquestrador não escolheu tabelas: "
            + str(st.get("answer"))[:200],
        )
        return r
    if not st.get("is_multi_source"):
        r.update(ok=False, porque="o orquestrador escolheu tabelas de UMA ligação só")
        return r

    if arquitectura == "nova":
        from core.llm.multi_fonte import executar_fatias

        parciais, fontes, falhadas = executar_fatias(
            st,
            amb.config,
            st["chosen_tables"],
            amb.dispatch_map,
            amb.fonte_cliente,
            llm_e,
            run_specialist=run_specialist,
        )
        st["fontes_publicas"] = fontes
    else:
        parciais, falhadas = fatias_por_tabela(
            st,
            amb.config,
            st["chosen_tables"],
            amb.dispatch_map,
            amb.fonte_cliente,
            llm_e,
            run_specialist,
        )
    r["fatias"] = [
        {
            "tabelas": x.get("table"),
            "linhas": len(x.get("data") or []),
            "sql": " ".join(str(x.get("sql") or "").split())[:800],
        }
        for x in parciais
    ]
    if falhadas:
        r["fatias_falhadas"] = [
            {"tabelas": f.get("table"), "motivo": str(f.get("reason"))[:300]}
            for f in falhadas
        ]
    # A flag MULTI_FONTE_POR_LIGACAO(_TENANTS) marca isto no grafo; aqui a
    # arquitectura escolhida decide.
    final = run_merger(
        {
            **st,
            "partial_results": parciais,
            "failed_slices": falhadas,
            "multi_fonte_por_ligacao": arquitectura == "nova",
        },
        amb.config,
        llm_m,
    )
    r["merger_sql"] = " ".join(str(final.get("sql") or "").split())[:400]
    r["erro"] = final.get("error") or final.get("debug_error")
    dados = final.get("data") or []
    r["resultado"] = [
        {k: _num(v) if _num(v) is not None else v for k, v in l.items()}
        for l in dados[:3]
    ]
    numeros = [_num(v) for l in dados for v in l.values() if _num(v) is not None]
    falta = [
        k
        for k, v in r["esperado"].items()
        if v is None or not any(_bate(v, n) for n in numeros)
    ]
    r["ok"] = not falta and not final.get("error")
    if com_formatter and r["ok"]:
        from core.llm.formatter import run_formatter

        f = run_formatter(dict(final), amb.config, llm_f)
        r["resposta"] = f.get("answer")
        if st.get("fontes_publicas") and "actualizado" not in (f.get("answer") or ""):
            r["ok"] = False
            r["porque"] = "a resposta não cita a fonte e a hora do dado"
    if not r["ok"] and "porque" not in r:
        r["porque"] = _diagnostico(r, falta)
    r["s"] = round(time.time() - t0, 1)
    return r


def _diagnostico(r: Dict[str, Any], falta: List[str]) -> str:
    if r.get("erro"):
        return f"merger: {str(r['erro'])[:200]}"
    cortadas = [f for f in r.get("fatias", []) if f["linhas"] in (100, 150)]
    if cortadas:
        return (
            "fatia cortada pelo LIMIT do prompt do especialista ("
            + ", ".join(f"{c['tabelas']}={c['linhas']} linhas" for c in cortadas)
            + "): o merger somou um subconjunto"
        )
    if len(r.get("fatias", [])) < 2:
        return "menos de duas fatias com dados — o merger não tinha o que cruzar"
    return f"número errado em {falta}: obtido {r.get('resultado')}"


def correr(
    llm: str = "oraculo",
    arquitectura: str = "nova",
    com_formatter: bool = False,
    vezes: int = 1,
):
    from scripts.portao_fontes.fixtures import Ambiente
    from scripts.portao_fontes.perguntas import PERGUNTAS

    amb = Ambiente()
    llms = _llms(llm, arquitectura)
    saida = []
    for p in PERGUNTAS:
        for _ in range(vezes):
            _CONTAGEM.clear()
            _ESPERAS.clear()
            t0 = time.time()
            try:
                r = correr_pergunta(amb, p, llms, arquitectura, com_formatter)
            except Exception as e:  # o portão tem de mostrar a falha, não morrer
                r = {
                    "id": p.id,
                    "ok": False,
                    "porque": f"excepção: {type(e).__name__}: {str(e)[:300]}",
                }
            r["s_total"] = round(time.time() - t0, 1)
            if _CONTAGEM or _ESPERAS:
                r["tokens"] = {
                    m: dict(v, s=round(v["s"], 1)) for m, v in _CONTAGEM.items()
                }
                r["esperas_throttle"] = len(_ESPERAS)
                r["s_em_esperas"] = round(sum(_ESPERAS), 1)
            if llm != "oraculo":  # progresso, uma linha por pergunta
                print(
                    json.dumps(r, ensure_ascii=False, default=str),
                    file=sys.stderr,
                    flush=True,
                )
            saida.append(r)
    return saida


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--llm", choices=("oraculo", "openai", "bedrock"), default="oraculo"
    )
    ap.add_argument("--arquitectura", choices=("nova", "antiga"), default="nova")
    ap.add_argument("--formatter", action="store_true")
    ap.add_argument("--vezes", type=int, default=1)
    ap.add_argument("--json", action="store_true", help="uma linha JSON por pergunta")
    a = ap.parse_args()
    res = correr(a.llm, a.arquitectura, a.formatter, a.vezes)
    for r in res:
        if a.json:
            print(json.dumps(r, ensure_ascii=False, default=str))
        else:
            estado = "OK  " if r.get("ok") else "FALHA"
            print(f"{estado} {r['id']}: {'' if r.get('ok') else r.get('porque')}")
    passou = sum(1 for r in res if r.get("ok"))
    print(f"\nPORTÃO ({a.llm}, arquitectura {a.arquitectura}): {passou}/{len(res)}")


if __name__ == "__main__":
    main()
