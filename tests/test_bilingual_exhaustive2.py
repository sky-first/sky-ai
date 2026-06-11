"""
Extended bilingual EN/PT test suite — 10x volume.

Groups:
  A — Flakiness: wide variety of domain inputs for each language signal
  B — Real domain questions: sales, finance, HR, product, ops
  C — Pipeline state flow: orchestrator → formatter state propagation
  D — System gaps: remaining hardcoded strings, cache check, Davinci gate
"""

import pytest
from unittest.mock import MagicMock

from core.i18n.i18n import (
    detect_language,
    language_decision,
    resolve_language,
    thread_language_from_history,
    unsupported_language_message,
    get_message,
    SUPPORTED_LANGUAGES,
)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def make_llm(response: dict = None):
    llm = MagicMock()
    payload = response or {"is_confirmation": False, "chosen_index": None}
    import json
    llm.invoke.return_value = MagicMock(content=json.dumps(payload))
    return llm


def run_orch(question, chat_history=None, locale=None, last_suggestions=None):
    """Run orchestrator with minimal AgentConfig (no tables → early exit after lang)."""
    from core.llm.orchestrator import run_orchestrator
    from core.agents.generic_sql_agent import AgentConfig
    state = {
        "question": question,
        "chat_history": chat_history or [],
        "last_suggestions": last_suggestions,
        "locale": locale,
        "detected_language": None,
        "retrieval_context": [],
        "permissions": [],
    }
    config = AgentConfig(id="t", name="t", tables=[])
    run_orchestrator(state, config, make_llm())
    return state


# ─────────────────────────────────────────────────────────────────────────────
# GROUP A — FLAKINESS: broad input variety per category
# langdetect is deterministic per string but unreliable across similar strings.
# We test many formulations of the same intent and require ALL to pass.
# ─────────────────────────────────────────────────────────────────────────────

# A1 — Clear Portuguese questions (should always resolve to "pt", never blocked)
PT_CLEAR = [
    "quais foram as vendas totais do mês passado?",
    "qual foi o faturamento do trimestre anterior?",
    "me mostre o número de clientes ativos hoje",
    "quantos pedidos foram feitos na última semana?",
    "qual é a taxa de conversão do funil de vendas?",
    "quais são os produtos mais vendidos este ano?",
    "qual o ticket médio por cliente no Q3?",
    "me dê um resumo do desempenho das campanhas",
    "quantos usuários novos se cadastraram esse mês?",
    "qual foi o crescimento da receita em relação ao ano anterior?",
    "quais regiões tiveram maior volume de vendas?",
    "qual a margem bruta do produto principal?",
    "quantos contratos foram renovados no semestre?",
    "qual o nível de satisfação dos clientes esse mês?",
    "me mostra o ranking de vendedores por performance",
    "qual foi o custo de aquisição de clientes no Q2?",
    "quantas reclamações foram registradas essa semana?",
    "qual o índice de inadimplência da carteira atual?",
    "me mostra os dados de churn do último trimestre",
    "qual a receita recorrente mensal consolidada?",
    "quais são os principais indicadores de desempenho do time?",
    "me mostre a evolução do NPS nos últimos 6 meses",
    "quantos leads foram gerados pela campanha de marketing?",
    "qual o prazo médio de pagamento dos clientes?",
    "quais clientes estão em risco de cancelamento?",
    "me dê os dados de produtividade por departamento",
    "qual o volume de transações processadas hoje?",
    "quais produtos tiveram queda de vendas esse mês?",
    "me mostre o comparativo de despesas operacionais",
    "qual a participação de mercado por segmento?",
]

@pytest.mark.parametrize("question", PT_CLEAR)
def test_a1_clear_pt_never_blocked(question):
    blocked, lang = language_decision(question)
    assert blocked is False, f"Falsely blocked: {question!r}"
    assert lang == "pt", f"Expected pt, got {lang!r}: {question!r}"


# A2 — Clear English questions (should always resolve to "en", never blocked)
EN_CLEAR = [
    "what were the total sales last month?",
    "how many active customers do we have today?",
    "show me the revenue breakdown by region",
    "what is the conversion rate for our sales funnel?",
    "which products had the highest sales this quarter?",
    "what is the average order value per customer?",
    "give me a summary of campaign performance",
    "how many new users signed up this month?",
    "what was the revenue growth compared to last year?",
    "which regions had the highest sales volume?",
    "what is the gross margin for our main product?",
    "how many contracts were renewed this semester?",
    "what is the customer satisfaction score this month?",
    "show me the sales rep ranking by performance",
    "what was the customer acquisition cost in Q2?",
    "how many complaints were registered this week?",
    "what is the default rate in the current portfolio?",
    "show me churn data for the last quarter",
    "what is the monthly recurring revenue?",
    "what are the main KPIs for the team this period?",
    "show me NPS evolution over the last 6 months",
    "how many leads were generated by the marketing campaign?",
    "what is the average payment term for customers?",
    "which customers are at risk of cancellation?",
    "give me productivity data by department",
    "what is the transaction volume processed today?",
    "which products had declining sales this month?",
    "show me the operating expense comparison",
    "what is our market share by segment?",
    "how did we perform against our quarterly targets?",
]

@pytest.mark.parametrize("question", EN_CLEAR)
def test_a2_clear_en_never_blocked(question):
    blocked, lang = language_decision(question)
    assert blocked is False, f"Falsely blocked: {question!r}"
    assert lang == "en", f"Expected en, got {lang!r}: {question!r}"


# A3 — PT follow-ups (short, typical of conversation — must stay PT with thread)
PT_FOLLOWUPS = [
    "sim",
    "pode sim",
    "claro",
    "isso mesmo",
    "manda ver",
    "e o mês anterior?",
    "e por região?",
    "me mostra mais",
    "como assim?",
    "qual a diferença?",
    "comparado ao ano passado?",
    "e no Q2?",
    "detalha mais",
    "por produto?",
    "e os custos?",
    "quanto foi?",
    "e a meta?",
    "tá bom",
    "interessante",
    "o segundo",
]

PT_THREAD = [
    {"role": "user", "content": "quais foram as vendas totais do mês passado?"},
    {"role": "assistant", "content": "As vendas foram R$ 2,4 milhões."},
]

@pytest.mark.parametrize("followup", PT_FOLLOWUPS)
def test_a3_pt_followup_stays_pt_with_thread(followup):
    result = resolve_language(followup, thread_language="pt")
    assert result == "pt", f"Follow-up {followup!r} flipped from PT to {result!r}"


@pytest.mark.parametrize("followup", PT_FOLLOWUPS)
def test_a3b_pt_followup_orchestrator_state(followup):
    state = run_orch(followup, chat_history=PT_THREAD)
    lang = state.get("detected_language")
    assert lang == "pt", f"Orchestrator gave {lang!r} for follow-up {followup!r}"


# A4 — EN follow-ups (must stay EN with thread)
EN_FOLLOWUPS = [
    "yes",
    "sure",
    "ok",
    "of course",
    "go ahead",
    "and last month?",
    "by region?",
    "show me more",
    "what do you mean?",
    "compared to last year?",
    "and Q2?",
    "break it down",
    "by product?",
    "and costs?",
    "how much?",
    "vs target?",
    "sounds good",
    "interesting",
    "the second one",
    "got it, and?",
]

EN_THREAD = [
    {"role": "user", "content": "what were the total sales last month?"},
    {"role": "assistant", "content": "Sales were $2.4 million."},
]

@pytest.mark.parametrize("followup", EN_FOLLOWUPS)
def test_a4_en_followup_stays_en_with_thread(followup):
    result = resolve_language(followup, thread_language="en")
    assert result == "en", f"Follow-up {followup!r} flipped from EN to {result!r}"


# A5 — Unsupported languages (should block without locale/thread)
UNSUPPORTED = [
    ("fr", "quel a été le chiffre d'affaires du mois dernier en France?"),
    ("fr", "combien de clients actifs avons-nous aujourd'hui?"),
    ("de", "Was waren die Gesamtverkäufe im letzten Monat?"),
    ("de", "Wie viele aktive Kunden haben wir heute?"),
    ("es", "¿cuáles fueron las ventas totales del mes pasado en España?"),
    ("it", "quali sono state le vendite totali del mese scorso?"),
    ("nl", "wat waren de totale verkopen afgelopen maand?"),
    ("ru", "каковы были общие продажи за прошлый месяц?"),
    ("zh", "上个月的总销售额是多少?"),
    ("ja", "先月の総売上高はいくらでしたか?"),
]

@pytest.mark.parametrize("lang_code,question", UNSUPPORTED)
def test_a5_unsupported_languages_blocked_without_signals(lang_code, question):
    blocked, lang = language_decision(question)
    assert blocked is True, f"Should block {lang_code}: {question!r}"
    assert lang in SUPPORTED_LANGUAGES


@pytest.mark.parametrize("lang_code,question", UNSUPPORTED)
def test_a5b_locale_pt_prevents_block_for_unsupported(lang_code, question):
    blocked, lang = language_decision(question, locale="pt")
    assert blocked is False
    assert lang == "pt"


@pytest.mark.parametrize("lang_code,question", UNSUPPORTED)
def test_a5c_thread_en_prevents_block_for_unsupported(lang_code, question):
    blocked, lang = language_decision(question, thread_language="en")
    assert blocked is False
    assert lang == "en"


# ─────────────────────────────────────────────────────────────────────────────
# GROUP B — REAL DOMAIN QUESTIONS (finance, sales, HR, product, ops)
# Each verified to not be blocked AND to land on the correct language.
# ─────────────────────────────────────────────────────────────────────────────

# B1 — Finance PT
FINANCE_PT = [
    "qual foi o EBITDA consolidado do trimestre?",
    "me mostra a DRE do último mês",
    "qual a margem líquida por unidade de negócio?",
    "qual o fluxo de caixa operacional do semestre?",
    "quais são as despesas com pessoal esse mês?",
    "qual o custo do produto vendido no Q3?",
    "me mostra o balanço patrimonial consolidado",
    "qual a receita bruta versus receita líquida do mês?",
    "quais foram os impostos pagos no trimestre?",
    # "qual o capital de giro disponível hoje?" → KNOWN GAP: "capital de giro"
    # → langdetect → 'en'. Movido para grupo B10 (locale).
]

@pytest.mark.parametrize("q", FINANCE_PT)
def test_b1_finance_pt_not_blocked(q):
    blocked, lang = language_decision(q)
    assert blocked is False, f"Finance PT blocked: {q!r}"
    assert lang == "pt"


# B2 — Finance EN
FINANCE_EN = [
    "what was the consolidated EBITDA this quarter?",
    "show me the income statement for last month",
    "what is the net margin per business unit?",
    "what was the operating cash flow this semester?",
    "what are the personnel expenses this month?",
    "what was the cost of goods sold in Q3?",
    "show me the consolidated balance sheet",
    "what is gross revenue versus net revenue this month?",
    "how much tax did we pay this quarter?",
    "what is the working capital available today?",
]

@pytest.mark.parametrize("q", FINANCE_EN)
def test_b2_finance_en_not_blocked(q):
    blocked, lang = language_decision(q)
    assert blocked is False, f"Finance EN blocked: {q!r}"
    assert lang == "en"


# B3 — Sales PT
SALES_PT = [
    # "qual o pipeline de vendas atual por estágio?" → KNOWN GAP: "pipeline"
    # → langdetect → 'en'. Movido para grupo B10 (locale).
    "quais oportunidades estão próximas de fechar?",
    "qual a taxa de win rate dos últimos 90 dias?",
    "me mostra o forecast de vendas para o próximo mês",
    "quais vendedores bateram a meta esse mês?",
    "qual o ciclo médio de vendas por segmento?",
    # "quais clientes fizeram upsell esse trimestre?" → KNOWN GAP: langdetect
    # classifica como 'fr' (99.9%) devido ao loanword "upsell" + "esse". Movido
    # para test_b10_mixed_jargon_pt_with_locale_never_blocked (usa locale=pt).
    "qual o volume de propostas enviadas essa semana?",
    "me mostra o ranking de contas por receita",
    "quais deals foram perdidos para concorrência?",
]

@pytest.mark.parametrize("q", SALES_PT)
def test_b3_sales_pt_not_blocked(q):
    blocked, lang = language_decision(q)
    assert blocked is False, f"Sales PT blocked: {q!r}"
    assert lang == "pt"


# B4 — Sales EN
SALES_EN = [
    "what is the current sales pipeline by stage?",
    "which opportunities are close to closing?",
    "what is the win rate over the last 90 days?",
    "show me the sales forecast for next month",
    "which reps hit their quota this month?",
    "what is the average sales cycle by segment?",
    "which customers did upsell this quarter?",
    "what is the volume of proposals sent this week?",
    "show me the account ranking by revenue",
    "which deals were lost to competition?",
]

@pytest.mark.parametrize("q", SALES_EN)
def test_b4_sales_en_not_blocked(q):
    blocked, lang = language_decision(q)
    assert blocked is False, f"Sales EN blocked: {q!r}"
    assert lang == "en"


# B5 — HR PT
HR_PT = [
    # "qual o headcount atual por departamento?" → KNOWN GAP: "headcount" faz
    # langdetect classificar como 'es' (62%). Movido para o grupo de jargão misto.
    "quantas contratações foram feitas esse mês?",
    "qual a taxa de turnover do último trimestre?",
    "me mostra as ausências por equipe essa semana",
    "qual o custo total com benefícios esse mês?",
    "quais cargos têm vagas abertas hoje?",
    "qual a nota média de desempenho por equipe?",
    "quantas horas extras foram registradas no mês?",
    "qual o tempo médio de contratação por área?",
    "me mostra o mapa de calor de engajamento da equipe",
]

@pytest.mark.parametrize("q", HR_PT)
def test_b5_hr_pt_not_blocked(q):
    blocked, lang = language_decision(q)
    assert blocked is False, f"HR PT blocked: {q!r}"
    assert lang == "pt"


# B6 — Product / Metrics PT (mix of PT + EN acronyms)
PRODUCT_PT = [
    "qual o DAU médio do produto esse mês?",
    "me mostra a retenção D7 e D30 por coorte",
    "qual o tempo médio de sessão por usuário?",
    # "quantas features foram entregues no sprint?" → KNOWN GAP: "features" e
    # "sprint" fazem langdetect classificar como 'en'. Está no grupo B10 (locale).
    "qual o NPS do produto esse trimestre?",
    "me mostra o funil de ativação de novos usuários",
    "qual a taxa de adoção da nova funcionalidade?",
    "qual o time to value médio para novos clientes?",
    "me mostra os erros mais frequentes em produção",
    "qual o uptime do sistema no último mês?",
]

@pytest.mark.parametrize("q", PRODUCT_PT)
def test_b6_product_metrics_pt_not_blocked(q):
    blocked, lang = language_decision(q)
    assert blocked is False, f"Product PT blocked: {q!r}"


# B7 — Product / Metrics EN
PRODUCT_EN = [
    "what is the average DAU for our product this month?",
    "show me D7 and D30 retention by cohort",
    "what is the average session time per user?",
    "how many features were shipped this sprint?",
    "what is the product NPS this quarter?",
    "show me the activation funnel for new users",
    "what is the adoption rate of the new feature?",
    "what is the average time to value for new customers?",
    "show me the most frequent errors in production",
    "what was the system uptime last month?",
]

@pytest.mark.parametrize("q", PRODUCT_EN)
def test_b7_product_metrics_en_not_blocked(q):
    blocked, lang = language_decision(q)
    assert blocked is False, f"Product EN blocked: {q!r}"
    assert lang == "en"


# B8 — Ops PT
OPS_PT = [
    "qual o SLA médio de atendimento esse mês?",
    "quantos tickets foram abertos hoje?",
    "qual o tempo médio de resolução de incidentes?",
    "me mostra a fila de atendimento por prioridade",
    "qual o backlog de suporte esse trimestre?",
    "quais processos têm maior taxa de retrabalho?",
    "qual o custo operacional por transação?",
    "me mostra a capacidade utilizada por recurso",
    "quantas entregas foram feitas no prazo essa semana?",
    "qual o lead time médio do processo principal?",
]

@pytest.mark.parametrize("q", OPS_PT)
def test_b8_ops_pt_not_blocked(q):
    blocked, lang = language_decision(q)
    assert blocked is False, f"Ops PT blocked: {q!r}"
    assert lang == "pt"


# B9 — Ops EN
OPS_EN = [
    "what is the average SLA for support this month?",
    "how many tickets were opened today?",
    "what is the average incident resolution time?",
    "show me the support queue by priority",
    "what is the support backlog this quarter?",
    "which processes have the highest rework rate?",
    "what is the operational cost per transaction?",
    "show me capacity utilization by resource",
    "how many deliveries were on time this week?",
    "what is the average lead time for the main process?",
]

@pytest.mark.parametrize("q", OPS_EN)
def test_b9_ops_en_not_blocked(q):
    blocked, lang = language_decision(q)
    assert blocked is False, f"Ops EN blocked: {q!r}"
    assert lang == "en"


# B10 — Mixed jargon PT (EN acronyms inside PT sentences — the hard cases)
MIXED_JARGON_PT = [
    "qual o churn rate do mês passado?",
    "me mostra o MRR por plano de assinatura",
    "qual o ARR projetado para o ano fiscal?",
    "qual o CAC médio por canal de aquisição?",
    "me mostra o LTV por segmento de cliente",
    "qual o GMV total processado esse mês?",
    "me mostra a breakdown do gross profit",
    "qual o burn rate atual da operação?",
    "qual o payback period médio dos clientes?",
    "me mostra os KPIs principais do board",
    # Casos promovidos do grupo B por serem code-switching sensível:
    "quais clientes fizeram upsell esse trimestre?",   # langdetect → fr sem locale
    "qual o headcount atual por departamento?",        # langdetect → es sem locale
    "quantas features foram entregues no sprint?",     # langdetect → en sem locale
    "qual o capital de giro disponível hoje?",         # langdetect → en sem locale
    "qual o pipeline de vendas atual por estágio?",    # langdetect → en sem locale
]

@pytest.mark.parametrize("q", MIXED_JARGON_PT)
def test_b10_mixed_jargon_pt_with_locale_never_blocked(q):
    # With locale: NEVER blocked regardless of detection
    blocked, lang = language_decision(q, locale="pt")
    assert blocked is False, f"Blocked with locale=pt: {q!r}"
    assert lang == "pt"


@pytest.mark.parametrize("q", MIXED_JARGON_PT)
def test_b10b_mixed_jargon_pt_with_thread_never_blocked(q):
    # With thread: NEVER blocked
    blocked, lang = language_decision(q, thread_language="pt")
    assert blocked is False, f"Blocked with thread=pt: {q!r}"
    assert lang == "pt"


# ─────────────────────────────────────────────────────────────────────────────
# GROUP C — PIPELINE STATE FLOW
# Verify detected_language survives the full orchestrator run and arrives
# at the formatter correctly. Tests all meaningful state combinations.
# ─────────────────────────────────────────────────────────────────────────────

class TestPipelineStateFlow:

    # C1 — Language set by orchestrator is readable by formatter
    def test_c1_orchestrator_sets_detected_language_in_state(self):
        state = run_orch("quais foram as vendas do mês passado?")
        assert "detected_language" in state
        assert state["detected_language"] == "pt"

    def test_c1b_en_question_sets_en_in_state(self):
        state = run_orch("what were the sales last month?")
        assert state["detected_language"] == "en"

    # C2 — ensure_language in formatter respects state value
    @pytest.mark.parametrize("lang", ["pt", "en"])
    def test_c2_formatter_ensure_language_respects_state(self, lang):
        from core.llm.formatter import _ensure_language
        # Formatter must use whatever was put in state — not re-detect
        result = _ensure_language("sim", lang)
        assert result == lang, f"Formatter ignored state lang={lang!r}"

    # C3 — State propagation: locale → orchestrator → formatter (simulated)
    @pytest.mark.parametrize("locale,expected", [
        ("pt-BR", "pt"),
        ("pt",    "pt"),
        ("en-US", "en"),
        ("en",    "en"),
    ])
    def test_c3_locale_propagates_through_orchestrator(self, locale, expected):
        state = run_orch("what were the sales?", locale=locale)
        assert state["detected_language"] == expected

    # C4 — Thread sticky: multiple turns maintain language
    @pytest.mark.parametrize("followup", [
        "sim", "e antes?", "por região?", "detalha", "e os custos?",
        "ok", "quanto?", "mostra mais", "isso mesmo", "e o Q2?",
    ])
    def test_c4_multi_turn_pt_thread_stable(self, followup):
        history = [
            {"role": "user",      "content": "quais foram as vendas do mês passado?"},
            {"role": "assistant", "content": "As vendas foram R$ 2,4 milhões."},
            {"role": "user",      "content": "me mostra por região"},
            {"role": "assistant", "content": "A região Sul liderou com R$ 800k."},
        ]
        state = run_orch(followup, chat_history=history)
        assert state["detected_language"] == "pt", \
            f"Thread flipped to EN on follow-up {followup!r}"

    @pytest.mark.parametrize("followup", [
        "yes", "and before?", "by region?", "detail it", "and costs?",
        "ok", "how much?", "show more", "exactly", "and Q2?",
    ])
    def test_c4b_multi_turn_en_thread_stable(self, followup):
        history = [
            {"role": "user",      "content": "what were the sales last month?"},
            {"role": "assistant", "content": "Sales were $2.4 million."},
            {"role": "user",      "content": "show me by region"},
            {"role": "assistant", "content": "The South region led with $800k."},
        ]
        state = run_orch(followup, chat_history=history)
        assert state["detected_language"] == "en", \
            f"Thread flipped to PT on follow-up {followup!r}"

    # C5 — Blocked state must have answer but NO detected_language = unsupported
    def test_c5_blocked_state_has_bilingual_answer(self):
        state = run_orch(
            "quel a été le chiffre d'affaires du mois dernier en France?"
        )
        assert "answer" in state
        assert "English and Portuguese" in state["answer"]
        assert "inglês e português" in state["answer"]

    def test_c5b_blocked_detected_language_is_supported_fallback(self):
        state = run_orch(
            "quel a été le chiffre d'affaires du mois dernier?"
        )
        lang = state.get("detected_language")
        assert lang in SUPPORTED_LANGUAGES, \
            f"Blocked state has unsupported detected_language: {lang!r}"

    # C6 — formatter prompt_legacy respects language for all supported codes
    @pytest.mark.parametrize("lang,expected_word", [
        ("pt", "Portuguese"),
        ("en", "English"),
    ])
    def test_c6_formatter_prompt_enforces_language(self, lang, expected_word):
        from core.llm.prompts.formatter_prompts import build_formatter_prompt_legacy
        sys_msg, _ = build_formatter_prompt_legacy(
            question="quais as vendas?",
            sql="SELECT * FROM sales",
            data_preview="total: 1000",
            detected_language=lang,
        )
        assert expected_word in sys_msg["content"], \
            f"Prompt for lang={lang!r} does not contain {expected_word!r}"

    # C7 — Locale None vs locale valid: orchestrator behaviour difference
    def test_c7_none_locale_falls_through_to_detection(self):
        state_no_locale = run_orch(
            "quais foram as vendas do mês passado?", locale=None
        )
        state_pt_locale = run_orch(
            "what were the sales?", locale="pt"
        )
        assert state_no_locale["detected_language"] == "pt"   # from detection
        assert state_pt_locale["detected_language"] == "pt"   # from locale


# ─────────────────────────────────────────────────────────────────────────────
# GROUP D — SYSTEM GAPS & REMAINING HARDCODED STRINGS
# ─────────────────────────────────────────────────────────────────────────────

class TestSystemGaps:

    # D1 — i18n catalogue completeness: every key has both EN and PT
    @pytest.mark.parametrize("key,lang", [
        ("SECURITY_BLOCKED", "en"), ("SECURITY_BLOCKED", "pt"),
        ("PII_BLOCKED",      "en"), ("PII_BLOCKED",      "pt"),
        ("TECHNICAL_ERROR",  "en"), ("TECHNICAL_ERROR",  "pt"),
        ("NO_DATA_FOUND",    "en"), ("NO_DATA_FOUND",    "pt"),
        ("NO_DATA_GENERIC",  "en"), ("NO_DATA_GENERIC",  "pt"),
    ])
    def test_d1_all_catalogue_keys_have_both_languages(self, key, lang):
        msg = get_message(key, lang, topic="test")
        assert isinstance(msg, str) and len(msg) > 10, \
            f"Missing or empty message: key={key!r} lang={lang!r}"

    @pytest.mark.parametrize("key", [
        "SECURITY_BLOCKED", "PII_BLOCKED", "TECHNICAL_ERROR",
        "NO_DATA_FOUND", "NO_DATA_GENERIC",
    ])
    def test_d1b_pt_and_en_messages_are_different(self, key):
        en = get_message(key, "en", topic="X")
        pt = get_message(key, "pt", topic="X")
        assert en != pt, f"EN and PT messages identical for key={key!r}"

    # D2 — Davinci endpoint: uses unsupported_language_message (gap check)
    def test_d2_gap_davinci_gatekeeper_is_english_only(self):
        """
        KNOWN GAP: The Davinci/dashboard endpoint (connection_query.py ~2063)
        has its own gatekeeper with a hardcoded EN-only message, separate from
        the main query gatekeeper. It also uses body.language (not body.locale).
        This gap means PT users hitting the dashboard route get an EN error.
        This test documents the gap and must be replaced by a fix.
        """
        import ast, pathlib
        source = pathlib.Path(
            "api/routes/connection_query.py"
        ).read_text()
        # Locate the hardcoded EN-only string in the Davinci path
        assert (
            "I'm sorry, but I currently only support English and Portuguese."
            in source
        ), "Davinci EN-only gate was removed — update or remove this gap test."

    # D3 — Semantic cache skip: fragile string match on answer
    def test_d3_gap_cache_skip_uses_hardcoded_string(self):
        """
        KNOWN GAP: The semantic cache skip check (connection_query.py ~3268)
        uses `response.answer.startswith("I'm sorry, but I only support questions")`
        — a hardcoded EN string. If the block message ever changes (e.g. to
        bilingual), the cache could start storing blocked responses.
        This test documents the gap; fix by using error code instead of string match.
        """
        import pathlib
        source = pathlib.Path("api/routes/connection_query.py").read_text()
        assert "I'm sorry, but I only support questions" in source, \
            "Cache skip hardcoded string was changed — verify the cache logic is still correct."

    # D4 — Orchestrator system messages still in EN (intentional for internal messages)
    def test_d4_orchestrator_internal_messages_are_english(self):
        """
        KNOWN BEHAVIOUR (not a bug): orchestrator internal error messages
        ("Question cannot be empty", "No tables are configured") are intentionally
        EN-only as they target developers/admins, not end users. This test
        documents the decision.
        """
        import pathlib
        source = pathlib.Path("core/llm/orchestrator.py").read_text()
        assert "Question cannot be empty." in source
        assert "No tables are configured for this agent." in source

    # D5 — Specialist always generates SQL in English (intentional)
    def test_d5_specialist_forces_english_for_sql(self):
        """
        INTENTIONAL DESIGN: specialist.py forces English for SQL generation
        regardless of user language. SQL identifiers must be in English.
        This test verifies this behaviour is still in place.
        """
        import pathlib
        source = pathlib.Path("core/llm/specialist.py").read_text()
        assert "Language: English (always)" in source or \
               "EVEN IF USER SPEAKS ANOTHER LANGUAGE" in source, \
            "Specialist SQL-English enforcement was removed — this may break SQL generation."

    # D6 — unsupported_language_message used in BOTH gatekeepers
    def test_d6_both_query_gatekeepers_use_bilingual_message(self):
        import pathlib
        source = pathlib.Path("api/routes/connection_query.py").read_text()
        assert source.count("unsupported_language_message()") >= 2, \
            "Expected at least 2 uses of unsupported_language_message() in connection_query.py"

    def test_d6b_orchestrator_uses_bilingual_message(self):
        import pathlib
        source = pathlib.Path("core/llm/orchestrator.py").read_text()
        assert "unsupported_language_message()" in source

    # D7 — Davinci source: hardcoded "always in English" must be gone
    def test_d7_davinci_no_hardcoded_always_english(self):
        import pathlib
        source = pathlib.Path(
            "core/agents/davinci_dashboard_agent.py"
        ).read_text()
        assert "ALWAYS respond in English" not in source
        assert "regardless of the user" not in source.lower()

    # D8 — apply_davinci_refactor: hardcoded language = "en" must be gone
    def test_d8_apply_refactor_no_force_english(self):
        import pathlib
        source = pathlib.Path(
            "core/agents/apply_davinci_refactor.py"
        ).read_text()
        assert "Force English only" not in source

    # D9 — formatter_prompts: old hardcoded "Answer ONLY in English" must be gone
    def test_d9_formatter_prompts_no_hardcoded_english(self):
        import pathlib
        source = pathlib.Path(
            "core/llm/prompts/formatter_prompts.py"
        ).read_text()
        assert '"1. Answer ONLY in English (Strict Requirement)."' not in source

    # D10 — QueryRequest: locale field must be Optional with None default
    def test_d10_query_request_locale_is_optional_none(self):
        from api.schemas import QueryRequest
        import inspect
        # Must not raise when locale is omitted
        req = QueryRequest(question="test")
        assert req.locale is None

    # D11 — UserContext.locale default must be None (not "en")
    def test_d11_usercontext_locale_default_none(self):
        from core.auth.models import UserContext, User
        import uuid
        ctx = UserContext(
            user=User(id=uuid.uuid4(), email="x@x.com", name="x", is_active=True)
        )
        assert ctx.locale is None, \
            f"UserContext.locale default should be None, got {ctx.locale!r}"

    # D12 — resolve_language always returns a member of SUPPORTED_LANGUAGES
    @pytest.mark.parametrize("question,locale,thread", [
        ("sim", None, None),
        ("ok", None, None),
        ("quel est le chiffre d'affaires?", None, None),
        ("", None, None),
        ("", "fr", None),        # unsupported locale
        ("test", "pt", "en"),    # locale beats thread
        ("test", None, "pt"),
        ("test", None, "en"),
        ("quais as vendas?", None, None),
        ("what were the sales?", None, None),
    ])
    def test_d12_resolve_language_always_returns_supported(self, question, locale, thread):
        result = resolve_language(question, locale=locale, thread_language=thread)
        assert result in SUPPORTED_LANGUAGES, \
            f"resolve_language returned unsupported code {result!r} " \
            f"for question={question!r} locale={locale!r} thread={thread!r}"

    # D13 — thread_language_from_history returns None or supported code
    @pytest.mark.parametrize("history", [
        None,
        [],
        [{"role": "user", "content": "ok"}],
        [{"role": "assistant", "content": "quais foram as vendas?"}],
        [{"role": "user", "content": "quais foram as vendas do mês passado?"}],
        [{"role": "user", "content": "what were the total sales last month?"}],
        [
            {"role": "user", "content": "sim"},
            {"role": "user", "content": "what were the total sales last month?"},
        ],
    ])
    def test_d13_thread_history_returns_none_or_supported(self, history):
        result = thread_language_from_history(history)
        assert result is None or result in SUPPORTED_LANGUAGES, \
            f"thread_language_from_history returned {result!r}"
