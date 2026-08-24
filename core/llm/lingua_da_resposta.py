"""Em que língua a Sky responde, e como se chama essa língua no prompt.

**Porque isto é um módulo e não duas linhas repetidas.**

A decisão estava escrita à mão em quatro sítios::

    _lang = detected_language if detected_language in ("en", "pt") else "en"
    _lang_name = "Portuguese" if _lang == "pt" else "English"

Quatro cópias da mesma regra é a garantia de que acrescentar uma língua se
faz em três delas. E é exactamente o que estava prestes a acontecer: pôr
espanhol na app sem o pôr aqui dá **interface em espanhol e respostas em
inglês** — que é pior do que não ter espanhol, porque parece que funciona
até se ler a resposta.

── O nome vai em inglês, de propósito ───────────────────────────────────────

O prompt diz «Answer ONLY in Spanish», não «Responde SÓ em espanhol». Todo o
resto do prompt está em inglês, e misturar línguas dentro de um prompt faz
modelos pequenos responderem na língua das INSTRUÇÕES em vez da língua
pedida. Já aconteceu aqui.
"""

from __future__ import annotations

from typing import Optional

#: As línguas em que a Sky sabe responder.
#:
#: **Acrescentar uma língua faz-se aqui e no `core/i18n/i18n.py`.** Se as duas
#: listas divergirem, uma delas passa a mentir — e a que mente é sempre a que
#: alguém se esqueceu de actualizar.
NOME_DA_LINGUA = {
    "en": "English",
    "pt": "Portuguese",
    "es": "Spanish",
}

LINGUA_DE_OMISSAO = "en"


def lingua_da_resposta(detectada: Optional[str]) -> str:
    """O código de duas letras em que se responde.

    Uma língua que não sabemos falar cai no inglês — responder em inglês a
    quem escreveu em alemão é honesto; tentar alemão com um prompt que não o
    prepara é que não.
    """
    codigo = (detectada or "")[:2].lower()
    return codigo if codigo in NOME_DA_LINGUA else LINGUA_DE_OMISSAO


def nome_da_lingua(detectada: Optional[str]) -> str:
    """Como essa língua se chama DENTRO do prompt. Sempre em inglês."""
    return NOME_DA_LINGUA[lingua_da_resposta(detectada)]
