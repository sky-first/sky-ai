# -*- coding: utf-8 -*-
"""Tabelas que SAÍRAM de uma ligação têm de sair também do índice da IA.

Fontes do sistema, lacuna L1/L4 (desenho §3.5 e §8): desligar uma fonte
pública faz ``REVOKE`` no Postgres e o backend volta a sincronizar a ligação
«Dados públicos» — a tabela deixa de estar em ``connection_metadata``. Mas a
descoberta do sky-ai só apagava o que ia reinserir:

- ``ingest_from_connection_metadata_cache`` apaga as linhas do ÂMBITO do
  pedido (este projecto, sem equipa) e, com ``table_names``, só essas — as
  linhas de outros âmbitos (outro projecto, uma equipa, as globais de demo)
  e as tabelas fora da lista ficavam;
- com o catálogo VAZIO (a última fonte desligada) saía logo no início
  (``if not tables_json: return 0``), sem apagar nada;
- a cache semântica só era limpa pela ligação: uma resposta mista guardada
  debaixo da ligação do CLIENTE (que usou ``gasolineras_precio`` pelo merger)
  continuava a responder com dados de uma fonte já desligada (S7).

O resultado: o orquestrador continuava a ver e a escolher tabelas que o
Postgres agora recusa, e a cache servia números que o cliente deixou de
pagar. Esta poda corre ANTES da ingestão, em todos os âmbitos, contra o
catálogo actual da ligação.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set

from sqlalchemy import text

from core.logging_utils import log_event


def _ultimo(nome: str) -> str:
    return (nome or "").replace('"', "").split(".")[-1].strip()


def nomes_no_catalogo(tables_json: Any) -> Set[str]:
    """Nomes (último segmento) das tabelas em ``connection_metadata.tables``."""
    nomes: Set[str] = set()
    if isinstance(tables_json, dict):
        iterador: Iterable = tables_json.keys()
        for n in iterador:
            if n:
                nomes.add(_ultimo(str(n)))
        return nomes
    for t in tables_json or []:
        if isinstance(t, dict):
            n = t.get("table_name") or t.get("name")
            if n:
                nomes.add(_ultimo(str(n)))
    return nomes


def tabelas_removidas(no_indice: Iterable[str], no_catalogo: Set[str]) -> List[str]:
    return sorted({n for n in no_indice if n and _ultimo(n) not in no_catalogo})


async def catalogo_difere_do_indice(db, connection_id: str) -> bool:
    """O catálogo da ligação tem tabelas a mais ou a menos do que o índice?

    O guarda «descoberta recente» do ``/discover`` saltava a descoberta
    quando o backend tinha acabado de sincronizar e havia linhas indexadas —
    exactamente o que acontece ao marcar/desmarcar uma fonte pública: o
    ``sync_connection`` refresca ``connection_metadata`` e logo a seguir pede
    a descoberta, que era saltada. A tabela nova nunca entrava (o «marcar e
    perguntar já» falhava) e a removida nunca saía. Com o conjunto diferente,
    não há nada de recente para reaproveitar.
    """
    try:
        row = (
            await db.execute(
                text(
                    "SELECT tables FROM connection_metadata "
                    "WHERE CAST(connection_id AS text) = :cid LIMIT 1"
                ),
                {"cid": str(connection_id)},
            )
        ).first()
        if row is None:
            return False
        catalogo = nomes_no_catalogo(row[0])
        indice = {
            _ultimo(r[0])
            for r in (
                await db.execute(
                    text(
                        "SELECT DISTINCT table_name FROM table_metadata "
                        "WHERE CAST(data_connection_id AS text) = :cid"
                    ),
                    {"cid": str(connection_id)},
                )
            ).fetchall()
            if r[0]
        }
        return catalogo != indice
    except Exception:
        try:
            await db.rollback()
        except Exception:
            pass
        return False


async def podar_tabelas_removidas(db, connection_id: str) -> Dict[str, Any]:
    """Apaga do índice (metadados, embeddings, cache) as tabelas que saíram.

    Sem linha em ``connection_metadata`` não se sabe o catálogo — não se apaga
    nada (uma ligação nunca sincronizada não tem nada indexado). Com a linha e
    a lista vazia, o catálogo é vazio e sai tudo. Nunca rebenta: uma falha
    aqui não pode impedir a descoberta.
    """
    resultado: Dict[str, Any] = {
        "removidas": [],
        "metadados": 0,
        "embeddings": 0,
        "cache": 0,
    }
    try:
        row = (
            await db.execute(
                text(
                    "SELECT tables FROM connection_metadata "
                    "WHERE CAST(connection_id AS text) = :cid LIMIT 1"
                ),
                {"cid": str(connection_id)},
            )
        ).first()
        if row is None:
            return resultado
        catalogo = nomes_no_catalogo(row[0])

        no_indice = [
            r[0]
            for r in (
                await db.execute(
                    text(
                        "SELECT DISTINCT table_name FROM table_metadata "
                        "WHERE CAST(data_connection_id AS text) = :cid"
                    ),
                    {"cid": str(connection_id)},
                )
            ).fetchall()
        ]
        removidas = tabelas_removidas(no_indice, catalogo)
        # Embeddings de descrição de conjunto (sem table_metadata_id) também.
        desc = [
            r[0]
            for r in (
                await db.execute(
                    text(
                        "SELECT DISTINCT metadata->>'table_name' FROM embeddings "
                        "WHERE metadata->>'kind' = 'dataset_description' "
                        "AND metadata->>'data_connection_id' = :cid"
                    ),
                    {"cid": str(connection_id)},
                )
            ).fetchall()
        ]
        removidas_desc = tabelas_removidas(desc, catalogo)
        todas = sorted(set(removidas) | set(removidas_desc))
        if not todas:
            return resultado

        p = {"cid": str(connection_id), "nomes": removidas}
        n_emb = 0
        n_tm = 0
        if removidas:
            r1 = await db.execute(
                text(
                    "DELETE FROM embeddings WHERE table_metadata_id IN ("
                    " SELECT id FROM table_metadata"
                    " WHERE CAST(data_connection_id AS text) = :cid"
                    " AND table_name = ANY(:nomes))"
                ),
                p,
            )
            n_emb += int(getattr(r1, "rowcount", 0) or 0)
            r2 = await db.execute(
                text(
                    "DELETE FROM table_metadata "
                    "WHERE CAST(data_connection_id AS text) = :cid "
                    "AND table_name = ANY(:nomes)"
                ),
                p,
            )
            n_tm = int(getattr(r2, "rowcount", 0) or 0)
        if removidas_desc:
            r3 = await db.execute(
                text(
                    "DELETE FROM embeddings "
                    "WHERE metadata->>'kind' = 'dataset_description' "
                    "AND metadata->>'data_connection_id' = :cid "
                    "AND metadata->>'table_name' = ANY(:nomes)"
                ),
                {"cid": str(connection_id), "nomes": removidas_desc},
            )
            n_emb += int(getattr(r3, "rowcount", 0) or 0)

        # Cache semântica: as respostas desta ligação E as de qualquer ligação
        # que tenham usado estas tabelas (perguntas mistas pelo merger ficam
        # guardadas debaixo da ligação do cliente). Os nomes das tabelas de
        # dados públicos são distintivos (gasolineras_precio, festivos…).
        padroes = [f"%{n}%" for n in todas]
        r4 = await db.execute(
            text(
                "DELETE FROM semantic_cache "
                "WHERE CAST(connection_id AS text) = :cid "
                "OR CAST(response_json AS text) ILIKE ANY(:padroes)"
            ),
            {"cid": str(connection_id), "padroes": padroes},
        )
        n_cache = int(getattr(r4, "rowcount", 0) or 0)
        await db.commit()

        resultado = {
            "removidas": todas,
            "metadados": n_tm,
            "embeddings": n_emb,
            "cache": n_cache,
        }
        log_event(
            "discover_tabelas_removidas_podadas",
            {"connection_id": connection_id, **resultado},
        )
        return resultado
    except Exception as exc:
        try:
            await db.rollback()
        except Exception:
            pass
        log_event(
            "discover_poda_falhou",
            {"connection_id": connection_id, "error": str(exc)[:300]},
        )
        return resultado
