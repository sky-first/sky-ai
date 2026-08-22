"""A Sky classifica o que encontra: é um risco, uma oportunidade, ou nenhum.

**O problema.** Todos os achados nasciam iguais. O worker gravava
``type="insight"`` e ``severity="medium"`` cravados no código — nenhum agente
produziu alguma vez um risco ou uma oportunidade. Os filtros «Risco» e
«Oportunidade» existem nas duas interfaces e estão sempre a zero para achados
a sério; só os de demonstração, semeados à mão, têm variedade.

Podia-se filtrar, mas não havia por onde.

── Porque é a Sky a classificar, e não a pessoa ─────────────────────────────

A alternativa era pedir a quem cria o agente que escolhesse: «este agente
procura riscos». Previsível, e errado no fundo — um agente que vigia margens
encontra às vezes um risco e às vezes uma boa notícia, e forçá-lo a um rótulo
faz o filtro mentir. A classificação é do ACHADO, não do agente.

Fica a porta aberta para a correcção humana: quem vir um achado mal
classificado deve poder corrigi-lo, e essa correcção vale mais do que a
adivinhação inicial. É o passo seguinte, não este.

── O que isto NÃO faz ───────────────────────────────────────────────────────

Não inventa gravidade a partir do tom. Um texto alarmado sobre uma coisa
pequena continua a ser uma coisa pequena, e a gravidade sai do que os números
dizem — não de quantos pontos de exclamação a resposta tem.

E não classifica não-respostas. Uma resposta que diz «correu mal do nosso
lado» ou «essa pergunta não parece estar relacionada aos seus dados» não é um
achado de espécie nenhuma; devolve-se `insight`/`low` e quem chama que decida.
Perguntar ao modelo o que é aquilo só produziria uma etiqueta com ar de
verdade.
"""

import json as _json
import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from config.settings import settings
from core.llm.providers import LangChainChatOpenAIProvider, OllamaProvider
from core.logging_utils import log_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/findings", tags=["findings"])

#: Os três tipos, e as três gravidades. São os mesmos nomes que as duas
#: interfaces já mostram nos filtros — inventar aqui um quarto obrigaria a
#: mudar os dois clientes para o mostrar.
TIPOS = ("risk", "opportunity", "insight")
GRAVIDADES = ("high", "med", "low")

#: Uma resposta que contenha isto não é um achado — é o sistema a dizer que
#: não conseguiu. Classificá-la seria pôr uma etiqueta numa não-resposta.
NAO_E_ACHADO = (
    "correu mal do nosso lado",
    "something went wrong on our",
    "não parece estar relacionada aos seus dados",
    "does not seem to be related to your data",
    "não há como comparar",
    "not been informed",
    "não foram informados",
)

_PROMPT = """Classificas achados de análise de dados. Respondes SÓ com JSON.

Decide duas coisas sobre o achado:

"type":
  "risk"        — algo está pior, a piorar, ou fora do esperado de forma que
                  custa dinheiro, clientes ou tempo se ninguém agir.
  "opportunity" — algo está melhor do que o esperado, ou há aqui ganho por
                  tomar se alguém agir.
  "insight"     — descreve como as coisas estão. Nem alarme nem ganho.

"severity":
  "high" — pede acção esta semana. Grande em tamanho ou rápido a piorar.
  "med"  — vale a pena olhar, não é urgente.
  "low"  — de registo.

Regras:
- A gravidade sai do que os NÚMEROS dizem, não do tom do texto. Um texto
  alarmado sobre uma variação de 1% é "low".
- Sem números concretos no achado, a gravidade é no máximo "med": não se
  chama urgente ao que não se mediu.
- Na dúvida entre risco e achado, escolhe "insight". Um alarme falso ensina
  a ignorar alarmes.

Responde exactamente: {"type": "...", "severity": "..."}"""


def _modelo():
    """O modelo barato — isto é uma etiqueta, não uma análise.

    Respeita o `AI_PROVIDER` como o resto da casa: uma rota que instancia
    OpenAI à força faz a stack inteira em Ollama gastar tokens sem ninguém
    perceber porquê (foi o que aconteceu com os títulos dos widgets).
    """
    if settings.use_local_models:
        return OllamaProvider(
            model=settings.llm_model_formatter_local,
            base_url=settings.ollama_base_url,
            temperature=0,
            num_ctx=getattr(settings, "ollama_num_ctx_formatter", 4096),
        )
    return LangChainChatOpenAIProvider(
        model=settings.llm_model_formatter or "gpt-4o-mini",
        temperature=0,
        max_tokens=30,
    )


class PedidoDeClassificacao(BaseModel):
    title: str = Field(default="", description="Título do achado.")
    answer: str = Field(..., description="O texto do achado.")
    question: Optional[str] = Field(
        default=None, description="A pergunta do agente que o produziu."
    )


class Classificacao(BaseModel):
    type: str = Field(..., description="risk | opportunity | insight")
    severity: str = Field(..., description="high | med | low")
    #: Falso quando não se chegou a perguntar ao modelo — porque o texto não é
    #: um achado, ou porque a chamada falhou. Quem chama pode querer saber a
    #: diferença entre «é mesmo um insight» e «não deu para saber».
    classified: bool = Field(default=True)


def parece_um_achado(texto: str) -> bool:
    """Falso quando o texto é o sistema a dizer que não conseguiu.

    Estas respostas chegam ao worker como qualquer outra e eram gravadas como
    achados. Classificá-las põe uma etiqueta numa desculpa.
    """
    baixo = (texto or "").lower()
    return not any(m in baixo for m in NAO_E_ACHADO)


def _limpar(bruto: str) -> Optional[dict]:
    """O JSON que vier, mesmo embrulhado em ```json.

    Modelos pequenos embrulham. Rejeitar por causa disso trocava uma
    classificação boa por um `insight` de omissão.
    """
    t = (bruto or "").strip()
    if t.startswith("```"):
        t = t.split("```")[1] if "```" in t[3:] else t[3:]
        t = t.lstrip("json").strip()
    inicio, fim = t.find("{"), t.rfind("}")
    if inicio == -1 or fim == -1:
        return None
    try:
        return _json.loads(t[inicio : fim + 1])
    except Exception:  # noqa: BLE001
        return None


@router.post("/classify", response_model=Classificacao)
async def classificar(pedido: PedidoDeClassificacao) -> Classificacao:
    """Risco, oportunidade ou achado — e o quanto pesa.

    NUNCA rebenta. Um classificador que rebenta faz perder o achado que estava
    a classificar, e o achado vale mais do que a etiqueta. Em qualquer falha
    devolve `insight`/`med`, que é o que o worker gravava antes desta rota
    existir — o pior caso é ficar como estava.
    """
    de_omissao = Classificacao(type="insight", severity="med", classified=False)

    if not parece_um_achado(pedido.answer):
        log_event("classificar_achado_nao_e_achado", {"titulo": pedido.title[:80]})
        return Classificacao(type="insight", severity="low", classified=False)

    contexto = f"Pergunta: {pedido.question}\n\n" if pedido.question else ""
    contexto += f"Título: {pedido.title}\n\nAchado:\n{pedido.answer[:2000]}"

    try:
        resposta = _modelo().invoke(
            [
                {"role": "system", "content": _PROMPT},
                {"role": "user", "content": contexto},
            ]
        )
        bruto = getattr(resposta, "content", None) or str(resposta)
    except Exception as exc:  # noqa: BLE001
        logger.warning("classificar_achado falhou: %s", exc)
        log_event("classificar_achado_erro", {"error": str(exc)[:200]})
        return de_omissao

    dados = _limpar(bruto)
    if not dados:
        log_event("classificar_achado_sem_json", {"bruto": (bruto or "")[:120]})
        return de_omissao

    tipo = str(dados.get("type", "")).lower().strip()
    gravidade = str(dados.get("severity", "")).lower().strip()
    # Um valor fora da lista é um valor inventado. Cair no de omissão é melhor
    # do que gravar "critical" numa coluna que os filtros não conhecem.
    if tipo not in TIPOS or gravidade not in GRAVIDADES:
        log_event("classificar_achado_fora_da_lista", {"type": tipo, "severity": gravidade})
        return de_omissao

    log_event("classificar_achado", {"type": tipo, "severity": gravidade})
    return Classificacao(type=tipo, severity=gravidade)
