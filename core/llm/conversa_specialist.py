"""Responder a quem fala connosco, sem ir aos dados.

O Lucas, depois de experimentar o live talk:

    «Ao dizer *1 2 3* precisamos falar: *4 5 6, haha, quer seguir? Ou tem
    alguma coisa que quer saber da sua empresa?* Precisa ter esse certo
    nível de inteligência quando alguém pergunta coisas fora do contexto
    ou desconexas.»

    «Ele pode falar tipo *bom dia, como vai por aí?* ou *quantos graus
    fazem hoje em Lisboa*, ou coisas simples que poderíamos sim responder
    sem ir aos dados. Ter uma certa abertura para esse tipo de conversas
    eu acho muito bom.»

── O que estava a acontecer ─────────────────────────────────────────

**Tudo** ia direito ao motor de perguntas. O classificador de intenções
pontua a frase contra padrões — receita, métrica, equipa, dashboard — e
o que não pontua em nada cai no valor por omissão, que é `data`.

«Bom dia» pontua zero. Portanto «bom dia» virava uma tentativa de gerar
SQL, que falhava, e a pessoa recebia a fórmula de erro.

── O que se faz aqui ────────────────────────────────────────────────

Uma resposta de conversa, com o LLM e sem tocar em nenhuma base de
dados. Três regras, e a terceira é a que mais importa:

1. **responde na língua de quem falou** — a mesma que o resto da app;
2. **é curta** — uma ou duas frases. Isto é uma pausa na conversa, não
   um relatório;
3. **não inventa o que não sabe.** A temperatura em Lisboa hoje, a
   cotação de uma acção, quem ganhou ontem — são coisas que mudam e que
   este modelo não tem como saber. Diz que não sabe, e diz porquê. Uma
   resposta errada com ar de certa é pior do que um «não sei».

E acaba a abrir uma porta: uma coisa concreta que a Sky *pode* fazer com
os dados desta pessoa. É o que o Lucas pediu — não matar a iteração.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict

logger = logging.getLogger(__name__)


#: Quanto tempo o modelo tem para uma frase de conversa. Curto de
#: propósito: se isto demorar, a pessoa fica à espera de um «bom dia».
_LIMITE_SEGUNDOS = 12


_INSTRUCOES = """You are Sky, an assistant that answers questions about a company's own data.

The user just said something conversational — a greeting, small talk, a
thank-you, or a general question that has nothing to do with their data.

Reply in AT MOST two short sentences, in {lingua}.

Rules:
- Be warm and natural. This is a pause in the conversation, not a report.
- If they asked something you genuinely cannot know — today's weather, a
  live stock price, today's news, anything that changes by the hour —
  say plainly that you don't have that. Never guess. A confident wrong
  answer is worse than "I don't know".
- If it's general knowledge that does not change (what a word means, a
  simple calculation), just answer it.
- End by opening a door: name ONE concrete thing you could look up in
  THEIR data. Keep it short and specific.

Never mention SQL, tables, columns, schemas, or that you route questions.
"""


#: Cumprimentos curtos demais para um detector de linguas julgar.
#:
#: O detector desiste abaixo de 8 caracteres e devolve "en" — e por boa
#: razao: julgar "oi" contra 75 linguas e adivinhar. So que as frases que
#: chegam a este ficheiro sao, por definicao, curtas: "ola", "bom dia",
#: "hola", "gracias" — todas abaixo do corte.
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


def _lingua_do_cumprimento(pergunta: str) -> str | None:
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


def _lingua(state: Dict[str, Any], pergunta: str) -> str:
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
    «bom dia» tem 7, «ola» tem 3, «hola» tem 4. As frases que chegam a
    este ficheiro sao curtas por definicao — e sao exactamente as que o
    detector se recusa a julgar. Por isso os cumprimentos sao vistos
    primeiro, contra uma lista curta de palavras que pertencem a uma
    lingua so.
    """
    do_estado = state.get("detected_language") or state.get("locale")
    if do_estado:
        return str(do_estado).strip().lower().replace("_", "-").split("-")[0]

    curto = _lingua_do_cumprimento(pergunta)
    if curto:
        return curto

    try:
        from core.i18n.i18n import resolve_language

        return resolve_language(pergunta)
    except Exception:
        # Detectar mal e melhor do que rebentar; e o ingles e o que sobra.
        logger.exception("conversa: nao consegui detectar a lingua de %r", pergunta[:60])
        return "en"


def _nome_da_lingua(lang: str) -> str:
    return {"pt": "Portuguese (Portugal)", "es": "Spanish", "en": "English"}.get(
        (lang or "en")[:2], "English"
    )


def _reserva(lang: str) -> str:
    """A resposta quando o modelo nao responde.

    Escrita a mao, nas tres linguas. Um «bom dia» nao pode morrer numa
    fórmula de erro — foi exactamente o que o Lucas apanhou.
    """
    return {
        "pt": "Olá! Estou aqui. Quer que veja alguma coisa nos seus dados?",
        "es": "¡Hola! Aquí estoy. ¿Quiere que mire algo en sus datos?",
        "en": "Hello! I'm here. Want me to look something up in your data?",
    }.get((lang or "en")[:2], "Hello! I'm here. Want me to look something up in your data?")


def run_conversa_specialist(state: Dict[str, Any], llm: Any) -> Dict[str, Any]:
    """Responde de conversa, sem consultar dados.

    Devolve o estado com `answer` preenchido. Nao mexe em `sql` nem em
    `data` — nao houve consulta nenhuma, e fingir que houve confundia
    quem le os registos a seguir.
    """
    pergunta = (state.get("question") or "").strip()
    lang = _lingua(state, pergunta)

    try:
        resposta = llm.invoke(
            [
                {
                    "role": "system",
                    "content": _INSTRUCOES.format(lingua=_nome_da_lingua(lang)),
                },
                {"role": "user", "content": pergunta},
            ]
        )
        texto = (getattr(resposta, "content", None) or str(resposta)).strip()
    except Exception:
        # Nao se propaga: uma saudacao que rebenta e pior do que uma
        # saudacao generica. O erro fica nos registos.
        logger.exception("conversa: o modelo nao respondeu; uso a frase de reserva")
        texto = ""

    if not texto:
        texto = _reserva(lang)

    state["answer"] = texto
    # Sem consulta, sem dados. Deixa-lo explicito evita que o formatador
    # ou o ecra procurem uma tabela que nunca existiu.
    state["sql"] = None
    state["data"] = []
    return state
