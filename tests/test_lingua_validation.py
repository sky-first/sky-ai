"""
Validation suite for the lingua-based language detection.

Covers every meaningful combination:
  - Pure EN questions
  - Pure PT questions
  - Mixed PT+EN (code-switching / loanwords)
  - Locale passed (pt, en, pt-BR, en-US, unsupported)
  - Thread active (pt or en)
  - Locale + thread combined
  - Gatekeeper: unsupported languages (FR, ES, DE, IT, ZH, RU…)
  - Short follow-ups (sim, yes, ok, manda, sure…)
  - Numbers as selections (1, 2, 3)
  - Empty / whitespace / garbage input
  - Very long questions
  - Questions with special characters and accents
  - Mixed-language question mid-thread
  - Locale overriding a thread of opposite language
"""

import pytest
from core.i18n.i18n import (
    detect_language,
    _detect_lingua_da_resposta,
    resolve_language,
    language_decision,
    thread_language_from_history,
    unsupported_language_message,
    SUPPORTED_LANGUAGES,
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. PURE ENGLISH — no locale, no thread
# ─────────────────────────────────────────────────────────────────────────────

PURE_EN = [
    "what were the total sales last month?",
    "how many active customers do we have today?",
    "show me the revenue breakdown by product",
    "which region had the highest growth this quarter?",
    "what is our customer acquisition cost?",
    "give me the top 10 accounts by revenue",
    "how many new signups did we get this week?",
    "what is the average order value this year?",
    "show me the churn rate trend over the last 6 months",
    "which campaigns had the best ROI last quarter?",
    "what percentage of users are on the premium plan?",
    "how many support tickets were resolved today?",
    "what is the net promoter score for this month?",
    "show me daily active users for the last 30 days",
    "what are the top reasons customers cancel?",
    "how long does it take to close a deal on average?",
    "what is the monthly recurring revenue this year?",
    "which sales rep closed the most deals last month?",
    "how many leads converted to customers this quarter?",
    "show me the pipeline by stage and value",
]

@pytest.mark.parametrize("q", PURE_EN)
def test_pure_en_not_blocked(q):
    blocked, lang = language_decision(q)
    assert blocked is False, f"Blocked EN: {q!r}"

@pytest.mark.parametrize("q", PURE_EN)
def test_pure_en_detected_as_en(q):
    blocked, lang = language_decision(q)
    assert lang == "en", f"Expected en, got {lang!r}: {q!r}"

@pytest.mark.parametrize("q", PURE_EN)
def test_pure_en_bilingual_detector(q):
    assert _detect_lingua_da_resposta(q) == "en", f"Bilingual wrong for: {q!r}"

@pytest.mark.parametrize("q", PURE_EN)
def test_pure_en_with_locale_en(q):
    blocked, lang = language_decision(q, locale="en")
    assert blocked is False and lang == "en"

@pytest.mark.parametrize("q", PURE_EN)
def test_pure_en_with_locale_pt(q):
    # locale=pt must override detection → answer in PT, never blocked
    blocked, lang = language_decision(q, locale="pt")
    assert blocked is False and lang == "pt"

@pytest.mark.parametrize("q", PURE_EN)
def test_pure_en_with_thread_pt(q):
    # Thread PT → answer must be PT regardless of question language
    blocked, lang = language_decision(q, thread_language="pt")
    assert blocked is False and lang == "pt"


# ─────────────────────────────────────────────────────────────────────────────
# 2. PURE PORTUGUESE — no locale, no thread
# ─────────────────────────────────────────────────────────────────────────────

PURE_PT = [
    "quais foram as vendas totais do mês passado?",
    "quantos clientes ativos temos hoje?",
    "me mostra a receita por produto",
    "qual região teve maior crescimento esse trimestre?",
    "qual o custo de aquisição de clientes?",
    "me dá as 10 maiores contas por receita",
    "quantos novos cadastros tivemos essa semana?",
    "qual o ticket médio esse ano?",
    "me mostra a tendência de cancelamentos nos últimos 6 meses",
    "quais campanhas tiveram melhor retorno no trimestre?",
    "qual percentual de usuários está no plano premium?",
    "quantos tickets de suporte foram resolvidos hoje?",
    "qual o NPS do mês atual?",
    "me mostra os usuários ativos diários dos últimos 30 dias",
    "quais os principais motivos de cancelamento dos clientes?",
    "quanto tempo leva em média para fechar um negócio?",
    "qual a receita recorrente mensal esse ano?",
    "qual vendedor fechou mais negócios no mês passado?",
    "quantos leads converteram em clientes esse trimestre?",
    "me mostra o funil de vendas por estágio e valor",
]

@pytest.mark.parametrize("q", PURE_PT)
def test_pure_pt_not_blocked(q):
    blocked, lang = language_decision(q)
    assert blocked is False, f"Blocked PT: {q!r}"

@pytest.mark.parametrize("q", PURE_PT)
def test_pure_pt_detected_as_pt(q):
    blocked, lang = language_decision(q)
    assert lang == "pt", f"Expected pt, got {lang!r}: {q!r}"

@pytest.mark.parametrize("q", PURE_PT)
def test_pure_pt_bilingual_detector(q):
    assert _detect_lingua_da_resposta(q) == "pt", f"Bilingual wrong for: {q!r}"

@pytest.mark.parametrize("q", PURE_PT)
def test_pure_pt_with_locale_pt(q):
    blocked, lang = language_decision(q, locale="pt-BR")
    assert blocked is False and lang == "pt"

@pytest.mark.parametrize("q", PURE_PT)
def test_pure_pt_with_locale_en(q):
    # locale=en overrides → answer in EN, never blocked
    blocked, lang = language_decision(q, locale="en")
    assert blocked is False and lang == "en"

@pytest.mark.parametrize("q", PURE_PT)
def test_pure_pt_with_thread_en(q):
    # Thread EN → answer must be EN
    blocked, lang = language_decision(q, thread_language="en")
    assert blocked is False and lang == "en"


# ─────────────────────────────────────────────────────────────────────────────
# 3. MIXED PT + EN LOANWORDS (code-switching)
#    These were the main gaps with langdetect — must all pass with lingua.
# ─────────────────────────────────────────────────────────────────────────────

MIXED_PT_EN = [
    # Business acronyms
    "qual foi o EBITDA consolidado do trimestre?",
    "qual o MRR por plano de assinatura?",
    "qual o ARR projetado para o ano fiscal?",
    "qual o CAC médio por canal de aquisição?",
    "me mostra o LTV por segmento de cliente",
    "qual o GMV total processado esse mês?",
    "qual o burn rate atual da operação?",
    "qual o payback period médio dos clientes?",
    "me mostra os KPIs principais do board",
    # Loanwords: previously detected as wrong language
    "qual o pipeline de vendas atual por estágio?",
    "quais clientes fizeram upsell esse trimestre?",
    "qual o headcount atual por departamento?",
    "quantas features foram entregues no sprint?",
    "qual o capital de giro disponível hoje?",
    "ROI da campanha de marketing",
    "qual o churn rate do mês passado?",
    "qual o NPS do produto esse trimestre?",
    "qual o DAU médio do produto esse mês?",
    "me mostra a retenção D7 e D30 por coorte",
    "qual o time to value médio para novos clientes?",
    # Long mixed sentences (enough PT structure words to anchor detection)
    "qual o win rate do time de sales no último quarter?",
    "quais leads do inbound converteram melhor no funil esse mês?",
    "qual foi o churn involuntário versus voluntário no trimestre?",
    # NOTE: ultra-heavy EN loanwords below are in the limitation test
    # "me mostra o breakdown do gross profit por business unit no Q3"
    # "me mostra o dashboard de performance do produto com DAUs e MAUs"
]

# Sentences so dominated by EN loanwords that even a bilingual detector
# picks EN — not blocked, but may answer in EN without locale/thread.
ULTRA_MIXED_EN_HEAVY = [
    "me mostra o breakdown do gross profit por business unit no Q3",
    "me mostra o dashboard de performance do produto com DAUs e MAUs",
]

@pytest.mark.parametrize("q", MIXED_PT_EN)
def test_mixed_pt_en_not_blocked_no_signals(q):
    blocked, _ = language_decision(q)
    assert blocked is False, f"Mixed PT+EN blocked without signals: {q!r}"

@pytest.mark.parametrize("q", MIXED_PT_EN)
def test_mixed_pt_en_with_locale_pt_always_passes(q):
    blocked, lang = language_decision(q, locale="pt")
    assert blocked is False and lang == "pt", \
        f"With locale=pt blocked/wrong: {q!r} → blocked={blocked}, lang={lang!r}"

@pytest.mark.parametrize("q", MIXED_PT_EN)
def test_mixed_pt_en_with_locale_pt_br_always_passes(q):
    blocked, lang = language_decision(q, locale="pt-BR")
    assert blocked is False and lang == "pt"

@pytest.mark.parametrize("q", MIXED_PT_EN)
def test_mixed_pt_en_with_thread_pt_always_passes(q):
    blocked, lang = language_decision(q, thread_language="pt")
    assert blocked is False and lang == "pt", \
        f"With thread=pt blocked/wrong: {q!r} → blocked={blocked}, lang={lang!r}"

@pytest.mark.parametrize("q", MIXED_PT_EN)
def test_mixed_pt_en_resolve_with_locale(q):
    result = resolve_language(q, locale="pt-BR")
    assert result == "pt"

@pytest.mark.parametrize("q", MIXED_PT_EN)
def test_mixed_pt_en_bilingual_picks_pt(q):
    # The bilingual detector (EN+PT only) must pick PT for mixed PT+EN
    # (excludes ultra-EN-heavy cases which have their own test below)
    result = _detect_lingua_da_resposta(q)
    assert result == "pt", f"Bilingual picked {result!r} for: {q!r}"


@pytest.mark.parametrize("q", ULTRA_MIXED_EN_HEAVY)
def test_ultra_mixed_en_heavy_not_blocked(q):
    """
    KNOWN LIMITATION: Questions with >60% EN loanwords may be answered in
    EN even when the user wrote in PT. They are never blocked. With locale
    or thread active, PT is correctly selected.
    """
    blocked, _ = language_decision(q)
    assert blocked is False, f"Ultra-mixed EN-heavy blocked: {q!r}"


@pytest.mark.parametrize("q", ULTRA_MIXED_EN_HEAVY)
def test_ultra_mixed_en_heavy_with_locale_pt(q):
    blocked, lang = language_decision(q, locale="pt")
    assert blocked is False and lang == "pt"


@pytest.mark.parametrize("q", ULTRA_MIXED_EN_HEAVY)
def test_ultra_mixed_en_heavy_with_thread_pt(q):
    blocked, lang = language_decision(q, thread_language="pt")
    assert blocked is False and lang == "pt"


# ─────────────────────────────────────────────────────────────────────────────
# 4. LOCALE COMBINATIONS
# ─────────────────────────────────────────────────────────────────────────────

LOCALE_FORMATS = [
    ("pt",    "pt"),
    ("pt-BR", "pt"),
    ("pt-PT", "pt"),
    ("pt_BR", "pt"),
    ("PT",    "pt"),
    ("PT-BR", "pt"),
    ("en",    "en"),
    ("en-US", "en"),
    ("en-GB", "en"),
    ("en_US", "en"),
    ("EN",    "en"),
]

@pytest.mark.parametrize("locale,expected", LOCALE_FORMATS)
def test_locale_formats_all_accepted(locale, expected):
    blocked, lang = language_decision("test question text here", locale=locale)
    assert blocked is False and lang == expected, \
        f"locale={locale!r} → expected {expected!r}, got blocked={blocked} lang={lang!r}"

@pytest.mark.parametrize("locale,expected", LOCALE_FORMATS)
def test_locale_overrides_detection_en_question(locale, expected):
    blocked, lang = language_decision(
        "what were the total sales last month?", locale=locale
    )
    assert blocked is False and lang == expected

@pytest.mark.parametrize("locale,expected", LOCALE_FORMATS)
def test_locale_overrides_detection_pt_question(locale, expected):
    blocked, lang = language_decision(
        "quais foram as vendas do mês passado?", locale=locale
    )
    assert blocked is False and lang == expected

UNSUPPORTED_LOCALES = ["fr", "es", "de", "it", "zh", "ru", "ja", "ar"]

@pytest.mark.parametrize("locale", UNSUPPORTED_LOCALES)
def test_unsupported_locale_falls_through_to_detection(locale):
    # Unsupported locale → ignored → detection takes over
    result = resolve_language("what were the sales?", locale=locale)
    assert result in SUPPORTED_LANGUAGES

@pytest.mark.parametrize("locale", UNSUPPORTED_LOCALES)
def test_unsupported_locale_never_blocks_supported_question(locale):
    blocked, _ = language_decision(
        "what were the total sales last month?", locale=locale
    )
    assert blocked is False


# ─────────────────────────────────────────────────────────────────────────────
# 5. THREAD COMBINATIONS
# ─────────────────────────────────────────────────────────────────────────────

PT_HISTORY = [
    {"role": "user",      "content": "quais foram as vendas do mês passado?"},
    {"role": "assistant", "content": "As vendas foram R$ 2,4 milhões."},
    {"role": "user",      "content": "me mostra por região"},
    {"role": "assistant", "content": "A região Sul liderou com R$ 800k."},
]

EN_HISTORY = [
    {"role": "user",      "content": "what were the total sales last month?"},
    {"role": "assistant", "content": "Sales were $2.4 million."},
    {"role": "user",      "content": "show me by region"},
    {"role": "assistant", "content": "The South region led with $800k."},
]

SHORT_FOLLOWUPS_PT = [
    "sim", "claro", "pode", "manda", "isso mesmo", "tá bom",
    "e antes?", "por produto?", "e os custos?", "detalha",
    "qual a diferença?", "e no Q2?", "mostra mais", "ok",
]

SHORT_FOLLOWUPS_EN = [
    "yes", "sure", "ok", "please", "go ahead", "sounds good",
    "and before?", "by product?", "and costs?", "break it down",
    "what's the difference?", "and Q2?", "show more",
]

@pytest.mark.parametrize("followup", SHORT_FOLLOWUPS_PT)
def test_pt_thread_short_followup_stays_pt(followup):
    thread_lang = thread_language_from_history(PT_HISTORY)
    result = resolve_language(followup, thread_language=thread_lang)
    assert result == "pt", f"PT thread + '{followup}' → {result!r}"

@pytest.mark.parametrize("followup", SHORT_FOLLOWUPS_EN)
def test_en_thread_short_followup_stays_en(followup):
    thread_lang = thread_language_from_history(EN_HISTORY)
    result = resolve_language(followup, thread_language=thread_lang)
    assert result == "en", f"EN thread + '{followup}' → {result!r}"

@pytest.mark.parametrize("followup", SHORT_FOLLOWUPS_PT)
def test_pt_thread_followup_not_blocked(followup):
    blocked, lang = language_decision(followup, thread_language="pt")
    assert blocked is False and lang == "pt"

@pytest.mark.parametrize("followup", SHORT_FOLLOWUPS_EN)
def test_en_thread_followup_not_blocked(followup):
    blocked, lang = language_decision(followup, thread_language="en")
    assert blocked is False and lang == "en"


# ─────────────────────────────────────────────────────────────────────────────
# 6. LOCALE + THREAD COMBINED (locale always wins)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("question", [
    "what were the sales?",
    "quais as vendas?",
    "sim",
    "yes",
])
def test_locale_pt_beats_en_thread(question):
    blocked, lang = language_decision(
        question, locale="pt", thread_language="en"
    )
    assert blocked is False and lang == "pt"

@pytest.mark.parametrize("question", [
    "what were the sales?",
    "quais as vendas?",
    "sim",
    "yes",
])
def test_locale_en_beats_pt_thread(question):
    blocked, lang = language_decision(
        question, locale="en", thread_language="pt"
    )
    assert blocked is False and lang == "en"

@pytest.mark.parametrize("locale,thread,expected", [
    ("pt",    "en", "pt"),
    ("en",    "pt", "en"),
    ("pt-BR", "en", "pt"),
    ("en-US", "pt", "en"),
])
def test_locale_always_beats_thread(locale, thread, expected):
    blocked, lang = language_decision(
        "any question here", locale=locale, thread_language=thread
    )
    assert blocked is False and lang == expected


# ─────────────────────────────────────────────────────────────────────────────
# 7. UNSUPPORTED LANGUAGES — gatekeeper must block
# ─────────────────────────────────────────────────────────────────────────────

UNSUPPORTED_QUESTIONS = [
    ("fr", "quel a été le chiffre d'affaires du mois dernier en France?"),
    ("fr", "combien de clients actifs avons-nous aujourd'hui?"),
    ("fr", "quels sont les produits les plus vendus ce trimestre?"),
    ("de", "Was waren die Gesamtverkäufe im letzten Monat?"),
    ("de", "Wie viele aktive Kunden haben wir heute?"),
    ("it", "quali sono state le vendite totali del mese scorso?"),
    ("it", "quanti clienti attivi abbiamo oggi?"),
    ("nl", "wat waren de totale verkopen afgelopen maand?"),
    ("ru", "каковы были общие продажи за прошлый месяц?"),
    ("zh", "上个月的总销售额是多少?"),
    ("ja", "先月の総売上高はいくらでしたか?"),
    ("ko", "지난 달 총 판매량은 얼마였나요?"),
    ("ar", "ما كانت إجمالي المبيعات الشهر الماضي؟"),
]

# O espanhol saiu desta lista a 24/08/2026.
#
# Passou a ser lingua suportada, portanto uma pergunta em espanhol tem de
# ser RESPONDIDA em espanhol, e nao bloqueada. As duas frases que estavam
# aqui mudaram-se para `SUPPORTED_SPANISH` em baixo, com a asercao ao
# contrario — porque uma frase que deixa de ser bloqueada e uma frase que
# tem de passar a ter resposta, e so a segunda metade prova isso.
SUPPORTED_SPANISH = [
    "¿cuáles fueron las ventas totales del mes pasado en España?",
    "¿cuántos clientes activos tenemos hoy?",
    "cuantos clientes activos tenemos hoy",
    "muestrame las ventas por region del ultimo trimestre",
]


@pytest.mark.parametrize("question", SUPPORTED_SPANISH)
def test_spanish_is_answered_not_blocked(question):
    blocked, lang = language_decision(question)
    assert blocked is False, f"espanhol bloqueado: {question!r}"
    assert lang == "es", f"espanhol respondido em {lang!r}: {question!r}"


# **O portugues com jargao ingles NAO pode virar espanhol.**
#
# Foi o unico dano real de acrescentar o espanhol ao detector: a frase de
# baixo media ES 0,351 / PT 0,327 / EN 0,322 — um empate a tres — e com o
# empate a decidir ganhava o espanhol. Uma pergunta portuguesa respondida
# em espanhol a frente de um cliente e dos erros mais caros que a app pode
# cometer.
PT_COM_JARGAO_INGLES = [
    "qual o win rate do time de sales no último quarter?",
    "qual o pipeline de vendas atual por estágio?",
    "quais clientes fizeram upsell esse trimestre?",
    "qual o churn rate do último trimestre?",
    "qual o headcount atual por departamento?",
]


@pytest.mark.parametrize("question", PT_COM_JARGAO_INGLES)
def test_portugues_com_jargao_nao_vira_espanhol(question):
    assert _detect_lingua_da_resposta(question) == "pt", (
        f"{question!r} deixou de ser portugues"
    )


@pytest.mark.parametrize("lang_code,question", UNSUPPORTED_QUESTIONS)
def test_unsupported_lang_blocked_no_signals(lang_code, question):
    blocked, lang = language_decision(question)
    assert blocked is True, f"{lang_code} not blocked: {question!r}"

@pytest.mark.parametrize("lang_code,question", UNSUPPORTED_QUESTIONS)
def test_unsupported_lang_locale_pt_prevents_block(lang_code, question):
    blocked, lang = language_decision(question, locale="pt")
    assert blocked is False and lang == "pt"

@pytest.mark.parametrize("lang_code,question", UNSUPPORTED_QUESTIONS)
def test_unsupported_lang_locale_en_prevents_block(lang_code, question):
    blocked, lang = language_decision(question, locale="en")
    assert blocked is False and lang == "en"

@pytest.mark.parametrize("lang_code,question", UNSUPPORTED_QUESTIONS)
def test_unsupported_lang_thread_prevents_block(lang_code, question):
    blocked, lang = language_decision(question, thread_language="pt")
    assert blocked is False and lang == "pt"

@pytest.mark.parametrize("lang_code,question", UNSUPPORTED_QUESTIONS)
def test_unsupported_block_message_names_every_supported_language(lang_code, question):
    blocked, _ = language_decision(question)
    if blocked:
        msg = unsupported_language_message()
        # Tres linguas, e a frase tem de aparecer nas tres: quem escreve em
        # alemao nao le a versao portuguesa.
        assert "English, Portuguese and Spanish" in msg
        assert "inglês, português e espanhol" in msg
        assert "inglés, portugués y español" in msg


# ─────────────────────────────────────────────────────────────────────────────
# 8. EDGE CASES — empty, short, numeric, garbage, accents
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", ["", "   ", "\t\n", None if False else ""])
def test_empty_text_returns_en(text):
    assert detect_language(text) == "en"
    assert _detect_lingua_da_resposta(text) == "en"
    assert resolve_language(text) == "en"

@pytest.mark.parametrize("text,expected_lang", [
    ("1",  "en"),
    ("2",  "en"),
    ("3",  "en"),
    ("ok", "en"),
])
def test_very_short_text_falls_back_to_en(text, expected_lang):
    result = resolve_language(text)
    assert result == expected_lang

@pytest.mark.parametrize("q", ["1", "2", "3"])
def test_numeric_selection_not_blocked(q):
    blocked, _ = language_decision(q)
    assert blocked is False

def test_very_long_pt_question():
    q = ("quais foram as vendas totais consolidadas por região geográfica "
         "no último trimestre considerando todos os canais de distribuição "
         "incluindo vendas diretas, indiretas e online para o mercado "
         "brasileiro e internacional com comparativo ao mesmo período "
         "do ano anterior?")
    blocked, lang = language_decision(q)
    assert blocked is False and lang == "pt"

def test_very_long_en_question():
    q = ("what were the total consolidated sales by geographic region "
         "in the last quarter considering all distribution channels "
         "including direct, indirect and online sales for the domestic "
         "and international markets with a comparison to the same period "
         "of the previous year and the forecast for next quarter?")
    blocked, lang = language_decision(q)
    assert blocked is False and lang == "en"

def test_question_with_special_chars_pt():
    q = "qual a variação percentual (%) do faturamento em relação ao mês anterior?"
    blocked, lang = language_decision(q)
    assert blocked is False and lang == "pt"

def test_question_with_numbers_and_currency_pt():
    q = "quais clientes gastaram mais de R$ 50.000 no último trimestre?"
    blocked, lang = language_decision(q)
    assert blocked is False and lang == "pt"

def test_question_with_numbers_and_currency_en():
    q = "which customers spent more than $50,000 last quarter?"
    blocked, lang = language_decision(q)
    assert blocked is False and lang == "en"

def test_resolve_always_returns_supported_language():
    garbage_inputs = [
        "xkcd 1234 foo bar baz",
        "!!!@@@###",
        "123 456 789",
    ]
    for text in garbage_inputs:
        result = resolve_language(text)
        assert result in SUPPORTED_LANGUAGES, \
            f"resolve_language returned {result!r} for garbage: {text!r}"


# ─────────────────────────────────────────────────────────────────────────────
# 9. MIXED-LANGUAGE QUESTION MID-THREAD
#    User switches language in the middle of a PT conversation.
#    Expected: locale wins > thread wins > detection.
# ─────────────────────────────────────────────────────────────────────────────

def test_en_question_in_pt_thread_stays_pt_by_thread():
    # No locale, thread=PT, user asks in EN → thread wins → PT
    blocked, lang = language_decision(
        "what were the sales last month?", thread_language="pt"
    )
    assert blocked is False and lang == "pt"

def test_pt_question_in_en_thread_stays_en_by_thread():
    blocked, lang = language_decision(
        "quais foram as vendas do mês passado?", thread_language="en"
    )
    assert blocked is False and lang == "en"

def test_locale_pt_en_question_mid_thread_en():
    # locale=PT + EN thread + EN question → locale wins → PT
    blocked, lang = language_decision(
        "what were the sales?",
        locale="pt",
        thread_language="en",
    )
    assert blocked is False and lang == "pt"

def test_locale_en_pt_question_mid_thread_pt():
    # locale=EN + PT thread + PT question → locale wins → EN
    blocked, lang = language_decision(
        "quais foram as vendas?",
        locale="en",
        thread_language="pt",
    )
    assert blocked is False and lang == "en"


# ─────────────────────────────────────────────────────────────────────────────
# 10. RESOLVE_LANGUAGE — full priority chain exhaustive
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("question,locale,thread,expected", [
    # locale wins
    ("what were the sales?",                "pt",    "en",  "pt"),
    ("quais as vendas?",                    "en",    "pt",  "en"),
    ("sim",                                 "pt",    None,  "pt"),
    ("yes",                                 "en",    None,  "en"),
    # thread wins (no locale)
    ("sim",                                 None,    "pt",  "pt"),
    ("ok",                                  None,    "en",  "en"),
    ("and last month?",                     None,    "en",  "en"),
    ("e o mês passado?",                    None,    "pt",  "pt"),
    # detection (no locale, no thread)
    ("what were the total sales?",          None,    None,  "en"),
    ("quais foram as vendas do mês?",       None,    None,  "pt"),
    # fallback (ambiguous, no signals)
    ("sim",                                 None,    None,  "en"),  # too short
    # unsupported locale → fall through
    ("what were the sales?",                "fr",    None,  "en"),
    ("quais as vendas?",                    "de",    None,  "pt"),
])
def test_resolve_language_priority_chain(question, locale, thread, expected):
    result = resolve_language(question, locale=locale, thread_language=thread)
    assert result == expected, \
        f"q={question!r} locale={locale!r} thread={thread!r} → expected {expected!r}, got {result!r}"


# ─────────────────────────────────────────────────────────────────────────────
# 11. THREAD HISTORY EXTRACTION — various history shapes
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("history,expected", [
    (None,  None),
    ([],    None),
    # Only short messages
    ([{"role": "user", "content": "ok"}], None),
    ([{"role": "user", "content": "sim"}], None),
    # Only assistant messages (should be ignored)
    ([{"role": "assistant", "content": "quais foram as vendas do mês passado?"}], None),
    # First real user message is PT
    ([
        {"role": "user", "content": "quais foram as vendas do mês passado?"},
        {"role": "assistant", "content": "As vendas foram R$ 2,4M."},
    ], "pt"),
    # First real user message is EN
    ([
        {"role": "user", "content": "what were the total sales last month?"},
        {"role": "assistant", "content": "Sales were $2.4M."},
    ], "en"),
    # Short first, long second → picks long one
    ([
        {"role": "user", "content": "ok"},
        {"role": "user", "content": "quais foram as vendas do mês passado?"},
    ], "pt"),
    # Mixed roles: assistant PT, user EN → picks user EN
    ([
        {"role": "assistant", "content": "quais foram as vendas do mês passado?"},
        {"role": "user",      "content": "what were the total sales last month?"},
    ], "en"),
])
def test_thread_history_extraction(history, expected):
    result = thread_language_from_history(history)
    assert result == expected, \
        f"history={history} → expected {expected!r}, got {result!r}"


# ─────────────────────────────────────────────────────────────────────────────
# 12. REGRESSION: cases that were broken with langdetect, now fixed
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("question,expected_lang,old_behavior", [
    ("qual o pipeline de vendas atual por estágio?",    "pt", "en → errado"),
    ("quais clientes fizeram upsell esse trimestre?",   "pt", "fr → BLOQUEAVA"),
    ("qual o headcount atual por departamento?",        "pt", "es → errado"),
    ("quantas features foram entregues no sprint?",     "pt", "en → errado"),
    ("qual o capital de giro disponível hoje?",         "pt", "en → errado"),
    ("ROI da campanha de marketing",                    "pt", "variável → errado"),
    ("qual o EBITDA consolidado do trimestre?",         "pt", "variável → errado"),
    ("qual a taxa de win rate dos últimos 90 dias?",    "pt", "variável → errado"),
    ("me mostra o balanço patrimonial consolidado",     "pt", "variável → errado"),
    ("qual o fluxo de caixa operacional do semestre?",  "pt", "variável → errado"),
])
def test_regression_previously_broken_with_langdetect(question, expected_lang, old_behavior):
    blocked, lang = language_decision(question)
    assert blocked is False, \
        f"REGRESSION: {question!r} is being blocked (was: {old_behavior})"
    assert lang == expected_lang, \
        f"REGRESSION: {question!r} → expected {expected_lang!r}, got {lang!r} (was: {old_behavior})"
