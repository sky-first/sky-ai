"""O que segue para o Langfuse não leva linhas do cliente.

O agente de scan (``core/agents/full_context_agent.py``) usa a ferramenta
``query_table``, cujo resultado são LINHAS do cliente (até ``MAX_SQL_ROWS``).
Com ``LANGFUSE_ENABLED=true`` o callback enviava esse resultado — e todas as
mensagens seguintes, que o repetem no histórico — para o Langfuse Cloud.

Regra: a ferramenta embrulha as linhas entre ``INICIO`` e ``FIM``. O modelo vê
tudo (precisa); a máscara dada ao Langfuse troca cada bloco embrulhado por
``LINHAS_OMITIDAS``, onde quer que apareça (output da ferramenta, prompt do
passo seguinte, metadados). Se o SDK instalado não aceitar ``mask``, o
Langfuse NÃO liga — falha fechado, nunca aberto.
"""

from __future__ import annotations

import re
from typing import Any

INICIO = "<<<linhas_do_cliente>>>"
FIM = "<<</linhas_do_cliente>>>"
LINHAS_OMITIDAS = "[linhas do cliente omitidas]"

_BLOCO = re.compile(re.escape(INICIO) + r".*?(?:" + re.escape(FIM) + r"|$)", re.S)


def embrulhar_linhas(texto: str) -> str:
    """Marca ``texto`` (as linhas) para a máscara o reconhecer."""
    return f"{INICIO}\n{texto}\n{FIM}"


def mascarar(data: Any, **_kwargs: Any) -> Any:
    """A função ``mask`` do Langfuse: tira os blocos de linhas, recursivamente.

    Um bloco sem ``FIM`` (cortado a meio por um truncamento) também sai, até ao
    fim do texto — mais vale perder contexto do que mandar meia tabela.
    """
    if isinstance(data, str):
        return _BLOCO.sub(LINHAS_OMITIDAS, data) if INICIO in data else data
    if isinstance(data, dict):
        return {k: mascarar(v) for k, v in data.items()}
    if isinstance(data, list):
        return [mascarar(v) for v in data]
    if isinstance(data, tuple):
        return tuple(mascarar(v) for v in data)
    # Mensagens do LangChain (AIMessage, ToolMessage…): o conteúdo é texto.
    conteudo = getattr(data, "content", None)
    if isinstance(conteudo, (str, list)):
        try:
            return data.model_copy(update={"content": mascarar(conteudo)})
        except Exception:  # noqa: BLE001
            return mascarar(conteudo)
    return data
