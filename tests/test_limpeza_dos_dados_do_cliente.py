"""A limpeza única do que já ficou guardado (core/privacidade/limpeza.py).

Sem Postgres na CI: a base é falsa e responde às consultas que a limpeza faz.
O que se fixa é o comportamento — o que é contado, o que é apagado, o que é
reescrito, e que uma segunda corrida não faz nada. O SQL em si (jsonb,
to_regclass, CAST AS vector) só se prova contra um Postgres real: correr o
script em dry-run primeiro.
"""

from __future__ import annotations

import asyncio
import re

import pytest

from core.privacidade import limpeza
from core.privacidade.limpeza import descricao_sem_valores, texto_sem_valores

# ── As pistas de valores ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "antes,depois",
    [
        ("Possible values: 'paid', 'sent'", None),
        ("Estado da fatura. Possible values: 'paid', 'sent'", "Estado da fatura"),
        ("Estado. Possible values: 'a. b', 'c'", "Estado"),
        ("Sem pista", "Sem pista"),
        (None, None),
        ("", ""),
    ],
)
def test_descricao_sem_valores(antes, depois):
    assert descricao_sem_valores(antes) == depois


def test_texto_renderizado_perde_so_a_linha_da_pista():
    antes = (
        "Column vendas.estado\n"
        "Type: text\n"
        "Description: Estado. Possible values: 'Joana', 'Rui'\n"
        "Nullable: True  |  PII: False"
    )
    depois = texto_sem_valores(antes)
    assert "Joana" not in depois
    assert "Description: Estado\n" in depois
    assert "Nullable: True" in depois


# ── A limpeza de uma base ────────────────────────────────────────────────


class _R:
    def __init__(self, escalar=None, linhas=None):
        self._e, self._l = escalar, linhas or []

    def scalar(self):
        return self._e

    def all(self):
        return list(self._l)


class _BaseFalsa:
    """Uma base pequena em memória que entende as consultas da limpeza."""

    def __init__(self):
        self.tabelas = {
            "semantic_cache",
            "pipeline_jobs",
            "table_metadata",
            "embeddings",
            "context_documents",
            "checkpoints",
            "checkpoint_writes",
        }
        self.cache_vencidas = 2
        self.cache_com_linhas = 3
        self.pipeline_com_result = 4
        self.table_metadata = {"t1": "Estado. Possible values: 'Joana'", "t2": "ok"}
        self.embeddings = {"e1": "Description: X. Possible values: 'Rui'\nType: t"}
        self.context_documents = {
            "c1": ("Column: v.x", "Description: Possible values: 'Ana'")
        }
        self.sql: list[str] = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        q = str(stmt)
        self.sql.append(q)
        p = params or {}
        if q.startswith("SELECT to_regclass"):
            return _R(p["t"] in self.tabelas)
        if "count(*) FROM semantic_cache WHERE created_at" in q:
            return _R(self.cache_vencidas)
        if "count(*) FROM semantic_cache WHERE CASE" in q:
            return _R(self.cache_com_linhas)
        if q.startswith("DELETE FROM semantic_cache"):
            self.cache_vencidas = 0
            return _R()
        if q.startswith("UPDATE semantic_cache"):
            self.cache_com_linhas = 0
            return _R()
        if "count(*) FROM pipeline_jobs" in q:
            return _R(self.pipeline_com_result)
        if q.startswith("UPDATE pipeline_jobs"):
            self.pipeline_com_result = 0
            return _R()
        if q.startswith("DROP TABLE"):
            for t in re.findall(r"checkpoint\w*", q):
                self.tabelas.discard(t)
            return _R()
        if "FROM table_metadata WHERE description LIKE" in q:
            return _R(
                linhas=[
                    (k, v)
                    for k, v in self.table_metadata.items()
                    if "Possible values:" in (v or "")
                ]
            )
        if q.startswith("UPDATE table_metadata"):
            self.table_metadata[p["id"]] = p["d"]
            return _R()
        if "FROM embeddings WHERE text LIKE" in q:
            return _R(
                linhas=[
                    (k, v, None)
                    for k, v in self.embeddings.items()
                    if "Possible values:" in v
                ]
            )
        if q.startswith("UPDATE embeddings"):
            self.embeddings[p["id"]] = p["t"]
            return _R()
        if "FROM context_documents WHERE body LIKE" in q:
            return _R(
                linhas=[
                    (k, b, t)
                    for k, (t, b) in self.context_documents.items()
                    if "Possible values:" in b
                ]
            )
        if q.startswith("UPDATE context_documents"):
            t, _ = self.context_documents[p["id"]]
            self.context_documents[p["id"]] = (t, p["t"])
            return _R()
        raise AssertionError(f"consulta inesperada: {q}")

    async def commit(self):
        self.commits += 1


def _embebidos():
    vistos = []

    async def embed(textos):
        vistos.extend(textos)
        return [[0.1, 0.2] for _ in textos]

    return embed, vistos


def test_dry_run_so_conta():
    db = _BaseFalsa()
    embed, vistos = _embebidos()
    rel = asyncio.run(limpeza.limpar_base(db, "x", a_serio=False, embedder=embed))
    assert rel.contagens["cache_vencidas_apagadas"] == 2
    assert rel.contagens["cache_linhas_retiradas"] == 3
    assert rel.contagens["pipeline_results_esvaziados"] == 4
    assert rel.contagens["checkpoint_tabelas_apagadas"] == 2
    assert rel.contagens["table_metadata_valores_retirados"] == 1
    assert rel.contagens["embeddings_valores_retirados"] == 1
    assert rel.contagens["context_documents_valores_retirados"] == 1
    escritas = [q for q in db.sql if q.split()[0] in ("UPDATE", "DELETE", "DROP")]
    assert escritas == [] and db.commits == 0 and vistos == []


def test_a_serio_limpa_tudo_e_a_segunda_corrida_nao_faz_nada():
    db = _BaseFalsa()
    embed, vistos = _embebidos()
    asyncio.run(limpeza.limpar_base(db, "x", a_serio=True, embedder=embed))

    assert db.commits == 1
    assert db.table_metadata == {"t1": "Estado", "t2": "ok"}
    assert "Rui" not in db.embeddings["e1"]
    assert "Ana" not in db.context_documents["c1"][1]
    assert not {"checkpoints", "checkpoint_writes"} & db.tabelas
    # O vector é recalculado a partir do texto JÁ limpo.
    assert vistos and all("Possible values" not in t for t in vistos)
    assert any(t.startswith("Column: v.x\n") for t in vistos)

    # O UPDATE da cache tira as linhas e deixa a marca para o acerto.
    upd = next(q for q in db.sql if q.startswith("UPDATE semantic_cache"))
    assert "'data_sample', '[]'::jsonb" in upd and "'rows_omitted', true" in upd

    rel2 = asyncio.run(limpeza.limpar_base(db, "x", a_serio=True, embedder=embed))
    assert all(v == 0 for v in rel2.contagens.values()), rel2


def test_sem_embedder_nao_deixa_texto_e_vector_desencontrados():
    db = _BaseFalsa()
    with pytest.raises(RuntimeError):
        asyncio.run(limpeza.limpar_base(db, "x", a_serio=True, embedder=None))


def test_base_sem_as_tabelas_nao_falha():
    db = _BaseFalsa()
    db.tabelas = set()
    rel = asyncio.run(limpeza.limpar_base(db, "x", a_serio=True))
    assert rel.contagens == {"checkpoint_tabelas_apagadas": 0}
