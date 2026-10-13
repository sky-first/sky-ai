"""A cache semântica sem linhas do cliente.

Até 13/10/2026 a ``semantic_cache.response_json`` guardava o ``QueryResponse``
inteiro, com ``data_sample`` = as primeiras 15 linhas do resultado, sem prazo.
Era uma cópia permanente de dados do cliente na nossa base.

Agora:

* **Escrita** — ``payload_para_cache`` grava a resposta com ``data_sample=[]``
  e uma marca (``LINHAS_OMITIDAS``) a dizer se a resposta original tinha
  linhas. Não se grava quantas nem quais.
* **Leitura** — num acerto, as linhas guardadas são SEMPRE ignoradas (mesmo
  numa linha antiga que ainda as tenha). Se a resposta original tinha linhas,
  ``repor_linhas`` volta a correr o SQL guardado (``meta.sql``) na fonte do
  cliente. Se não conseguir, o acerto é tratado como falha de cache e a
  pergunta segue o caminho normal — nunca se serve um gráfico vazio.
* **Prazo** — uma linha com mais de ``DIAS_DE_VIDA`` dias nunca é servida e é
  apagada na escrita seguinte para a mesma ligação. O script
  ``scripts/limpar_dados_do_cliente.py`` limpa o que já lá está.

Uma resposta cujas linhas foram bloqueadas pelo detector de PII chega aqui com
``data_sample=[]``: fica sem a marca e o acerto nunca as vai buscar.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

#: Linhas da cache com mais do que isto nunca são servidas, e são apagadas.
DIAS_DE_VIDA = 30

#: Marca gravada no ``response_json``: a resposta original tinha linhas.
LINHAS_OMITIDAS = "rows_omitted"

#: Quantas linhas uma resposta mostra (o mesmo ``data[:15]`` do pipeline).
LINHAS_NA_AMOSTRA = 15


def limite_de_validade(agora: Optional[datetime] = None) -> datetime:
    """O ``created_at`` mais antigo que ainda pode ser servido (UTC, naive,
    como o ``default=datetime.utcnow`` da coluna)."""
    return (agora or datetime.utcnow()) - timedelta(days=DIAS_DE_VIDA)


def payload_para_cache(response: Any) -> Dict[str, Any]:
    """O ``response_json`` a gravar: a resposta sem as linhas do cliente."""
    payload = response.model_dump(mode="json")
    tinha_linhas = bool(payload.get("data_sample"))
    payload["data_sample"] = []
    payload[LINHAS_OMITIDAS] = tinha_linhas
    return payload


def precisa_de_linhas(cached_json: Dict[str, Any]) -> bool:
    """A resposta guardada tinha linhas (e por isso tem de as ir buscar)?

    Aceita também as linhas antigas, gravadas antes desta regra, que ainda
    trazem ``data_sample`` cheio: essas também precisam — e o que trazem não
    é usado.
    """
    if cached_json.get(LINHAS_OMITIDAS):
        return True
    return bool(cached_json.get("data_sample"))


def sem_linhas(cached_json: Dict[str, Any]) -> Dict[str, Any]:
    """Uma cópia do ``response_json`` sem as linhas guardadas e sem a marca."""
    limpo = dict(cached_json)
    limpo["data_sample"] = []
    limpo.pop(LINHAS_OMITIDAS, None)
    return limpo


async def repor_linhas(
    db: Any, connection_id: str, sql: Optional[str]
) -> Optional[List[Dict[str, Any]]]:
    """Volta a correr ``sql`` na fonte do cliente e devolve a amostra.

    Devolve ``None`` quando não dá (sem SQL, ligação desaparecida, fonte em
    baixo, SQL multi-fonte que a ligação principal não sabe correr): quem
    chama trata como falha de cache. Nunca levanta.
    """
    if not sql or not sql.strip():
        return None
    try:
        from sqlalchemy import text

        from api.routes.connection_query import _dispatch_map_from_conn_rows

        resultado = await db.execute(
            text(
                "SELECT id, name, connector_id AS type, config "
                "FROM data_connections WHERE id = :id"
            ),
            {"id": connection_id},
        )
        linha = resultado.first()
        if not linha:
            return None
        fontes = _dispatch_map_from_conn_rows([linha])
        fonte = fontes.get(str(linha[0]))
        if fonte is None:
            return None
        dados = await asyncio.to_thread(fonte.run_query, sql)
    except Exception as exc:  # noqa: BLE001 — falha = cache miss
        from core.logging_utils import log_event

        # A sessão segue para o pipeline: não a deixar numa transacção falhada.
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass

        log_event(
            "semantic_cache_rerun_failed",
            {"connection_id": connection_id, "error_type": type(exc).__name__},
        )
        return None
    if not isinstance(dados, list):
        return None
    return dados[:LINHAS_NA_AMOSTRA]
