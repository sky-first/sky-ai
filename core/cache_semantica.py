"""O que entra na chave da cache semântica, e o que nunca lá fica.

── Porque é que isto existe (16/10/2026) ───────────────────────────────

Sandbox, projecto «Logística y Transporte». Depois do promote de sky-ai
1a22f72c (#297: as fatias e o merger passam a ler as métricas e o
glossário) e de o job da demo gravar o termo «Porte fuera de plazo» e a
métrica «Vehículos que no se pagan», «¿Qué vehículos no se pagan?» e
«¿Qué camiones no se pagan?» devolveram 2/2 o MESMO texto da véspera:
«No hay vehículos que no se paguen en el periodo analizado…». Na base,
03-GH-19 tem aportação −15.936 €. Logs de produção:

    semantic_cache_hit  similarity_score 1.0     «¿Qué vehículos no se pagan?»
    semantic_cache_hit  similarity_score 0.9583  «¿Qué camiones no se pagan?»
    query_total_timing  cache_hit true, llm_calls 0

A resposta tinha sido gravada já com a versão 4 da cache, ANTES de o
glossário mudar. A chave da cache era (ligação, espaço, equipa, língua,
versão, período) e a pergunta — nada do que o espaço DEFINE. Mudar uma
métrica, um termo ou as instruções não tocava em nenhuma dessas
dimensões, e a resposta antiga continuava válida até ao fim do prazo
(30 dias).

── Duas regras ─────────────────────────────────────────────────────────

1. **A impressão digital das definições faz parte da chave.** O backend
   manda no pedido tudo o que o motor vai ler sobre o espaço: as métricas
   e o glossário (``# Trusted metrics`` / ``# Glossary`` dentro de
   ``instructions``), as instruções de SQL, as tabelas autorizadas, as
   regras de segurança. ``impressao_das_definicoes`` resume isso num hash;
   uma linha da cache só é servida a um pedido com o MESMO hash.

   Porquê aqui e não «apagar a cache quando o backend semeia/sincroniza»:
   as definições mudam por muitos caminhos (ecrã do glossário, ecrã das
   métricas, seeds das demos, instruções do espaço/equipa, métricas
   pessoais) e cada um teria de se lembrar de invalidar — o primeiro que
   se esquecesse voltava a servir respostas velhas, em silêncio. O hash
   vê o que o motor vê, venha de onde vier. As linhas antigas deixam
   simplesmente de coincidir e saem pelo prazo normal.

   O que NÃO entra: a pergunta (já é o embedding), a conversa
   (``chat_history``) e o utilizador (já é o ``user_id`` no modo pessoal).

2. **Respostas de «0 linhas» e negativas nunca ficam na cache** (nem são
   servidas, se lá estiverem). «No hay…» é a resposta mais perigosa de
   repetir: é a que mais vezes vem de um SQL errado (um filtro a mais, uma
   junção que perde linhas) e é a que ninguém confere, porque não traz
   números. Uma resposta com dados pode ser re-verificada (o SQL volta a
   correr num acerto); uma negativa não tem nada para re-verificar.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, Iterable, Optional

#: Campos do pedido que mudam o que o motor sabe (ou pode ver) do espaço.
#: Texto livre: normalizado linha a linha (ver ``_texto``).
_CAMPOS_DE_TEXTO = ("instructions", "sql_instructions")

#: Listas cuja ordem não muda nada: entram ordenadas.
_CAMPOS_DE_CONJUNTO = (
    "authorized_tables",
    "selected_datasets",
    "connection_ids",
    "space_ids",
    "mentioned_file_ids",
)

#: Escalares de comportamento (tom, estilo, formato, modo de agente).
_CAMPOS_ESCALARES = (
    "ai_tone",
    "ai_style",
    "creativity",
    "length",
    "response_format",
    "agent_mode",
)


def _texto(valor: Optional[str]) -> str:
    """Linhas sem espaços à volta, sem vazias, ordenadas.

    A ordem das linhas não muda a definição — e o backend lista as
    métricas pela ordem da consulta, que não é garantida. Sem ordenar, o
    mesmo glossário dava hashes diferentes e a cache nunca acertava.
    """
    linhas = [x.strip() for x in str(valor or "").splitlines()]
    return "\n".join(sorted(x for x in linhas if x))


def _conjunto(valor: Optional[Iterable[Any]]) -> list:
    return sorted({str(x) for x in (valor or [])})


def _estruturado(valor: Any) -> Any:
    if valor is None:
        return None
    if hasattr(valor, "model_dump"):
        valor = valor.model_dump(mode="json")
    if isinstance(valor, dict):
        return {str(k): _estruturado(v) for k, v in sorted(valor.items())}
    if isinstance(valor, (list, tuple, set)):
        return [_estruturado(v) for v in valor]
    return valor


def impressao_das_definicoes(body: Any) -> str:
    """Hash (32 hex) de tudo o que o pedido diz sobre o espaço.

    Dois pedidos com as mesmas métricas, glossário, instruções e regras de
    acesso têm a mesma impressão; mudar uma vírgula numa definição muda-a.
    """
    partes: Dict[str, Any] = {}
    for campo in _CAMPOS_DE_TEXTO:
        partes[campo] = _texto(getattr(body, campo, None))
    for campo in _CAMPOS_DE_CONJUNTO:
        partes[campo] = _conjunto(getattr(body, campo, None))
    for campo in _CAMPOS_ESCALARES:
        valor = getattr(body, campo, None)
        partes[campo] = None if valor is None else str(valor)
    partes["security_config"] = _estruturado(getattr(body, "security_config", None))
    partes["selected_context"] = {
        str(k): _conjunto(v)
        for k, v in sorted((getattr(body, "selected_context", None) or {}).items())
    }
    bruto = json.dumps(partes, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:32]


# ── respostas que não se guardam ────────────────────────────────────────

#: Começo de uma resposta que nega a existência do que se perguntou, nas
#: três línguas da plataforma. Só conta quando a resposta não traz linhas.
_NEGATIVA = re.compile(
    r"^\W*(?:"
    # es
    r"no\s+(?:hay|existe[n]?|se\s+(?:han\s+)?encontra|encontr|tenemos|consta)"
    r"|ning[uú]n[oa]?\s"
    r"|sin\s+(?:datos|resultados)"
    # pt
    r"|n[aã]o\s+(?:h[aá]|existe[m]?|foram\s+encontrad|encontr|temos|consta)"
    r"|nenhu[mn]a?\s"
    r"|sem\s+(?:dados|resultados)"
    # en
    r"|there\s+(?:are|is|were|was)\s+no\b"
    r"|no\s+(?:data|results?|rows?|records?|matching)\b"
    r"|none\s+of\b"
    r"|i\s+(?:could\s+not|couldn['’]t|did\s+not|didn['’]t)\s+find"
    r")",
    re.IGNORECASE,
)

#: Tabelas em memória do merger multi-fonte (DuckDB): ``dataset_1``… O SQL
#: final de uma resposta multi-fonte só existe dentro do pedido — voltar a
#: corrê-lo na ligação principal dá sempre «relation dataset_1 does not
#: exist» (visto em produção a 16/10: ``semantic_cache_rerun_failed`` em
#: TODAS as perguntas multi-fonte). Guardá-la só enchia a tabela.
_SQL_DO_MERGER = re.compile(r"\bdataset_\d+\b", re.IGNORECASE)


def _meta(resposta: Any) -> Dict[str, Any]:
    if isinstance(resposta, dict):
        return dict(resposta.get("meta") or {})
    meta = getattr(resposta, "meta", None)
    if meta is None:
        return {}
    if hasattr(meta, "model_dump"):
        return meta.model_dump()
    return dict(meta)


def _resposta_texto(resposta: Any) -> str:
    if isinstance(resposta, dict):
        return str(resposta.get("answer") or "")
    return str(getattr(resposta, "answer", "") or "")


def e_negativa_ou_vazia(resposta: Any) -> bool:
    """A resposta diz que não há nada (ou o SQL dela não trouxe linhas)?

    Aceita o ``QueryResponse`` ou o ``response_json`` guardado.
    """
    meta = _meta(resposta)
    linhas = meta.get("num_rows") or 0
    if meta.get("sql") and not linhas:
        return True
    return not linhas and bool(_NEGATIVA.match(_resposta_texto(resposta)))


def motivo_para_nao_guardar(resposta: Any, tinha_linhas: bool) -> Optional[str]:
    """``None`` se a resposta pode ir para a cache; senão, o porquê."""
    if e_negativa_ou_vazia(resposta):
        return "negative_or_empty"
    sql = _meta(resposta).get("sql") or ""
    if tinha_linhas and _SQL_DO_MERGER.search(sql):
        return "sql_not_rerunnable"
    return None
