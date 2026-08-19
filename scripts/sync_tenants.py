"""Cria as tabelas do sky-ai em **todas** as bases de clientes.

Porque existe
-------------
O hook de migração do sky-ai faz ``Base.metadata.create_all`` — mas só contra a
``DATABASE_URL``, que é a base da **plataforma**. Nunca percorreu as bases dos
clientes.

No Modelo B cada cliente tem base própria, criada pelas migrações do sky-be. As
tabelas que são do sky-ai — ``embeddings``, ``semantic_cache``,
``table_metadata``, ``knowledge_file_chunks`` — nunca lá chegam. E a migração
``001_initial_schema`` do sky-ai é um *no-op* deliberado ("schema already
exists in databases that ran create_all"), portanto o alembic também não as
cria: assume que já existem, o que só é verdade na base antiga da plataforma.

Consequência: **toda a base de cliente nova nasce sem as tabelas da IA.** Isso
apareceu já três vezes, sempre com outra cara:

  - ``relation "embeddings" does not exist`` ao apagar uma ligação de dados,
    que era um 500 para qualquer cliente (corrigido no sky-be a 19/08);
  - a cache semântica do ``tenant_gbtsolutions``, que alguém teve de arranjar
    com DDL escrito à mão a 22/06;
  - o ``table_metadata`` em falta, que dá "No metadata found — execute table
    discovery first" a quem acabou de ligar uma fonte.

Cada uma foi tratada como incidente próprio. São a mesma coisa.

Isto é o par do ``scripts/migrate_tenants.py`` do sky-be, e segue-o de perto de
propósito: quem conhecer um conhece o outro.

Falha alto
----------
Se um cliente falhar, o script sai com erro e o hook trava o deploy. Não se
serve código cujo esquema não existe em todo o lado — um deploy adiado vê-se,
um cliente esquecido só se vê quando alguém se queixa.

Uso::

    python scripts/sync_tenants.py             # todos os clientes activos
    python scripts/sync_tenants.py --dry-run   # só diz o que faria
    python scripts/sync_tenants.py --slug x    # um só
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote_plus, unquote, urlparse

# Corre por caminho (`python scripts/sync_tenants.py`), e nesse modo o Python
# põe `scripts/` no sys.path — não a raiz. Sem isto, `import db.models` falha
# com ModuleNotFoundError. Aconteceu com o par deste script no sky-be, em
# produção, e só se viu quando o Job já estava a correr.
sys.path.insert(0, str(Path(__file__).parent.parent))


def _url_do_cliente(row) -> str:
    """Monta a URL asyncpg de um cliente a partir do segredo dele."""
    import boto3  # type: ignore[import-untyped]

    host = row["db_host"]
    port = row.get("db_port") or 5432
    arn = row["db_credentials_secret_arn"]

    blob = json.loads(
        boto3.client("secretsmanager").get_secret_value(SecretId=arn)["SecretString"]
    )
    if "username" in blob and "password" in blob:
        user, pw = blob["username"], blob["password"]
    else:
        parsed = urlparse(blob["url"])
        user, pw = unquote(parsed.username or ""), unquote(parsed.password or "")
    return (
        f"postgresql+asyncpg://{quote_plus(user)}:{quote_plus(pw)}"
        f"@{host}:{port}/{row['db_name']}"
    )


async def _clientes(slug: str | None) -> list[tuple[str, str]]:
    """(slug, url) de cada cliente activo com base dedicada."""
    import asyncpg

    plataforma_url = os.environ["DATABASE_URL"]
    pura = plataforma_url.replace("postgresql+asyncpg://", "postgresql://")
    nome_da_plataforma = pura.rsplit("/", 1)[-1].split("?")[0]

    ligacao = await asyncpg.connect(pura)
    try:
        linhas = await ligacao.fetch(
            """
            SELECT slug, db_host, db_port, db_name, db_credentials_secret_arn
            FROM tenant_registry
            WHERE is_active IS TRUE
            """
        )
    finally:
        await ligacao.close()

    saida: list[tuple[str, str]] = []
    for row in linhas:
        r = dict(row)
        if slug and r["slug"] != slug:
            continue
        if not r["db_host"] or not r["db_name"]:
            print(f"  {r['slug']}: sem base dedicada, ignorado")
            continue
        # O `sky` aponta para a base da plataforma: é a semente reservada do
        # registo, não um cliente. Já foi tratada pelo passo anterior do hook.
        if r["db_name"] == nome_da_plataforma:
            print(f"  {r['slug']}: é a base da plataforma, já sincronizada")
            continue
        saida.append((r["slug"], _url_do_cliente(r)))
    return saida


#: As tabelas que este script pode criar. Lista **explícita** de propósito:
#: `create_all` criaria as catorze do `db/models.py`, e sete delas pertencem ao
#: sky-be (`users`, `spaces`, `crews`, `data_connections`, `space_connections`,
#: `knowledge_files`, `knowledge_file_chunks`). Se por alguma razão faltassem
#: numa base de cliente, criá-las aqui gravava a **versão do sky-ai** do
#: esquema por cima do que o sky-be espera — e um desencontro de esquema entre
#: os dois serviços é bem pior do que a tabela em falta que se queria resolver.
#:
#: `planets` fica de fora por outro motivo: é o nome antigo de `pages`, que o
#: sky-be renomeou em `a3f2c1d0e9b8_rename_planets_to_pages`. O modelo do
#: sky-ai ficou para trás. Criá-la fabricava uma tabela órfã que ninguém lê.
TABELAS_DA_IA = (
    "embeddings",
    "semantic_cache",
    "table_metadata",
    "chat_history",
    "pipeline_jobs",
    "user_permissions",
)


async def _sincronizar(slug: str, url: str, a_serio: bool) -> list[str]:
    """Cria o que falta nessa base. Devolve as tabelas que criou."""
    import asyncpg
    from sqlalchemy.ext.asyncio import create_async_engine

    from db.models import Base

    pura = url.replace("postgresql+asyncpg://", "postgresql://")

    # `create_all` sabe o que já existe (`checkfirst` está ligado por omissão),
    # por isso isto é seguro em bases que já têm tudo.
    motor = create_async_engine(url, pool_pre_ping=True)
    try:
        ligacao = await asyncpg.connect(pura)
        try:
            # pgvector primeiro: sem a extensão, a coluna `vector` do
            # `embeddings` não se cria e o create_all rebenta a meio.
            await ligacao.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            antes = {
                r["tablename"]
                for r in await ligacao.fetch(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                )
            }
        finally:
            await ligacao.close()

        em_falta = sorted(set(TABELAS_DA_IA) - antes)
        if not em_falta:
            print(f"  {slug}: já tem tudo")
            return []
        if not a_serio:
            print(f"  {slug}: criaria {em_falta}")
            return em_falta

        # Só as que faltam e só as que são nossas — `tables=` restringe o
        # `create_all` em vez de o deixar percorrer o metadata inteiro.
        objectos = [Base.metadata.tables[t] for t in em_falta]
        async with motor.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: Base.metadata.create_all(
                    sync_conn, tables=objectos, checkfirst=True
                )
            )
        print(f"  {slug}: criadas {len(em_falta)} tabelas: {', '.join(em_falta)}")
        return em_falta
    finally:
        await motor.dispose()


async def principal() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--slug")
    args = parser.parse_args()

    clientes = await _clientes(args.slug)
    if not clientes:
        print("Nenhum cliente com base dedicada. Nada a fazer.")
        return 0

    print(f"Clientes a sincronizar: {[s for s, _ in clientes]}")
    falharam: list[str] = []
    for slug, url in clientes:
        try:
            await _sincronizar(slug, url, a_serio=not args.dry_run)
        except Exception as e:  # noqa: BLE001 — queremos o slug junto ao erro
            print(f"  {slug}: FALHOU — {type(e).__name__}: {e}")
            falharam.append(slug)

    if falharam:
        print(f"\nFalharam: {falharam}. O deploy trava aqui de propósito.")
        return 1
    print(f"\n{len(clientes)} clientes com as tabelas da IA em dia.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(principal()))
