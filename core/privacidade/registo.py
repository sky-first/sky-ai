"""Os logs não levam valores do cliente nem credenciais.

O stdout do pod vai para fora (CloudWatch). Até 13/10/2026 vários eventos
levavam valores reais: ``specialist_question_literals`` escrevia até 500
caracteres de valores das colunas; ``answer_preview`` levava o início da
resposta (com números do cliente); ``dsn_preview``/``conninfo_preview``
levavam os primeiros caracteres de ``postgresql://user:password@host``.

``limpar_payload`` é aplicado por ``core.logging_utils.log_event`` a TODOS os
eventos — uma regra num sítio só, em vez de corrigir chamada a chamada (cinco
sítios copiados já falharam uma vez neste repositório). Regras:

* chaves de **segredos** (DSN, URL de base, palavra-passe…) → ``<redacted>``;
* chaves de **dados** (respostas, amostras, linhas, valores) → só o tamanho:
  ``<redacted:N chars>`` / ``<redacted:N items>``. Números e booleanos
  passam (``"rows": 12`` é uma contagem, não um dado);
* chaves de **SQL** → o SQL fica (é gerado pela plataforma e é o que se usa
  para depurar), mas os literais de texto ``'…'`` passam a ``'?'``: o
  ``WHERE nome = 'Joana Silva'`` da correcção de literais não chega ao log;
* qualquer texto com ``esquema://utilizador:palavra@`` fica sem a palavra.
"""

from __future__ import annotations

import re
from typing import Any, Dict

#: Nunca vão para o log, nem truncadas.
CHAVES_SECRETAS = frozenset(
    {
        "dsn",
        "dsn_preview",
        "conninfo",
        "conninfo_preview",
        "database_url",
        "db_url",
        "sync_db_url",
        "connection_string",
        "password",
        "secret",
        "secret_key",
        "api_key",
        "token",
    }
)

#: Conteúdo vindo dos dados do cliente (ou da resposta, que os cita).
CHAVES_DE_DADOS = frozenset(
    {
        "answer",
        "answer_preview",
        "block",
        "literals",
        "data",
        "data_preview",
        "data_sample",
        "sample",
        "sample_rows",
        "sample_values",
        "values",
        "rows",
        "first_row",
        "result",
        "result_preview",
        "output",
        "output_preview",
        "response_preview",
        "final_msg_preview",
    }
)

#: SQL: fica, mas sem literais de texto.
CHAVES_DE_SQL = frozenset(
    {
        "sql",
        "sql_preview",
        "sql_executed",
        "sql_generated",
        "final_sql",
        "query_preview",
        "partiql_preview",
    }
)

_LITERAL_DE_TEXTO = re.compile(r"'(?:[^']|'')*'")
# Âncora no "://" e comprimentos limitados: sem isto o motor tentava o
# esquema a partir de cada letra do texto (ReDoS polinomial, CodeQL).
_CREDENCIAL_EM_URL = re.compile(
    r"(?<![A-Za-z0-9+.\-])(?P<esq>[A-Za-z][A-Za-z0-9+.\-]{0,30}://[^:/@\s]{0,256})"
    r":[^@\s]{0,1024}@"
)


def sem_literais(sql: str) -> str:
    """``WHERE nome = 'Joana'`` → ``WHERE nome = '?'``."""
    return _LITERAL_DE_TEXTO.sub("'?'", sql)


def sem_credenciais(texto: str) -> str:
    """``postgresql://u:segredo@h`` → ``postgresql://u:***@h``."""
    return _CREDENCIAL_EM_URL.sub(r"\g<esq>:***@", texto)


def _tamanho(valor: Any) -> str:
    if isinstance(valor, str):
        return f"<redacted:{len(valor)} chars>"
    try:
        return f"<redacted:{len(valor)} items>"
    except TypeError:
        return "<redacted>"


def _limpar_valor(chave: str, valor: Any) -> Any:
    k = chave.lower()
    if k in CHAVES_SECRETAS:
        return "<redacted>" if valor else valor
    if valor is None or isinstance(valor, (bool, int, float)):
        return valor
    if k in CHAVES_DE_DADOS:
        return _tamanho(valor)
    if k in CHAVES_DE_SQL and isinstance(valor, str):
        return sem_credenciais(sem_literais(valor))
    if isinstance(valor, str):
        return sem_credenciais(valor)
    if isinstance(valor, dict):
        return limpar_payload(valor)
    if isinstance(valor, (list, tuple)):
        return [
            (
                limpar_payload(v)
                if isinstance(v, dict)
                else (sem_credenciais(v) if isinstance(v, str) else v)
            )
            for v in valor
        ]
    return valor


def limpar_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """O payload de um evento, sem valores do cliente nem credenciais."""
    return {k: _limpar_valor(str(k), v) for k, v in payload.items()}
