"""juntar as duas cabeças da cadeia de migrações

A cadeia bifurcava. Duas revisões partiam do mesmo ponto::

    agent_finding_viz_kind_20260515
        ├── 004_audit_security_columns          (cabeça)
        └── 005_fix_embedding_dims_and_cache
                └── 006_temporal_bucket_cache
                        └── 007_locale_cache_version  (cabeça)

Com duas cabeças, ``alembic upgrade head`` recusa-se a escolher e aborta
com *«Multiple head revisions are present»*. **Nenhuma das duas linhas
corria** — nem a antiga nem a nova.

O efeito, verificado em produção a 03/09/2026: a tabela
``alembic_version`` estava **vazia** — nunca nada foi aplicado — e o
``semantic_cache`` continuava sem as colunas ``locale``,
``cache_version`` e ``temporal_bucket`` que o ORM declara desde a 006/007.

Consequência prática: **a cache de respostas esteve morta o tempo todo.**
Cada gravação falhava com ``column "cache_version" does not exist``, e a
excepção era engolida. Toda a pergunta repetida pagava o custo completo
de LLM e de SQL, sem alarme nenhum. Via-se nos registos do ``sky-ai``::

    Semantic cache STORE failed — answers are not being cached:
    UndefinedColumnError: column "cache_version" of relation
    "semantic_cache" does not exist

Esta revisão não altera esquema nenhum. Só volta a dar **uma** cabeça à
cadeia, para que as duas linhas passem a ser aplicadas.

Revision ID: 008_juntar_cabecas
Revises: 004_audit_security_columns, 007_locale_cache_version
Create Date: 2026-09-03
"""

from __future__ import annotations

# revision identifiers, used by Alembic.
revision = "008_juntar_cabecas"
# As duas cabeças. É isto que faz desta uma revisão de junção: a partir
# daqui há um caminho único, e o `upgrade head` volta a saber para onde ir.
down_revision = ("004_audit_security_columns", "007_locale_cache_version")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Nada a fazer.

    Uma revisão de junção existe para reunir a cadeia, não para mexer na
    base. O trabalho está nas revisões que ela junta — e é precisamente
    esse trabalho que estava parado.
    """


def downgrade() -> None:
    """Nada a desfazer.

    Reverter uma junção volta a partir a cadeia em duas cabeças, que é o
    estado avariado. Se for mesmo preciso, desce-se cada linha pelo seu
    lado.
    """
