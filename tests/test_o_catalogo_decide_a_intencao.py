"""Perguntas de dados iam parar à conversa.

Produção, 10/10/2026, ligação «Operaciones» (14 tabelas: routes, trips,
festivos, gasoleo_historico_diario, incidencias_trafico, gasolineras_rota…),
`locale=es`. Estas quatro receberam conversa («Lo siento, no dispongo…»,
«Claro, puedo buscar…») e nenhum SQL:

    «Qué festivos nacionales hay en los próximos 30 días y qué restricciones
     a pesados aplican esos días»
    «Precio medio diario del gasóleo A en los últimos 30 días según
     gasoleo_historico_diario»                      ← nomeia a tabela!
    «¿Cuántas incidencias de tráfico hay ahora en la A-5?»
    «¿Cuál es la gasolinera más barata de gasóleo A a menos de 3 km de la
     ruta Badajoz–Madrid?»

Não pontuavam em nenhum padrão («cuántas», «precio», «medio», «más barata»
não existiam), e com zero sinais a pergunta ia ao modelo — que, sem ver o
catálogo, chamava «mundo» a feriados, combustível e trânsito.

O modelo é aqui substituído por um que responde SEMPRE «MUNDO»: é o pior
caso, e o que se viu em produção. Se a pergunta chega aos dados mesmo assim,
é porque o classificador decidiu antes de perguntar.
"""

from __future__ import annotations

import pytest

from core.intent.question_intent import (
    QuestionIntent,
    classify_question_intent,
    termos_do_catalogo,
    toca_no_catalogo,
)


class _ModeloQueDizSempreMundo:
    def __init__(self):
        self.chamadas = 0

    def invoke(self, mensagens):
        self.chamadas += 1
        # O catálogo NUNCA vai no prompt (regra 1 de perguntar_ao_modelo).
        texto = " ".join(m["content"] for m in mensagens)
        assert "gasoleo_historico_diario" not in texto.split("<frase>")[0]
        return "MUNDO"


# O catálogo da «Operaciones», como o agente o recebe (nomes e colunas reais
# do carregador `dados_publicos/mundo/esquema.py`).
OPERACIONES = [
    {
        "logical_name": "routes",
        "columns": [
            {"name": "origin"},
            {"name": "destination"},
            {"name": "distance_km"},
        ],
    },
    {
        "logical_name": "trips",
        "columns": [
            {"name": "route_id"},
            {"name": "fuel_liters"},
            {"name": "cost_eur"},
        ],
    },
    {
        "logical_name": "festivos",
        "description": "Feriados nacionais e regionais ES/PT, a partir do BOE e do Código do Trabalho.",
        "columns": [
            {"name": "data"},
            {"name": "pais"},
            {"name": "regiao"},
            {"name": "nome"},
        ],
    },
    {
        "logical_name": "gasoleo_historico_diario",
        "description": "Gasóleo A por província e dia (MITECO).",
        "columns": [
            {"name": "data"},
            {"name": "provincia"},
            {"name": "minimo"},
            {"name": "media"},
        ],
    },
    {
        "logical_name": "incidencias_trafico",
        "description": "Incidências DGT (DATEX II v3.7).",
        "columns": [
            {"name": "carretera"},
            {"name": "pk"},
            {"name": "gravidade"},
            {"name": "activa"},
        ],
    },
    {
        "logical_name": "gasolineras_rota",
        "description": "Postos espanhóis a ≤5 km do traçado (OSRM) de cada rota da demo.",
        "columns": [
            {"name": "origem"},
            {"name": "destino"},
            {"name": "id_estacion"},
            {"name": "dist_km"},
        ],
    },
    {
        "logical_name": "gasolineras_precio",
        "columns": [
            {"name": "rotulo"},
            {"name": "municipio"},
            {"name": "precio_gasoleo_a"},
        ],
    },
    {
        "logical_name": "restricoes_pesados",
        "columns": [{"name": "data"}, {"name": "estrada"}],
    },
    {
        "logical_name": "tempo_cidades",
        "columns": [{"name": "cidade"}, {"name": "temperatura_max"}],
    },
]

TERMOS = termos_do_catalogo(OPERACIONES)

PERGUNTAS_DE_PRODUCAO = [
    "Lista las 5 gasolineras con el gasóleo A más barato en la tabla gasolineras_rota para la ruta Badajoz-Madrid",
    "Qué festivos nacionales hay en los próximos 30 días y qué restricciones a pesados aplican esos días",
    "Precio medio diario del gasóleo A en los últimos 30 días según gasoleo_historico_diario",
    "¿Cuántas incidencias de tráfico hay ahora en la A-5?",
    "¿Cuál es la gasolinera más barata de gasóleo A a menos de 3 km de la ruta Badajoz–Madrid?",
]


@pytest.mark.parametrize("pergunta", PERGUNTAS_DE_PRODUCAO)
def test_as_perguntas_de_producao_vao_aos_dados(pergunta):
    modelo = _ModeloQueDizSempreMundo()
    intent = classify_question_intent(pergunta, llm=modelo, catalog_terms=TERMOS)
    assert intent == QuestionIntent.DATA
    # E decidiu sem perguntar ao modelo.
    assert modelo.chamadas == 0


@pytest.mark.parametrize(
    "pergunta",
    [
        # Só o catálogo as segura: nenhum verbo de negócio.
        "¿Hay incidencias de tráfico ahora en la A-5?",
        "Qué festivos hay en Extremadura",
        "¿Qué restricciones a pesados hay el sábado?",
        "Feriados em Portugal",
    ],
)
def test_o_catalogo_sozinho_chega_para_ir_aos_dados(pergunta):
    modelo = _ModeloQueDizSempreMundo()
    com = classify_question_intent(pergunta, llm=modelo, catalog_terms=TERMOS)
    assert com == QuestionIntent.DATA
    # A mesma pergunta numa ligação SEM estas tabelas continua a ser do
    # mundo — é o catálogo que decide, não o assunto.
    sem = classify_question_intent(
        pergunta,
        llm=_ModeloQueDizSempreMundo(),
        catalog_terms=termos_do_catalogo(
            [{"logical_name": "orders", "columns": [{"name": "amount"}]}]
        ),
    )
    assert sem == QuestionIntent.CONVERSA


def test_ahora_nao_manda_para_a_conversa_quando_ha_tabela_que_responde():
    q = "¿Qué incidencias hay ahora mismo en la N-430?"
    assert (
        classify_question_intent(
            q, llm=_ModeloQueDizSempreMundo(), catalog_terms=TERMOS
        )
        == QuestionIntent.DATA
    )


@pytest.mark.parametrize(
    "conversa",
    ["Hola", "Buenos días", "Gracias", "Olá", "bom dia", "Obrigado!", "¿Cómo estás?"],
)
def test_conversa_a_serio_continua_conversa_com_o_catalogo_ligado(conversa):
    assert (
        classify_question_intent(conversa, catalog_terms=TERMOS)
        == QuestionIntent.CONVERSA
    )


@pytest.mark.parametrize(
    "mundo",
    [
        "¿Quién es el presidente de Francia?",
        "Cuéntame un chiste",
        "Qual a capital da Austrália?",
    ],
)
def test_perguntas_do_mundo_sem_tabela_continuam_conversa(mundo):
    assert (
        classify_question_intent(
            mundo, llm=_ModeloQueDizSempreMundo(), catalog_terms=TERMOS
        )
        == QuestionIntent.CONVERSA
    )


@pytest.mark.parametrize(
    "pergunta",
    [
        "¿Cuántos viajes hicimos en septiembre?",
        "Precio medio del gasóleo por provincia",
        "Muéstrame el máximo y el mínimo de la semana",
        "Lista los 10 clientes con más pedidos",
        "Quantos pedidos tivemos nos últimos 7 dias?",
    ],
)
def test_verbos_e_agregacoes_em_espanhol_sao_sinal_de_dados_mesmo_sem_catalogo(
    pergunta,
):
    modelo = _ModeloQueDizSempreMundo()
    assert classify_question_intent(pergunta, llm=modelo) == QuestionIntent.DATA
    assert modelo.chamadas == 0


def test_palavras_genericas_de_esquema_nao_contam_como_catalogo():
    """`data`, `nome`, `valor`, `estado`… estão em todas as tabelas e em
    todas as frases; não podem fazer de qualquer frase uma pergunta de dados."""
    termos = termos_do_catalogo(
        [
            {
                "logical_name": "x",
                "columns": [
                    {"name": "data"},
                    {"name": "nome"},
                    {"name": "estado"},
                    {"name": "valor"},
                ],
            }
        ]
    )
    assert not toca_no_catalogo("Qual é o teu nome? E o estado do tempo?", termos)
