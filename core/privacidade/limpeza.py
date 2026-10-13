"""Limpeza dos dados do cliente que já ficaram guardados (uma vez, idempotente).

Corre por ``scripts/limpar_dados_do_cliente.py`` em cada base (plataforma e
clientes). Cada passo é seguro de repetir: a segunda corrida não encontra nada.

1. ``semantic_cache`` — apaga o que passou do prazo e tira ``data_sample`` do
   resto (deixando a marca ``rows_omitted`` para o acerto ir à fonte).
2. ``pipeline_jobs.result`` — esvazia (o router foi removido).
3. Tabelas do checkpointer do LangGraph — apaga (o grafo já não as usa).
4. «Possible values: 'a', 'b'» — valores reais que o conector Postgres do
   backend escrevia nas descrições das colunas: sai de ``table_metadata``,
   e do texto de ``embeddings`` e ``context_documents`` (com o vector
   recalculado, porque o vector antigo foi feito COM os valores).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from core.privacidade.cache_semantico import LINHAS_OMITIDAS, limite_de_validade

MARCA_DOS_VALORES = "Possible values:"

# Numa descrição, a pista vinha sempre no FIM ("<comentário>. Possible values: …").
_PISTA_ATE_AO_FIM = re.compile(r"\.?\s*Possible values:.*\Z", re.S)
# Num texto renderizado (embeddings, context_documents), a descrição é uma
# linha entre outras: corta-se só até ao fim da linha.
_PISTA_ATE_AO_FIM_DA_LINHA = re.compile(r"\.?[ \t]*Possible values:[^\n]*")

TABELAS_DO_CHECKPOINTER = (
    "checkpoint_writes",
    "checkpoint_blobs",
    "checkpoints",
    "checkpoint_migrations",
)


def descricao_sem_valores(descricao: Optional[str]) -> Optional[str]:
    """Tira a pista de valores de uma descrição; vazia passa a ``None``."""
    if not descricao or MARCA_DOS_VALORES not in descricao:
        return descricao
    limpa = _PISTA_ATE_AO_FIM.sub("", descricao).strip()
    return limpa or None


def texto_sem_valores(texto: str) -> str:
    """Tira a pista de valores de um texto com várias linhas."""
    if not texto or MARCA_DOS_VALORES not in texto:
        return texto
    return _PISTA_ATE_AO_FIM_DA_LINHA.sub("", texto)


@dataclass
class Relatorio:
    base: str
    contagens: Dict[str, int] = field(default_factory=dict)

    def __str__(self) -> str:
        partes = ", ".join(f"{k}={v}" for k, v in self.contagens.items()) or "nada"
        return f"{self.base}: {partes}"


Embedder = Callable[[Sequence[str]], Awaitable[List[List[float]]]]


async def _existe(db: Any, tabela: str) -> bool:
    from sqlalchemy import text

    r = await db.execute(text("SELECT to_regclass(:t) IS NOT NULL"), {"t": tabela})
    return bool(r.scalar())


def _vector(v: Sequence[float]) -> str:
    return "[" + ",".join(str(float(x)) for x in v) + "]"


async def limpar_base(
    db: Any,
    nome: str,
    *,
    a_serio: bool,
    embedder: Optional[Embedder] = None,
) -> Relatorio:
    """Aplica os quatro passos a UMA base. ``a_serio=False`` só conta."""
    from sqlalchemy import text

    rel = Relatorio(nome)
    corte = limite_de_validade()

    # 1. semantic_cache ─────────────────────────────────────────────────
    if await _existe(db, "semantic_cache"):
        cond_vencidas = "created_at IS NULL OR created_at < :corte"
        cond_com_linhas = (
            "CASE WHEN jsonb_typeof(response_json::jsonb -> 'data_sample') = 'array' "
            "THEN jsonb_array_length(response_json::jsonb -> 'data_sample') > 0 "
            "ELSE false END"
        )
        vencidas = (
            await db.execute(
                text(f"SELECT count(*) FROM semantic_cache WHERE {cond_vencidas}"),
                {"corte": corte},
            )
        ).scalar() or 0
        com_linhas = (
            await db.execute(
                text(f"SELECT count(*) FROM semantic_cache WHERE {cond_com_linhas}")
            )
        ).scalar() or 0
        if a_serio:
            await db.execute(
                text(f"DELETE FROM semantic_cache WHERE {cond_vencidas}"),
                {"corte": corte},
            )
            await db.execute(
                text(
                    "UPDATE semantic_cache SET response_json = "
                    "(response_json::jsonb || jsonb_build_object("
                    f"'data_sample', '[]'::jsonb, '{LINHAS_OMITIDAS}', true))::json "
                    f"WHERE {cond_com_linhas}"
                )
            )
        rel.contagens["cache_vencidas_apagadas"] = int(vencidas)
        rel.contagens["cache_linhas_retiradas"] = int(com_linhas)

    # 2. pipeline_jobs.result ───────────────────────────────────────────
    if await _existe(db, "pipeline_jobs"):
        n = (
            await db.execute(
                text("SELECT count(*) FROM pipeline_jobs WHERE result IS NOT NULL")
            )
        ).scalar() or 0
        if a_serio and n:
            await db.execute(
                text("UPDATE pipeline_jobs SET result = NULL WHERE result IS NOT NULL")
            )
        rel.contagens["pipeline_results_esvaziados"] = int(n)

    # 3. checkpointer do LangGraph ──────────────────────────────────────
    existentes = [t for t in TABELAS_DO_CHECKPOINTER if await _existe(db, t)]
    if existentes and a_serio:
        await db.execute(text("DROP TABLE IF EXISTS " + ", ".join(existentes)))
    rel.contagens["checkpoint_tabelas_apagadas"] = len(existentes)

    # 4. «Possible values:» ────────────────────────────────────────────
    padrao = {"marca": f"%{MARCA_DOS_VALORES}%"}
    if await _existe(db, "table_metadata"):
        linhas = (
            await db.execute(
                text(
                    "SELECT id, description FROM table_metadata "
                    "WHERE description LIKE :marca"
                ),
                padrao,
            )
        ).all()
        if a_serio:
            for id_, descricao in linhas:
                await db.execute(
                    text("UPDATE table_metadata SET description = :d WHERE id = :id"),
                    {"d": descricao_sem_valores(descricao), "id": id_},
                )
        rel.contagens["table_metadata_valores_retirados"] = len(linhas)

    for tabela, coluna_texto, com_titulo in (
        ("embeddings", "text", False),
        ("context_documents", "body", True),
    ):
        if not await _existe(db, tabela):
            continue
        titulo = "title" if com_titulo else "NULL"
        linhas = (
            await db.execute(
                text(
                    f"SELECT id, {coluna_texto}, {titulo} FROM {tabela} "
                    f"WHERE {coluna_texto} LIKE :marca"
                ),
                padrao,
            )
        ).all()
        rel.contagens[f"{tabela}_valores_retirados"] = len(linhas)
        if not a_serio or not linhas:
            continue
        if embedder is None:
            raise RuntimeError(
                f"{nome}: {len(linhas)} linhas de {tabela} com valores, e sem "
                "embedder para recalcular o vector"
            )
        textos = [texto_sem_valores(t) for _, t, _ in linhas]
        a_embeber = [
            f"{ti}\n{te}" if ti else te for (_, _, ti), te in zip(linhas, textos)
        ]
        vectores = await embedder(a_embeber)
        for (id_, _, _), novo, vec in zip(linhas, textos, vectores):
            await db.execute(
                text(
                    f"UPDATE {tabela} SET {coluna_texto} = :t, "
                    "embedding = CAST(:v AS vector) WHERE id = :id"
                ),
                {"t": novo, "v": _vector(vec), "id": id_},
            )

    if a_serio:
        await db.commit()
    return rel
