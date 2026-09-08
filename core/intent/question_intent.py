"""
Multi-agent intent classifier.

Two-tier detection:
1. Fast regex patterns (zero LLM cost) for obvious intents
2. LLM-based classification for ambiguous cases

The intent determines which specialist node handles the question
in the LangGraph pipeline.
"""

from __future__ import annotations

import re
import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger("dataassistant")


class QuestionIntent(str, Enum):
    DATA = "data"  # SQL query against customer databases
    KNOWLEDGE = (
        "knowledge"  # Metrics + Glossary + Relationships catalog (post-refactor)
    )
    STRATEGY = "knowledge"  # Legacy alias — Strategy was folded into Knowledge
    SIGNALS = "signals"  # Market signals, events, anomalies, trends
    RELATIONSHIPS = "relationships"  # Cross-space/dept connections, cause-and-effect
    PEOPLE = "people"  # Teams, users, crew membership, activity
    WIDGETS = "widgets"  # Existing dashboards, past insights, AI history
    MIXED = "mixed"  # Needs multiple sources
    CATALOG = "catalog"  # "What tables do I have?"
    DASHBOARD = "dashboard"  # Dashboard generation
    # Conversa: cumprimentos, agradecimentos, e o que nao tem nada a ver
    # com os dados de ninguem.
    #
    # Nao existia, e por isso «bom dia» — que nao pontua em padrao nenhum
    # — caia no valor por omissao, que e `data`. Um cumprimento virava
    # uma tentativa de gerar SQL, falhava, e a pessoa recebia a formula
    # de erro. Ver `core/llm/conversa_specialist.py`.
    CONVERSA = "conversa"


# ── Fast regex patterns (zero cost) ────────────────────────────

# Knowledge intent — covers (a) the legacy strategy vocabulary that
# now lives under Metrics (OKR, goal, KPI), (b) the Knowledge layer
# proper (metric, definition, glossary, formula), and (c) intent verbs
# like "what does X mean" / "define X" that should always go through
# the curated catalog before falling back to general knowledge.
_KNOWLEDGE_PATTERNS = re.compile(
    r"\b("
    r"okr|okrs|objective|objectives|key.?result|key.?results|"
    r"pillar|pillars|initiative|initiatives|"
    r"goal|goals|"
    r"strategy|strategic|"
    r"on.?track|off.?track|"
    r"progress|milestone|milestones|"
    r"business.?plan|roadmap|vision|mission|"
    r"budget.?plan|forecast|assumption|assumptions|"
    r"cycle|quarterly|q[1-4]|"
    # Knowledge layer terms (post-refactor)
    r"metric|metrics|kpi|kpis|"
    r"glossary|glossaries|term|terms|definition|definitions|"
    # Narrow "what is/are/does" to knowledge-only contexts (not generic data questions)
    r"what.?(?:is|are|does)\s+(?:a\s+|an\s+|the\s+)?(?:definition|formula|kpi|okr|metric|term|glossary)|what.{0,40}means?\b|define|"
    r"formula|formulas"
    r")\b",
    re.IGNORECASE,
)

# Backwards-compat alias so any external code referencing the old name
# still works (and tests expecting STRATEGY enum can still find it).
_STRATEGY_PATTERNS = _KNOWLEDGE_PATTERNS

_SIGNALS_PATTERNS = re.compile(
    r"\b(" r"signal|signals|"
    # "events" alone is too broad — web_analytics.events is a data table.
    # Only match when preceded by qualifiers that imply intelligence signals.
    r"intelligence.?event|market.?event|business.?event|"
    r"anomaly|anomalies|"
    r"alert|alerts|notification|"
    r"spike|drop|surge|"
    r"competitor|regulatory|"
    r"external.?signal|internal.?event|"
    r"deviation|warning|"
    r"macro|geopolitic"
    r")\b",
    re.IGNORECASE,
)

_RELATIONSHIPS_PATTERNS = re.compile(
    r"\b(" r"relationship|relationships|"
    # "drives" alone is too broad (e.g. "which utm_source drives sessions").
    # Only match when followed by cross-entity language.
    r"depends.?on|correlates?|"
    r"cross.?space|across.?space|across.?department|"
    r"how.?does.+affect|"
    r"enterprise.?context|business.?context|"
    r"connected.?to|linked.?to|"
    r"between.+department|between.+space|between.+team"
    r")\b",
    re.IGNORECASE,
)

_PEOPLE_PATTERNS = re.compile(
    r"\b("
    r"team.?member|crew.?member|"
    r"which.?team|which.?crew|which.?space|"
    r"people|person|member|members|"
    r"asking|activity|"
    r"role|roles|permission|permissions|"
    r"organization.?structure|org.?chart"
    r")\b",
    re.IGNORECASE,
)

_WIDGETS_PATTERNS = re.compile(
    r"\b("
    r"dashboard|dashboards|widget|widgets|"
    r"chart|charts|kpi.?card|"
    r"what.?was.?asked|previous.?question|past.?question|"
    r"history|ai.?history|"
    r"already.?analyz|existing.?report|existing.?dashboard|"
    r"what.?do.?we.?have|what.?reports"
    r")\b",
    re.IGNORECASE,
)

_CATALOG_PATTERNS = re.compile(
    r"\b("
    r"what.?tables|which.?tables|list.?tables|show.?tables|"
    r"what.?data.?sources|which.?connections|"
    r"what.?schemas|describe.?schema"
    r")\b",
    re.IGNORECASE,
)

# ── Conversa ─────────────────────────────────────────────────────────
#
# Cumprimentos, despedidas, agradecimentos e o «como estás». Nas tres
# linguas que a app fala, porque quem escreve «bom dia» nao muda de
# lingua para ser percebido.
#
# ⚠️ Deliberadamente **curto**. Estes padroes correm ANTES de tudo o
# resto e ganham; um padrao largo de mais rouba perguntas de negocio
# legitimas e manda-as para uma resposta de conversa — que e um defeito
# muito pior do que o que se esta a corrigir.
#
# «Obrigado pelo relatorio de vendas» nao pode virar conversa. Por isso
# a regra nao e so o padrao: e o padrao **e** a frase ser curta. Ver
# `_parece_conversa`.
_CONVERSA_PATTERNS = re.compile(
    r"^\s*("
    # cumprimentos
    r"ol[aá]|oi|bom\s*dia|boa\s*tarde|boa\s*noite|"
    r"hello|hi|hey|good\s*(morning|afternoon|evening)|"
    r"hola|buenos\s*d[ií]as|buenas\s*(tardes|noches)|"
    # como estas
    r"tudo\s*(bem|bom)|como\s*(vai|est[aá]s?|vais)|"
    r"how\s*(are|is\s*it\s*going)|what'?s\s*up|"
    r"qu[eé]\s*tal|c[oó]mo\s*est[aá]s?|"
    # agradecimentos e despedidas
    r"obrigad[oa]|valeu|thanks?|thank\s*you|gracias|"
    r"adeus|at[eé]\s*(logo|j[aá])|bye|good\s*bye|hasta\s*luego|"
    # testes de microfone — o «1 2 3» do Lucas
    r"(um|dois|tr[eê]s|one|two|three|uno|dos|tres|\d)(\s*[,.]?\s*(um|dois|tr[eê]s|one|two|three|uno|dos|tres|\d))+"
    r")\b",
    re.IGNORECASE,
)

#: Acima disto, uma frase que comeca por «obrigado» ja nao e um
#: agradecimento — e um pedido com boas maneiras. Contado em palavras,
#: porque «obrigado» e «gracias» tem comprimentos diferentes.
_MAX_PALAVRAS_DE_CONVERSA = 8


def _parece_conversa(q: str) -> bool:
    """Um cumprimento, e nao um pedido educado.

    **Tres condicoes, as tres obrigatorias.** O padrao sozinho nao
    chegava: «Obrigado, agora mostra-me as vendas do trimestre» comeca
    por «obrigado», tem oito palavras, e passava — mandar isso para a
    conversa era trocar um defeito por outro pior.

    Por isso a terceira condicao, que e a que decide: a frase nao pode
    ter **nenhum** sinal de negocio. Se tem, e uma pergunta com boas
    maneiras, e vai para o motor como qualquer outra.
    """
    if not _CONVERSA_PATTERNS.match(q):
        return False
    if len(q.split()) > _MAX_PALAVRAS_DE_CONVERSA:
        return False

    # Zero sinais. Nao «poucos» — zero. Na duvida, a pergunta vai ao
    # motor: uma pergunta de negocio respondida com «ola!» e muito pior
    # do que um «ola» respondido com dados.
    for padrao in (
        _DATA_BOOST_PATTERNS,
        _STRATEGY_PATTERNS,
        _SIGNALS_PATTERNS,
        _RELATIONSHIPS_PATTERNS,
        _PEOPLE_PATTERNS,
        _WIDGETS_PATTERNS,
        _CATALOG_PATTERNS,
    ):
        if padrao.search(q):
            return False
    return True

_DATA_BOOST_PATTERNS = re.compile(
    r"\b("
    # ── Portugues e espanhol ──────────────────────────────────────
    #
    # Estes padroes eram **so em ingles**, num produto cuja interface
    # esta em portugues. «Show me total revenue» era reconhecida como
    # pergunta de dados; «Mostra-me a receita total» nao pontuava em
    # nada e caia no valor por omissao.
    #
    # Dava certo por acidente — o valor por omissao TAMBEM e `data` —
    # mas so por acidente: qualquer regra que dependa da pontuacao (a
    # da conversa, agora, e o desempate entre intencoes) via zero onde
    # devia ver um sinal forte.
    #
    # Descoberto a corrigir outra coisa: «obrigado, agora mostra-me as
    # vendas do trimestre» ia parar a conversa, porque «vendas» nao
    # existia aqui e «sales» existia.
    r"quant[oa]s?|quanto|"
    r"receita|faturacao|faturação|vendas|clientes?|encomendas?|pedidos?|"
    r"fatura|faturas|pagamentos?|"
    r"m[eé]dia|soma|total|totais|"
    r"m[eê]s.?passado|este.?m[eê]s|ontem|hoje|trimestre|"
    r"agrupad[oa]|por.?regi[aã]o|"
    r"crescimento|abandono|cancelamentos?|"
    r"ingresos|ventas|facturaci[oó]n|promedio|"
    r"mes.?pasado|este.?mes|ayer|hoy|trimestre|"
    r"crecimiento|abandono|cancelaciones|"
    # ── Ingles ────────────────────────────────────────────────────
    r"how.?many|how.?much|count|total|sum|average|"
    r"select|query|sql|"
    r"revenue|sales|invoice|payment|customers?|orders?|"
    r"last.?month|this.?month|yesterday|today|"
    r"group.?by|filter|where|"
    r"top.?\d|bottom.?\d|"
    r"trends?|trending|growth|churn|cancellations?|"
    # Web analytics & product usage vocabulary — always data queries
    r"sessions?|page.?path|page.?view|utm_source|utm_campaign|utm|"
    r"signup.?count|signups?|conversion|converted|"
    r"feature.?adoption|feature.?use|times.?used|seats.?used|seats.?paid|"
    r"health.?score|account.?health|at.?risk|risk.?level|logged.?in|last.?login|"
    r"subscri|cancelled|cancell"
    r")\b",
    re.IGNORECASE,
)


def classify_question_intent(
    question: str,
    has_data_sources: bool = True,
    llm=None,
) -> QuestionIntent:
    """
    Classify a user question into the appropriate specialist intent.

    Args:
        question: The user's natural language question
        has_data_sources: Whether the current context has SQL data sources
        llm: Optional LLM provider for ambiguous cases (unused in v1)

    Returns:
        QuestionIntent enum value
    """
    q = question.strip()
    if not q:
        return QuestionIntent.DATA

    # Conversa primeiro, e antes de pontuar seja o que for. Um «bom dia»
    # nao pontua em padrao nenhum e caia no valor por omissao — que e
    # `data`. Virava uma tentativa de gerar SQL, falhava, e a pessoa
    # recebia a formula de erro.
    if _parece_conversa(q):
        return QuestionIntent.CONVERSA

    # Score each intent
    strategy_score = len(_STRATEGY_PATTERNS.findall(q))
    signals_score = len(_SIGNALS_PATTERNS.findall(q))
    relationships_score = len(_RELATIONSHIPS_PATTERNS.findall(q))
    people_score = len(_PEOPLE_PATTERNS.findall(q))
    widgets_score = len(_WIDGETS_PATTERNS.findall(q))
    catalog_score = len(_CATALOG_PATTERNS.findall(q))
    data_score = len(_DATA_BOOST_PATTERNS.findall(q))

    # Catalog is high-priority if detected
    if catalog_score > 0 and data_score == 0:
        return QuestionIntent.CATALOG

    # DATA_OVERRIDE: strong data signal with NO competing non-data signals → DATA
    # Using non_data_max == 0 (not <= 1) because even a single non-data signal
    # alongside data terms indicates a genuinely mixed question (e.g. "revenue vs OKR
    # targets" has both data=revenue and strategy=OKR).
    non_data_max = max(
        [
            strategy_score,
            signals_score,
            relationships_score,
            people_score,
            widgets_score,
        ],
        default=0,
    )
    if data_score >= 2 and non_data_max == 0:
        return QuestionIntent.DATA

    # Check for mixed intent (multiple non-data intents scored, or strategy+data combo)
    non_data_scores = [
        s
        for s in [
            strategy_score,
            signals_score,
            relationships_score,
            people_score,
            widgets_score,
        ]
        if s > 0
    ]
    # Mixed if: 2+ non-data layers, OR strategy+data (need targets AND actuals), OR relationships+data
    if len(non_data_scores) >= 2:
        return QuestionIntent.MIXED
    if strategy_score > 0 and data_score > 0:
        return QuestionIntent.MIXED
    if relationships_score > 0 and data_score > 0:
        return QuestionIntent.MIXED
    if signals_score > 0 and data_score > 0:
        return QuestionIntent.MIXED

    # Single dominant intent — boost non-data intents (they're more specific)
    scores = {
        QuestionIntent.STRATEGY: strategy_score * 2,
        QuestionIntent.SIGNALS: signals_score * 2,
        QuestionIntent.RELATIONSHIPS: relationships_score * 2,
        QuestionIntent.PEOPLE: people_score * 2,
        QuestionIntent.WIDGETS: widgets_score * 2,
        QuestionIntent.DATA: data_score,
    }

    best_intent = max(scores, key=lambda k: scores[k])
    best_score = scores[best_intent]

    if best_score == 0:
        return QuestionIntent.DATA if has_data_sources else QuestionIntent.RELATIONSHIPS

    # If a non-data intent won but data also scored, it might be mixed
    if (
        best_intent != QuestionIntent.DATA
        and data_score > 0
        and best_score <= data_score
    ):
        return QuestionIntent.MIXED

    return best_intent
