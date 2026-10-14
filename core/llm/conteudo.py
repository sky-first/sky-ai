# -*- coding: utf-8 -*-
"""O texto de uma resposta do modelo, venha ela como vier.

14/10/2026: com ``AI_PROVIDER=bedrock`` (``ChatBedrockConverse``) o
``.content`` de uma mensagem NÃO é sempre uma ``str``: quando a resposta traz
mais de um bloco — texto + ``tool_use``, ou o raciocínio do modelo
(``reasoning_content``) antes do texto — vem uma LISTA de blocos::

    [{"type": "reasoning_content", "reasoning_content": {...}},
     {"type": "text", "text": "invoices, customers"},
     {"type": "tool_use", "id": "…", "name": "…", "input": {...}}]

O orquestrador partiu logo na primeira pergunta do portão das fontes
(``'list' object has no attribute 'splitlines'``) e havia mais de trinta
sítios a ler ``.content`` como se fosse texto. Com o OpenAI (produção) o
problema não aparece porque lá o conteúdo é sempre ``str``.

Toda a leitura do texto de uma resposta do modelo passa por aqui:

- só contam os blocos ``text`` (e cadeias soltas dentro da lista);
- o raciocínio, as chamadas a ferramentas e as imagens ficam de fora — não
  são resposta, e o raciocínio pode dizer «isto NÃO é OUT_OF_SCOPE»;
- nunca levanta excepção: o pior caso é ``""``.
"""

from __future__ import annotations

from typing import Any

#: Tipos de bloco que são o texto da resposta. ``text`` é o que a Converse,
#: a Anthropic e o OpenAI (Responses) usam; ``output_text`` é o do OpenAI.
_TIPOS_DE_TEXTO = {"text", "output_text"}


def texto_do_conteudo(conteudo: Any) -> str:
    """Texto de um ``.content`` (``str`` ou lista de blocos)."""
    if conteudo is None:
        return ""
    if isinstance(conteudo, str):
        return conteudo
    if isinstance(conteudo, (list, tuple)):
        partes = []
        for bloco in conteudo:
            if isinstance(bloco, str):
                partes.append(bloco)
            elif isinstance(bloco, dict):
                if bloco.get("type") in _TIPOS_DE_TEXTO and isinstance(
                    bloco.get("text"), str
                ):
                    partes.append(bloco["text"])
            # outros objectos (imagens, etc.) não são texto
        return "\n".join(p for p in partes if p)
    return str(conteudo)


def texto_da_resposta(resposta: Any) -> str:
    """Texto de uma resposta do modelo (``AIMessage``, ``str``, dict ou ``None``).

    Substitui ``raw.content if hasattr(raw, "content") else str(raw)`` e as
    suas variantes.
    """
    if resposta is None:
        return ""
    if isinstance(resposta, str):
        return resposta
    if isinstance(resposta, dict):
        if "content" in resposta:
            return texto_do_conteudo(resposta.get("content"))
        return str(resposta)
    if hasattr(resposta, "content"):
        return texto_do_conteudo(getattr(resposta, "content", None))
    return str(resposta)
