-- Ressuscitar a cache de respostas.
--
-- O ORM declara `locale`, `cache_version` e `temporal_bucket` no
-- `semantic_cache` desde Junho. A base de produção não as tinha. Cada
-- gravação falhava, e a excepção era engolida:
--
--     Semantic cache STORE failed — answers are not being cached:
--     UndefinedColumnError: column "cache_version" of relation
--     "semantic_cache" does not exist
--
-- A cache esteve 100% morta. Toda a pergunta repetida pagou o custo
-- completo de LLM e de SQL, sem alarme nenhum.
--
-- ── Porque é que isto não estava já feito ────────────────────────────
--
-- Estava — em `alembic/versions/006` e `007`. Mas **o sky-ai não corre
-- alembic**. O Job de migração sincroniza os modelos (o que só CRIA
-- tabelas em falta, nunca acrescenta colunas às que já existem) e aplica
-- os ficheiros desta pasta. Verificado a 03/09/2026: a tabela
-- `alembic_version_ai` nem sequer existe, enquanto a `alembic_version_be`
-- do backend tem valor. As revisões alembic deste serviço são
-- decorativas.
--
-- ── A armadilha do preenchimento retroactivo ─────────────────────────
--
-- O ORM declara `cache_version` com `server_default = 1`. Se a coluna
-- fosse criada COM esse valor por omissão, o Postgres preenchia todas as
-- linhas antigas com 1 — e as respostas anteriores, gravadas sem língua,
-- passavam a parecer válidas. Uma pergunta em português podia receber
-- uma resposta em inglês guardada meses antes.
--
-- Por isso as colunas entram SEM valor por omissão (linhas antigas ficam
-- a NULL) e são depois marcadas explicitamente como mortas com a versão
-- 0. A procura filtra pela versão 2, portanto as linhas 0 são inertes.
-- As novas são escritas com língua e versão explícitas.
--
-- Seguro a correr várias vezes: tudo guardado por IF NOT EXISTS, e o
-- UPDATE só toca em linhas a NULL.

ALTER TABLE semantic_cache
    ADD COLUMN IF NOT EXISTS temporal_bucket TEXT NULL;

ALTER TABLE semantic_cache
    ADD COLUMN IF NOT EXISTS locale VARCHAR(10) NULL;

ALTER TABLE semantic_cache
    ADD COLUMN IF NOT EXISTS cache_version INTEGER NULL;

-- Marcar as antigas como mortas. Explicitamente, e não por omissão.
UPDATE semantic_cache SET cache_version = 0 WHERE cache_version IS NULL;

CREATE INDEX IF NOT EXISTS idx_semantic_cache_temporal_bucket
    ON semantic_cache(temporal_bucket);

CREATE INDEX IF NOT EXISTS idx_semantic_cache_locale_version
    ON semantic_cache(locale, cache_version);
