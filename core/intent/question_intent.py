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

from core.intent.perguntas_sobre_o_mundo import parece_do_mundo

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
    # «¿Cómo estás?» — em espanhol a frase abre com «¿» ou «¡», e sem isto
    # nenhum cumprimento espanhol escrito como deve ser era reconhecido.
    r"^\s*[¿¡]?\s*("
    # cumprimentos
    r"ol[aá]|oi|bom\s*dia|boa\s*tarde|boa\s*noite|"
    r"hello|hi|hey|good\s*(morning|afternoon|evening)|"
    r"hola|buenos\s*d[ií]as|buenas\s*(tardes|noches)|"
    # como estas
    # «vao» e «estao» faltavam: «Como vao as coisas por ai?» — que E um
    # cumprimento — ia aos dados. Tem de estar nos dois sitios, aqui e em
    # `_ABERTURAS_AMBIGUAS`; so num nao chega, e foi o que me aconteceu.
    r"tudo\s*(bem|bom)|como\s*(vai|est[aá]s?|vais|v[aã]o|est[aã]o)|"
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


#: ⚠️ Aberturas que servem para cumprimentar **e** para perguntar.
#:
#: «Como está?» e um cumprimento. «Como está a correr o mes?» e uma
#: pergunta a serio — e o padrao de cumprimento roubava-a, porque casa
#: com «como esta» e o resto da frase nao tem vocabulario de negocio
#: nenhum. Encontrei cinco assim, todas a irem parar a conversa:
#:
#:     conversa  | Como esta a correr o mes?
#:     conversa  | Como esta o projeto Alfa?
#:     conversa  | Como vai o pipeline?
#:     conversa  | Como esta a equipa?
#:     conversa  | Tudo bem com o fecho?
#:
#: E, com ironia, «Como vao as coisas por ai?» — que E um cumprimento —
#: ia aos dados.
#:
#: «Ola» e «bom dia» nao entram nesta lista: ninguem comeca uma pergunta
#: de negocio com «ola» sem virgula, e quando comeca a virgula separa-as.
_ABERTURAS_AMBIGUAS = re.compile(
    r"^\s*[¿¡]?\s*("
    r"tudo\s*(bem|bom)|"
    # «vao» faltava aqui e no padrao principal: «Como vao as coisas por
    # ai?» — que E um cumprimento — ia aos dados. Anterior a isto.
    r"como\s*(vai|vais|v[aã]o|est[aá]s?|est[aã]o)|"
    r"qu[eé]\s*tal|c[oó]mo\s*est[aá]s?|c[oó]mo\s*va[ns]?|"
    r"how\s*(are|is\s*it\s*going)|what'?s\s*up|how'?s\s*it\s*going"
    r")",
    re.IGNORECASE,
)

#: O que pode vir a seguir a uma abertura ambigua sem deixar de ser um
#: cumprimento. Fora disto, ha um assunto — e um assunto faz da frase uma
#: pergunta.
_CAUDA_DE_CUMPRIMENTO = re.compile(
    r"^[\s,.!?¿¡]*"
    r"(por\s*(a[ií]|l[aá])|contigo|com\s*voc[eê]s?|voc[eê]s?|tu|you|"
    r"hoje|ent[aã]o|a[ií]|tudo|as\s*coisas(\s*por\s*a[ií])?|"
    r"with\s*you|there|today)?"
    r"[\s,.!?]*$",
    re.IGNORECASE,
)


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
    # ── A segunda porta: perguntas sobre o mundo ─────────────────────
    #
    # «Quantos graus fazem hoje em Lisboa?» — o exemplo que o Lucas deu —
    # nao e um cumprimento, tem seis palavras, e traz DOIS sinais de
    # negocio («quantos», «hoje»). Falhava nas tres condicoes e ia ao
    # motor de SQL procurar uma tabela de meteorologia. Vi-o em producao.
    #
    # Isto ganha ao sinal de negocio, e e a unica coisa que o faz. Os
    # padroes estao escritos com esse medo — ver o modulo, e sobretudo a
    # lista de quase-erros nos testes.
    if parece_do_mundo(q):
        return True

    if not _CONVERSA_PATTERNS.match(q):
        return False
    if len(q.split()) > _MAX_PALAVRAS_DE_CONVERSA:
        return False

    # Uma abertura ambigua so e um cumprimento se nao vier assunto atras.
    # «Como esta?» sim; «Como esta a correr o mes?» nao.
    ambigua = _ABERTURAS_AMBIGUAS.match(q)
    if ambigua:
        if not _CAUDA_DE_CUMPRIMENTO.match(q[ambigua.end() :]):
            return False
        # E se a cauda esta na lista, e cumprimento e acabou — sem passar
        # pela regra dos zero sinais.
        #
        # «Como estas hoje?» morria la: «hoje» conta como sinal de dados.
        # Mas ali nao ha assunto nenhum, so um adverbio — e a lista de
        # caudas e fechada e nao tem um unico substantivo de negocio.
        # Uma frase feita so de abertura e cauda nao tem do que falar.
        return True

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
    # ── Verbos e agregacoes que faltavam (10/10/2026) ──────────────
    #
    # «¿Cuántas incidencias de tráfico hay ahora en la A-5?» e «Precio
    # medio diario del gasóleo A…» nao pontuavam em NADA: «cuántas» so
    # existia em portugues («quantas») e «medio», «precio», «más barato»
    # nao existiam. Com zero sinais, a pergunta ia ao classificador do
    # modelo, que via «festivos nacionales» ou «ahora» e respondia MUNDO
    # — e a pessoa recebia conversa em vez dos dados que tinha ligados.
    r"cu[aá]nt[oa]s?|cu[aá]nto|"
    r"precios?|pre[cç]os?|"
    r"medi[oa]|m[ií]nim[oa]s?|m[aá]xim[oa]s?|m[ée]dio|"
    r"m[aá]s\s+barat[oa]s?|m[aá]s\s+car[oa]s?|mais\s+barat[oa]s?|mais\s+car[oa]s?|"
    r"lista|listar|liste|enumera|mu[eé]strame|muestra|mostra|"
    r"[uú]ltim[oa]s\s+\d+|pr[oó]xim[oa]s\s+\d+|"
    r"diari[oa]s?|di[aá]ri[oa]s?|semanal|"
    r"ranking|"
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


# ── O catálogo da ligação também é um sinal ─────────────────────────
#
# Visto em produção a 10/10/2026, na ligação «Operaciones» (14 tabelas,
# entre elas `festivos`, `gasoleo_historico_diario`, `incidencias_trafico`,
# `gasolineras_rota`). Quatro perguntas foram parar à conversa:
#
#     «Qué festivos nacionales hay en los próximos 30 días…»
#     «Precio medio diario del gasóleo A … según gasoleo_historico_diario»
#     «¿Cuántas incidencias de tráfico hay ahora en la A-5?»
#     «¿Cuál es la gasolinera más barata de gasóleo A a menos de 3 km…?»
#
# A segunda NOMEIA a tabela. O classificador não sabia que tabelas havia:
# decidia só por vocabulário genérico de negócio, e o que não pontuava ia ao
# modelo — que via «festivos nacionales» ou «ahora» e respondia «mundo».
#
# Feriados, preços de combustível e trânsito SÃO assuntos do mundo — até ao
# dia em que a empresa os liga como dados. A partir daí, quem decide é o
# catálogo, não o assunto.
#
# ⚠️ O catálogo nunca entra no prompt do classificador do modelo (ver
# `perguntar_ao_modelo.py`, regra 1). É comparado aqui, localmente.

#: Palavras de esquema e de ligação que aparecem em quase todas as tabelas
#: e em quase todas as frases. Já normalizadas (sem acentos, minúsculas,
#: sem plural). Tokens com menos de 5 letras nunca contam.
_PALAVRAS_GENERICAS = frozenset(
    {
        "table", "tabla", "tabela", "dados", "datos", "fecha", "nombre",
        "valor", "value", "estado", "status", "fonte", "source", "linha",
        "linea", "descricao", "descripcion", "description", "created",
        "updated", "criado", "creado", "actualizado", "atualizado",
        "actualizacion", "atualizacao", "codigo", "chave", "clave", "inicio",
        "start", "primeiro", "primero", "ultimo", "ultima", "numero",
        "number", "quando", "cuando", "sobre", "entre", "desde", "hasta",
        "todos", "todas", "about", "their", "there", "which", "where",
        "segun", "segundo", "outro", "otro", "other", "cada", "texto",
        "string", "integer", "boolean", "timestamp", "registo", "registro",
        "record", "quais", "cuale", "cual", "actual", "atual", "current",
        "total", "count", "media", "average", "identificador", "identifier",
        "usado", "usada", "mostrar", "porque", "because",
    }
)


def _normalizar(texto: str) -> str:
    import unicodedata

    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.lower()


def _raiz(token: str) -> str:
    """Plural fora, para «gasolinera» casar com «gasolineras»."""
    if len(token) > 5 and token.endswith("es"):
        return token[:-2]
    if len(token) > 4 and token.endswith("s"):
        return token[:-1]
    return token


def _tokens(texto: str, minimo: int) -> set:
    return {
        _raiz(t)
        for t in re.findall(r"[a-z0-9]+", _normalizar(texto))
        if len(t) >= minimo and not t.isdigit()
    } - _PALAVRAS_GENERICAS


def termos_do_catalogo(tables) -> frozenset:
    """O que, no catálogo da ligação, identifica um assunto.

    Aceita os `TableSchema` do agente ou dicts com `logical_name`/`name`,
    `description` e `columns`. Devolve:

    * o nome inteiro de cada tabela (``gasoleo_historico_diario``) — quem
      escreve o nome da tabela está a pedir essa tabela;
    * as palavras dos nomes das tabelas e das colunas (``festivo``,
      ``incidencia``, ``gasolinera``, ``precio``…), com 5+ letras;
    * as palavras das descrições das tabelas, com 6+ letras (as descrições
      são prosa — mais ruído, por isso a fasquia é mais alta).
    """
    termos: set = set()
    for t in tables or []:
        get = (lambda k, _t=t: _t.get(k)) if isinstance(t, dict) else (
            lambda k, _t=t: getattr(_t, k, None)
        )
        for chave in ("logical_name", "name", "table_name", "physical_name"):
            nome = get(chave)
            if not nome:
                continue
            nome = str(nome).split(".")[-1].strip('"`[]')
            termos.add(_normalizar(nome))
            termos |= _tokens(nome, 5)
        descricao = get("description")
        if descricao:
            termos |= _tokens(str(descricao), 6)
        for col in get("columns") or []:
            nome_col = col.get("name") if isinstance(col, dict) else getattr(col, "name", None)
            if nome_col:
                termos |= _tokens(str(nome_col), 5)
    return frozenset(x for x in termos if x)


def toca_no_catalogo(question: str, catalog_terms) -> bool:
    """A pergunta fala de alguma coisa que esta ligação tem."""
    if not question or not catalog_terms:
        return False
    normal = _normalizar(question)
    # Nome inteiro da tabela, com sublinhados: casa como substring.
    for termo in catalog_terms:
        if "_" in termo and termo in normal:
            return True
    return bool(_tokens(question, 5) & set(catalog_terms))


def classify_question_intent(
    question: str,
    has_data_sources: bool = True,
    llm=None,
    catalog_terms=None,
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
    #
    # Excepto quando a pergunta fala do que a ligação TEM. «Festivos
    # nacionales» ou «el tiempo en Madrid» são conversa numa base de
    # vendas e dados numa base que tem `festivos` ou `tempo_cidades`.
    no_catalogo = toca_no_catalogo(q, catalog_terms)
    if not no_catalogo and _parece_conversa(q):
        return QuestionIntent.CONVERSA

    # Score each intent
    strategy_score = len(_STRATEGY_PATTERNS.findall(q))
    signals_score = len(_SIGNALS_PATTERNS.findall(q))
    relationships_score = len(_RELATIONSHIPS_PATTERNS.findall(q))
    people_score = len(_PEOPLE_PATTERNS.findall(q))
    widgets_score = len(_WIDGETS_PATTERNS.findall(q))
    catalog_score = len(_CATALOG_PATTERNS.findall(q))
    data_score = len(_DATA_BOOST_PATTERNS.findall(q))
    # Uma pergunta sobre uma tabela que existe é uma pergunta de dados,
    # mesmo sem nenhum verbo de negócio. Conta como sinal — e por isso
    # nunca chega ao classificador do modelo, que não vê o catálogo e
    # chamava «mundo» a feriados, combustíveis e trânsito.
    if no_catalogo:
        data_score += 1

    # ── Zero sinais: perguntar ao modelo em vez de adivinhar ─────────
    #
    # O Lucas, depois de eu ter corrigido «quantos graus fazem hoje em
    # Lisboa» com uma lista de assuntos escrita a mao:
    #
    #     «essa e uma pergunta qualquer, poderia ser qual o nome do
    #     presidente do Brasil, voce trata como?»
    #
    # Tratava mal. Provei-o em producao: so apanhava o que estava na
    # lista. Presidente do Brasil, capital da Australia, uma piada — tudo
    # ia ao motor de SQL.
    #
    # A causa esta no fundo: o que nao pontua em nada cai no valor por
    # omissao, que e `data`. Adivinhar por palavras funciona para
    # reconhecer NEGOCIO — o vocabulario e finito e e nosso. Nao funciona
    # para reconhecer O MUNDO, que nao e.
    #
    # ⚠️ So aqui, e so com zero sinais de tudo. «Receita por regiao» nunca
    # chega a esta linha; «qual a capital da Australia» chega sempre. Uma
    # pergunta de negocio nunca gasta a chamada.
    #
    # Seguranca em `core/intent/perguntar_ao_modelo.py` e no desenho em
    # `docs/perguntar-ao-modelo-em-vez-de-adivinhar.md`.
    if llm is not None and 0 == (
        data_score
        + strategy_score
        + signals_score
        + relationships_score
        + people_score
        + widgets_score
        + catalog_score
    ):
        from core.intent.perguntar_ao_modelo import e_pergunta_sobre_o_mundo

        if e_pergunta_sobre_o_mundo(q, llm):
            return QuestionIntent.CONVERSA

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
