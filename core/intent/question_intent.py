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
    DATA = "data"                   # SQL query against customer databases
    KNOWLEDGE = "knowledge"         # Metrics + Glossary + Relationships catalog (post-refactor)
    STRATEGY = "knowledge"          # Legacy alias — Strategy was folded into Knowledge
    SIGNALS = "signals"             # Market signals, events, anomalies, trends
    RELATIONSHIPS = "relationships" # Cross-space/dept connections, cause-and-effect
    PEOPLE = "people"               # Teams, users, crew membership, activity
    WIDGETS = "widgets"             # Existing dashboards, past insights, AI history
    MIXED = "mixed"                 # Needs multiple sources
    CATALOG = "catalog"             # "What tables do I have?"
    DASHBOARD = "dashboard"         # Dashboard generation


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
    r"\b("
    r"signal|signals|"
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
    r"\b("
    r"relationship|relationships|"
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

_DATA_BOOST_PATTERNS = re.compile(
    r"\b("
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
        [strategy_score, signals_score, relationships_score, people_score, widgets_score],
        default=0,
    )
    if data_score >= 2 and non_data_max == 0:
        return QuestionIntent.DATA

    # Check for mixed intent (multiple non-data intents scored, or strategy+data combo)
    non_data_scores = [
        s for s in [strategy_score, signals_score, relationships_score, people_score, widgets_score]
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
    if best_intent != QuestionIntent.DATA and data_score > 0 and best_score <= data_score:
        return QuestionIntent.MIXED

    return best_intent
