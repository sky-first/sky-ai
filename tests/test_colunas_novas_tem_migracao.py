"""Uma coluna nova no ORM nao aparece sozinha numa tabela que ja existe.

O Job de migracao do sky-ai faz duas coisas:

  1. sincroniza os modelos SQLAlchemy — o que CRIA tabelas em falta, e
     mais nada. Nao acrescenta colunas a tabelas que ja existem;
  2. aplica os ficheiros `.sql` de `db/migrations/`.

Numa base nova o passo 1 constroi a tabela com todas as colunas do ORM,
e por isso local e CI passam sempre. Numa base que ja tem a tabela — ou
seja, producao — a coluna nova simplesmente nao aparece.

Foi o que aconteceu ao `semantic_cache`: o ORM declarava `locale`,
`cache_version` e `temporal_bucket` desde Junho, a base nao as tinha, e
cada gravacao falhava com a excepcao engolida. A cache esteve morta
meses, sem alarme nenhum, e toda a pergunta repetida pagou LLM.

Havia migracoes alembic para isto (006 e 007) — mas **o sky-ai nao corre
alembic**. Verificado em producao: a tabela `alembic_version_ai` nem
existe. Sao decorativas.

Este teste compara o ORM com os ficheiros `.sql` que correm de facto.
"""

import pathlib
import re
import sys

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

# As tabelas que ja existiam em producao antes de o ORM as mexer. Para
# estas, `create_all` nao chega — cada coluna nova precisa de SQL.
#
# Nao e a lista de todas as tabelas de proposito: uma tabela criada de
# raiz pelo `create_all` nasce completa, e exigir-lhe SQL seria ruido.
TABELAS_QUE_JA_EXISTIAM = ["semantic_cache"]


def _colunas_no_sql(tabela: str) -> set[str]:
    """Colunas que algum ficheiro .sql acrescenta a esta tabela."""
    achadas = set()
    padrao = re.compile(
        r"ALTER\s+TABLE\s+" + tabela + r"\s+ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)",
        re.IGNORECASE | re.DOTALL,
    )
    for f in (RAIZ / "db" / "migrations").glob("*.sql"):
        achadas.update(m.lower() for m in padrao.findall(f.read_text(encoding="utf-8")))
    return achadas


def _colunas_no_orm(tabela: str) -> set[str]:
    from db.models import Base

    for t in Base.metadata.sorted_tables:
        if t.name == tabela:
            return {c.name.lower() for c in t.columns}
    raise AssertionError(f"a tabela {tabela!r} nao existe no ORM")


@pytest.mark.parametrize("tabela", TABELAS_QUE_JA_EXISTIAM)
def test_toda_a_coluna_do_orm_tem_sql_que_a_crie(tabela):
    orm = _colunas_no_orm(tabela)
    sql = _colunas_no_sql(tabela)

    # As colunas do desenho original — as que estavam la antes de a
    # tabela existir em producao — nao precisam de SQL.
    ORIGINAIS = {
        "id",
        "connection_id",
        "space_id",
        "crew_id",
        "question",
        "embedding",
        "response_json",
        "created_at",
    }

    em_falta = orm - sql - ORIGINAIS
    assert not em_falta, (
        f"o ORM declara {sorted(em_falta)} em {tabela}, e nenhum ficheiro "
        f".sql as cria.\n"
        f"Numa base nova o create_all resolve — em producao, onde a tabela "
        f"ja existe, a coluna nunca aparece e a escrita falha em silencio.\n"
        f"Acrescenta um ficheiro em db/migrations/ com "
        f"`ALTER TABLE {tabela} ADD COLUMN IF NOT EXISTS ...`."
    )


def test_as_tres_colunas_da_cache_estao_cobertas():
    """As que estiveram em falta em producao. Explicito, para nao regredir."""
    sql = _colunas_no_sql("semantic_cache")

    for coluna in ("locale", "cache_version", "temporal_bucket"):
        assert coluna in sql, (
            f"{coluna} nao e criada por nenhum .sql — a cache volta a morrer "
            "em producao, e sem erro visivel"
        )


def test_as_linhas_antigas_sao_marcadas_como_mortas():
    """Sem isto, respostas guardadas sem lingua voltariam a ser servidas.

    Uma pergunta em portugues podia receber uma resposta em ingles
    guardada meses antes.
    """
    sqls = "\n".join(
        f.read_text(encoding="utf-8") for f in (RAIZ / "db" / "migrations").glob("*.sql")
    ).lower()

    assert "set cache_version = 0" in sqls, (
        "as linhas antigas nao sao marcadas como mortas — se a coluna for "
        "criada com o valor por omissao do ORM (1), o Postgres preenche-as "
        "todas e elas passam a parecer validas"
    )
