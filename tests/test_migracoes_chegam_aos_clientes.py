"""As migrações SQL do sky-ai também têm de correr nas bases dos CLIENTES.

**Ter as tabelas não é ter o esquema.** O `sync_tenants` verificava se as
tabelas existiam, dizia «já tem tudo» e devolvia — e as migrações SQL, que são
as que trazem as COLUNAS e os TIPOS, corriam só contra a base da plataforma.

Medido em produção a 22/08/2026, no cliente `sandbox`, com o Job a escrever
«sandbox: já tem tudo» na mesma hora em que o serviço escrevia nos logs:

    operator does not exist: json <=> unknown
    column "user_id" of relation "semantic_cache" does not exist
    relation "query_audit_log" does not exist

São, uma a uma, as migrações 005, 004 e 001.

O efeito não é cosmético: sem cache semântica cada pergunta paga o custo
inteiro do LLM, e sem `query_audit_log` o perfilador falha. Foi por isto que
alguém já escreveu DDL À MÃO na base do GBT — e o cliente seguinte nasceu com
o mesmo defeito, porque a correcção foi na base e não no caminho.
"""

from __future__ import annotations

import glob
import inspect
import os
import pathlib


def _fonte_sem_comentarios() -> str:
    import scripts.sync_tenants as m

    return "\n".join(
        l
        for l in inspect.getsource(m).splitlines()
        if not l.lstrip().startswith("#")
    )


def test_as_migracoes_sql_correm_por_cliente():
    fonte = _fonte_sem_comentarios()
    assert "async def _correr_migracoes_sql" in fonte
    assert "await _correr_migracoes_sql(slug, pura, a_serio)" in fonte


def test_ter_as_tabelas_ja_nao_termina_o_trabalho():
    """O defeito era um `return` cedo demais.

    Com as tabelas presentes, saía-se antes de correr as migrações — e é
    exactamente esse o estado de um cliente que já foi criado uma vez e nunca
    mais viu uma migração.
    """
    fonte = _fonte_sem_comentarios()
    assert 'print(f"  {slug}: já tem tudo")' not in fonte
    i = fonte.index("if not em_falta:")
    # A seguir a «não falta nenhuma tabela» NÃO pode vir um return.
    assert "return" not in fonte[i : i + 200]


def test_uma_migracao_ja_aplicada_nao_trava_as_outras():
    """São escritas para serem repetidas. Uma que se queixe não pode levar as
    seguintes atrás — senão a primeira repetida bloqueava todas."""
    import scripts.sync_tenants as m

    fonte = inspect.getsource(m._correr_migracoes_sql)
    ciclo = fonte.index("for f in ficheiros:")
    depois = fonte[ciclo:]
    assert "try:" in depois
    assert "except Exception" in depois


def test_a_pasta_das_migracoes_existe_e_tem_as_que_importam():
    """Se a pasta mudar de sítio, o script fica a correr zero ficheiros e a
    dizer que está tudo bem — que é a forma silenciosa deste defeito voltar."""
    from scripts.sync_tenants import PASTA_DAS_MIGRACOES

    raiz = pathlib.Path(__file__).resolve().parent.parent
    ficheiros = sorted(
        os.path.basename(f) for f in glob.glob(str(raiz / PASTA_DAS_MIGRACOES / "*.sql"))
    )
    assert ficheiros, f"nenhuma migração em {PASTA_DAS_MIGRACOES}"
    # As três que faltavam ao sandbox.
    assert "001_create_query_audit_log.sql" in ficheiros
    assert "004_add_user_id_to_semantic_cache.sql" in ficheiros
    assert "005_migrate_embeddings_to_1024.sql" in ficheiros
