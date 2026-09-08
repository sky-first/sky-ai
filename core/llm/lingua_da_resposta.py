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

import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

#: As línguas em que a Sky sabe responder.
#:
#: **Acrescentar uma língua faz-se aqui e no `core/i18n/i18n.py`.** Se as duas
#: listas divergirem, uma delas passa a mentir — e a que mente é sempre a que
#: alguém se esqueceu de actualizar.
NOME_DA_LINGUA = {
    "en": "English",
    # «Portuguese» e nao «Portuguese (Portugal)» mandava o modelo escrever
    # o portugues que ele conhece melhor, que e o do Brasil — «você», «time»,
    # «celular». O `conversa_specialist` ja tinha a sua propria copia com o
    # «(Portugal)» corrigido; ter duas era garantir que uma delas mentia.
    "pt": "Portuguese (Portugal)",
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


#: Cumprimentos curtos demais para um detector de linguas julgar.
#:
#: O detector desiste abaixo de 8 caracteres e devolve "en" — e por boa
#: razao: julgar "oi" contra 75 linguas e adivinhar. So que as frases de
#: conversa sao, por definicao, curtas: "ola", "bom dia", "hola",
#: "gracias" — todas abaixo do corte.
#:
#: So entram aqui palavras que pertencem a UMA lingua. "ola" e portugues,
#: "hola" e espanhol; nenhuma das duas e ambigua. Palavras que existem em
#: mais do que uma ficam de fora e vao para o detector.
_CUMPRIMENTOS_POR_LINGUA = {
    "pt": ("bom dia", "boa tarde", "boa noite", "ola", "olá", "oi", "obrigado",
           "obrigada", "adeus", "ate logo", "até logo", "tudo bem", "como vai"),
    "es": ("hola", "buenos dias", "buenos días", "buenas tardes", "buenas noches",
           "gracias", "que tal", "qué tal", "adios", "adiós", "hasta luego"),
    "en": ("hello", "hi", "hey", "good morning", "good afternoon", "good evening",
           "thanks", "thank you", "bye", "goodbye", "how are you"),
}

_SEM_ACENTOS = str.maketrans("áàâãäéèêëíìîïóòôõöúùûüçñ", "aaaaaeeeeiiiiooooouuuucn")


def lingua_do_cumprimento(pergunta: str) -> str | None:
    """A lingua de um cumprimento curto, ou None se nao for um."""
    limpo = re.sub(r"[^\w\s]", " ", pergunta.lower().translate(_SEM_ACENTOS))
    limpo = " ".join(limpo.split())
    if not limpo:
        return None

    for lang, frases in _CUMPRIMENTOS_POR_LINGUA.items():
        for frase in frases:
            alvo = frase.translate(_SEM_ACENTOS)
            if limpo == alvo or limpo.startswith(alvo + " "):
                return lang
    return None


def lingua_de_quem_fala(state: Dict[str, Any], pergunta: str) -> str:
    """A lingua da resposta, com a propria frase como ultimo recurso.

    ⚠️ **Apanhado em producao, minutos depois de publicar isto.** Fiz a
    pergunta «Bom dia! Como vai por ai?» e recebi *«Good morning! I'm
    doing well»*. Em portugues limpo, resposta em ingles.

    A primeira razao: o estado nao trazia `detected_language` nem
    `locale`, e o valor por omissao era `en`. Nos caminhos de dados a
    lingua e resolvida mais acima no grafo; este no e o primeiro a
    responder e nao passa por la.

    A segunda so apareceu quando a correccao chumbou na integracao — e e
    a mais interessante. Localmente o teste passava, no servidor falhava,
    **com o mesmo codigo**: aqui o `lingua` nao esta instalado e usa-se o
    detector de reserva; la esta, e o detector a serio devolvia `en` para
    a mesma frase portuguesa.

    Nao e um defeito dele. O `detect_language` e o porteiro: pontua contra
    75 linguas e, abaixo de 0,50 de confianca, diz `en` de proposito, para
    nao barrar ninguem por engano. Escolher a lingua da resposta e o
    trabalho do `resolve_language` — que so conhece EN/PT/ES e por isso
    decide onde o outro se cala.

    E fica na mesma um buraco: **ambos desistem abaixo de 8 caracteres.**
    «bom dia» tem 7, «ola» tem 3, «hola» tem 4. As frases de conversa sao
    curtas por definicao — e sao exactamente as que o detector se recusa a
    julgar. Por isso os cumprimentos sao vistos primeiro, contra uma lista
    curta de palavras que pertencem a uma lingua so.

    ── Porque vive aqui, e nao no no que a usa ──────────────────────────

    O `intent_classifier` encaminha para SEIS nos que nunca passam pelo
    orquestrador — e o orquestrador e o unico sitio que escreve
    `detected_language` no estado. Todos os seis tem o mesmo buraco, e ja
    tropecamos uma vez em ter a mesma regra copiada por cinco ficheiros.
    """
    do_estado = state.get("detected_language") or state.get("locale")
    if do_estado:
        return str(do_estado).strip().lower().replace("_", "-").split("-")[0]

    curto = lingua_do_cumprimento(pergunta)
    if curto:
        return curto

    try:
        from core.i18n.i18n import resolve_language

        return resolve_language(pergunta)
    except Exception:
        # Detectar mal e melhor do que rebentar; e o ingles e o que sobra.
        logger.exception("nao consegui detectar a lingua de %r", pergunta[:60])
        return "en"
