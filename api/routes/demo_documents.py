"""Responder a perguntas sobre um ficheiro largado na demo pública.

Todos os outros caminhos do motor exigem um ``connection_id`` — uma
ligação configurada, com metadados indexados. Um ficheiro que um
visitante arrasta para a página não tem nada disso, e é por isso que
este endpoint existe.

Porque não bastava o cálculo local. A primeira versão da demo analisava
o ficheiro no browser, o que era rápido, grátis e privado — e sabia
somar e mais nada. Perguntas como *"qual é o nome da primeira pessoa"*
ou qualquer coisa sobre um contrato em PDF ficavam sem resposta, e a
Sky passava a parecer uma ferramenta de BI em vez de um produto que
lê o que lhe derem.

**Modelo de retenção, à maneira do iLovePDF:** o conteúdo chega, é
usado para responder, e não é escrito em lado nenhum — nem base de
dados, nem disco, nem registo. Vive o tempo do pedido. É por isso que
não há aqui nenhuma escrita: a promessa cumpre-se por não existir
código que a possa quebrar, e não por uma tarefa de limpeza que alguém
tem de lembrar-se de manter.

O que **é** registado é o tamanho e o tipo do que veio, para se poder
diagnosticar problemas sem nunca guardar conteúdo.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from core.llm.factory import create_llm_formatter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo", tags=["demo"])

# Tecto do que segue para o modelo.
#
# Não é uma preocupação de custo apenas — é de qualidade. Um contexto
# gigante dilui a pergunta e as respostas pioram. Uma amostra de 120
# linhas chega para responder a quase tudo o que se pergunta a uma
# tabela, e o modelo é instruído a dizer quando não chega.
MAX_ROWS = 120
MAX_TEXT_CHARS = 24_000


class DemoDocumentQuestion(BaseModel):
    question: str
    locale: str = "en"
    # Caminho tabular: cabeçalhos e uma amostra de linhas.
    columns: List[str] = Field(default_factory=list)
    rows: List[List[str]] = Field(default_factory=list)
    total_rows: Optional[int] = None
    # Caminho documental: texto já extraído (PDF, contrato, acta).
    text: Optional[str] = None
    filename: Optional[str] = None


class DemoDocumentAnswer(BaseModel):
    answer: str
    # Verdadeiro quando o modelo diz que a amostra não chega para
    # responder com confiança. O ecrã mostra-o em vez de apresentar um
    # palpite como facto.
    insufficient: bool = False


_SYSTEM = {
    "pt": (
        "És a Sky, uma analista de dados. Respondes a perguntas sobre o ficheiro "
        "que o utilizador acabou de partilhar.\n\n"
        "Regras, por ordem de importância:\n"
        "1. Responde SÓ com o que está nos dados fornecidos. Nunca inventes um "
        "número, um nome ou uma data.\n"
        "2. Se a amostra não chegar para responder com confiança, diz isso "
        "claramente e explica o que precisarias. É preferível admitir do que "
        "arriscar — um número errado sobre os dados de alguém custa a confiança "
        "toda.\n"
        "3. Vai direta ao ponto: a resposta na primeira frase, o contexto depois. "
        "No máximo três frases curtas.\n"
        "4. Quando deres um número, diz sobre quantos registos foi calculado.\n"
        "5. Responde em português de Portugal."
    ),
    "en": (
        "You are Sky, a data analyst. You answer questions about the file the "
        "user just shared.\n\n"
        "Rules, in order of importance:\n"
        "1. Answer ONLY from the data provided. Never invent a number, a name or "
        "a date.\n"
        "2. If the sample isn't enough to answer confidently, say so plainly and "
        "explain what you'd need. Admitting beats guessing — a wrong number about "
        "someone's own data costs all the trust.\n"
        "3. Lead with the answer, context after. Three short sentences at most.\n"
        "4. When you give a number, say how many records it came from."
    ),
}


def _tabular_context(payload: DemoDocumentQuestion) -> str:
    header = " | ".join(payload.columns)
    lines = [header, "-" * min(len(header), 120)]
    for row in payload.rows[:MAX_ROWS]:
        lines.append(" | ".join(str(c) for c in row))

    note = ""
    if payload.total_rows and payload.total_rows > len(payload.rows):
        # O modelo tem de saber que está a ver uma amostra, senão
        # responde "o total é X" sobre 120 linhas de 90 mil.
        note = (
            f"\n\n[Esta é uma amostra de {len(payload.rows)} linhas de um total "
            f"de {payload.total_rows}. Para totais e médias exactas sobre o "
            f"ficheiro inteiro, diz que precisas do ficheiro completo.]"
        )
    return "\n".join(lines) + note


@router.post("/answer-document", response_model=DemoDocumentAnswer)
async def answer_document(payload: DemoDocumentQuestion) -> DemoDocumentAnswer:
    """Uma resposta sobre o ficheiro. Nada é guardado."""
    locale = (payload.locale or "en").split("-")[0].lower()
    system = _SYSTEM.get(locale, _SYSTEM["en"])

    if payload.text:
        context = payload.text[:MAX_TEXT_CHARS]
        kind = "documento"
    elif payload.columns:
        context = _tabular_context(payload)
        kind = "tabela"
    else:
        return DemoDocumentAnswer(
            answer="", insufficient=True
        )

    # Só metadados no registo. O conteúdo do ficheiro de alguém não
    # entra num log que fica noventa dias no Loki.
    logger.info(
        "demo_answer_document kind=%s cols=%d rows=%d chars=%d",
        kind,
        len(payload.columns),
        len(payload.rows),
        len(context),
    )

    llm = create_llm_formatter(creativity=1)
    try:
        result = llm.invoke(
            [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": f"{context}\n\n---\n\n{payload.question}",
                },
            ]
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("demo_answer_document_failed: %s", exc)
        return DemoDocumentAnswer(answer="", insufficient=True)

    answer = getattr(result, "content", None) or str(result)
    answer = answer.strip()

    # Sinal grosseiro de que o modelo se escusou. Serve para o ecrã
    # apresentar a resposta como limitação e não como facto.
    low = answer.lower()
    insufficient = not answer or any(
        marker in low
        for marker in (
            "não consigo",
            "nao consigo",
            "não é possível",
            "amostra não",
            "i can't",
            "cannot answer",
            "not enough",
            "insufficient",
        )
    )

    return DemoDocumentAnswer(answer=answer, insufficient=insufficient)
