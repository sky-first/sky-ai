"""Produção, 11/10/2026 — tenant skyfirstlabs, ligação «Operaciones»
(esquema `ops`, dados públicos), `locale=es`, depois de uma descoberta nova.

1. «Lista las 5 gasolineras con el gasóleo A más barato en la tabla
   gasolineras_rota para la ruta Badajoz-Madrid» → «Lo siento, pero no
   dispongo de la información necesaria…», sem SQL.

   A intenção já ia aos dados (#277). A causa estava a seguir:
   `gasolineras_rota` tem a rota (origem, destino) e o posto (id_estacion),
   mas NÃO tem preço — o preço está em `gasolineras_precio`. O orquestrador
   escolhe a tabela que a pessoa nomeia, o especialista só vê as colunas das
   tabelas escolhidas («FORBIDDEN from using any column not listed»), não
   encontra gasóleo nenhum e recusa. E nem que o modelo escolhesse as duas:
   a ligação `id_estacion` não existia para o Sky — a heurística só conhecia
   `*_id`, o Postgres não tem FK declarada e o metadado que chega ao agente
   não traz PK. O comentário da coluna dizia-o («FK
   gasolineras_precio.id_estacion») e ninguém o lia.

2. «Precio medio diario del gasóleo A en los últimos 30 días según
   gasoleo_historico_diario» → «Usted puede observar que el precio medio
   diario del gasóleo A en los últimos 30 días es de 1,90 € €.»
   (a) «€ €»: o modelo escreve «1,90 €» (espaço inseparável estreito)
       ou repete a moeda; a expressão só aceitava espaço normal ou
       inseparável antes do «€», reescrevia o número com «€» e deixava o
       «€» do modelo a seguir.
   (b) «Usted puede observar que…»: anúncio em vez do facto.
"""

from __future__ import annotations

import re

import pytest

from core.agents.generic_sql_agent import AgentConfig, TableSchema
from core.llm.numeros import (
    CorrecaoEmFluxo,
    corrigir_resposta,
    e_preco_por_litro,
    sem_anuncio,
)
from core.sql.relationships import (
    detect_relationships,
    tabelas_vizinhas_que_a_pergunta_pede,
)


def _t(nome, descricao, colunas):
    return TableSchema(
        logical_name=nome,
        physical_name=f"ops.{nome}",
        description=descricao,
        columns=[
            {"name": n, "type": tipo, "description": d} for (n, tipo, d) in colunas
        ],
    )


# As colunas reais (sky-backend scripts/dados_publicos/mundo/esquema.py), como
# chegam ao agente pelo load_agent_config_from_connection: nome, tipo e
# comentário — SEM is_primary_key nem is_foreign_key.
GASOLINERAS_ROTA = _t(
    "gasolineras_rota",
    "Postos espanhóis a ≤5 km do traçado (OSRM) de cada rota da demo.",
    [
        ("origem", "text", "Cidade de origem (= ops.routes.origin)"),
        ("destino", "text", "Cidade de destino (= ops.routes.destination)"),
        ("id_estacion", "integer", "FK gasolineras_precio.id_estacion"),
        (
            "dist_km",
            "double precision",
            "Distância do posto ao traçado da rota (km, até 5)",
        ),
        (
            "km_desde_origem",
            "double precision",
            "Km aproximado da rota onde o posto fica",
        ),
        (
            "calculado_em",
            "timestamp with time zone",
            "Quando a proximidade foi calculada (UTC)",
        ),
    ],
)
GASOLINERAS_PRECIO = _t(
    "gasolineras_precio",
    "Postos de combustível de Espanha (MITECO), preço actual.",
    [
        ("id_estacion", "integer", "IDEESS do MITECO"),
        ("rotulo", "text", "Marca / rótulo do posto"),
        ("direccion", "text", None),
        ("cp", "text", "Código postal"),
        ("localidad", "text", None),
        ("municipio", "text", None),
        ("provincia", "text", "Província (maiúsculas, como no MITECO)"),
        ("cod_provincia", "text", "Código INE da província (06 = Badajoz)"),
        ("lat", "double precision", None),
        ("lon", "double precision", None),
        ("carretera", "text", "Estrada extraída da morada"),
        ("pk", "double precision", "Ponto quilométrico extraído da morada"),
        ("margen", "text", "Margem da via"),
        ("horario", "text", None),
        ("tipo_venta", "text", "P = venda ao público, R = restringida"),
        ("precio_gasoleo_a", "numeric", "Gasóleo A, €/l, preço de bomba publicado"),
        ("precio_gasoleo_premium", "numeric", "Gasóleo Premium, €/l"),
        ("precio_gasoleo_b", "numeric", "Gasóleo B (agrícola), €/l"),
        ("precio_gasolina_95", "numeric", "Gasolina 95 E5, €/l"),
        ("precio_adblue", "numeric", "AdBlue, €/l"),
        ("actualizado_em", "timestamp with time zone", "Campo Fecha do MITECO (UTC)"),
        ("fonte", "text", None),
    ],
)
GASOLEO_HISTORICO = _t(
    "gasoleo_historico_diario",
    "Gasóleo A por província e dia (MITECO).",
    [
        ("data", "date", None),
        ("provincia", "text", "Província em maiúsculas; ESPAÑA = total"),
        ("n_postos", "integer", "Postos com preço de Gasóleo A nesse dia"),
        ("minimo", "numeric", "Gasóleo A, mínimo do dia, €/l"),
        ("media", "numeric", "Gasóleo A, média simples, €/l"),
        ("mediana", "numeric", "Gasóleo A, mediana, €/l"),
        ("maximo", "numeric", "Gasóleo A, máximo, €/l"),
        ("origem", "text", "historico | actual"),
        ("fonte", "text", None),
    ],
)
ROUTES = _t(
    "routes",
    None,
    [
        ("id", "integer", None),
        ("origin", "text", None),
        ("destination", "text", None),
        ("distance_km", "numeric", None),
    ],
)
TRIPS = _t(
    "trips",
    None,
    [
        ("id", "integer", None),
        ("route_id", "integer", None),
        ("fuel_liters", "numeric", None),
        ("cost_eur", "numeric", None),
    ],
)
FESTIVOS = _t(
    "festivos",
    "Feriados nacionais e regionais ES/PT.",
    [
        ("chave", "text", None),
        ("data", "date", None),
        ("pais", "text", "ES | PT"),
        ("nome", "text", "Nome local"),
    ],
)

OPERACIONES = [
    ROUTES,
    TRIPS,
    FESTIVOS,
    GASOLEO_HISTORICO,
    GASOLINERAS_ROTA,
    GASOLINERAS_PRECIO,
]

PERGUNTA_1 = (
    "Lista las 5 gasolineras con el gasóleo A más barato en la tabla "
    "gasolineras_rota para la ruta Badajoz-Madrid"
)
PERGUNTA_2 = (
    "Precio medio diario del gasóleo A en los últimos 30 días según "
    "gasoleo_historico_diario"
)


def _par(rel):
    return {(rel.from_table, rel.from_column), (rel.to_table, rel.to_column)}


# ── 1. A causa: a ligação id_estacion não existia ────────────────────────


def test_a_ligacao_id_estacion_existe_com_as_colunas_reais():
    rels = detect_relationships(OPERACIONES)
    pares = [_par(r) for r in rels]
    assert {
        ("gasolineras_rota", "id_estacion"),
        ("gasolineras_precio", "id_estacion"),
    } in pares


def test_a_ligacao_vem_mesmo_sem_o_comentario_da_coluna():
    """A mesma chave em exactamente duas tabelas chega para a ver."""
    sem_comentarios = [
        TableSchema(
            logical_name=t.logical_name,
            physical_name=t.physical_name,
            columns=[{"name": c["name"]} for c in t.columns],
        )
        for t in OPERACIONES
    ]
    pares = [_par(r) for r in detect_relationships(sem_comentarios)]
    assert {
        ("gasolineras_rota", "id_estacion"),
        ("gasolineras_precio", "id_estacion"),
    } in pares


def test_a_heuristica_antiga_continua_a_ver_route_id():
    pares = [_par(r) for r in detect_relationships(OPERACIONES)]
    assert {("trips", "route_id"), ("routes", "id")} in pares


def test_a_rota_so_nao_tem_preco_e_a_vizinha_tem():
    """A raiz: a tabela que a pessoa nomeia não tem o que ela pede."""
    rota = {c["name"] for c in GASOLINERAS_ROTA.columns}
    assert not any("gasoleo" in c or "precio" in c for c in rota)
    assert {"origem", "destino"} <= rota  # a rota filtra-se por aqui
    rels = detect_relationships(OPERACIONES)
    assert tabelas_vizinhas_que_a_pergunta_pede(
        PERGUNTA_1, ["gasolineras_rota"], OPERACIONES, rels
    ) == ["gasolineras_precio"]


@pytest.mark.parametrize(
    "pergunta",
    [
        "¿Cuántas gasolineras hay en la ruta Badajoz-Madrid?",
        "Gasolineras a menos de 2 km de la ruta Badajoz-Madrid",
    ],
)
def test_sem_nada_que_falte_nao_se_junta_tabela_nenhuma(pergunta):
    rels = detect_relationships(OPERACIONES)
    assert (
        tabelas_vizinhas_que_a_pergunta_pede(
            pergunta, ["gasolineras_rota"], OPERACIONES, rels
        )
        == []
    )


def test_tabela_sem_ligacao_nao_entra_mesmo_que_tenha_a_palavra():
    """`gasoleo_historico_diario` fala de gasóleo mas não está ligada à rota."""
    rels = detect_relationships(OPERACIONES)
    novas = tabelas_vizinhas_que_a_pergunta_pede(
        PERGUNTA_1, ["gasolineras_rota"], OPERACIONES, rels
    )
    assert "gasoleo_historico_diario" not in novas


class _ModeloQueSoNomeiaARota:
    """O pior caso visto: o modelo devolve só a tabela que a pessoa nomeou.
    Sem `_chat` — vai pelo caminho de escolha simples do orquestrador."""

    def __init__(self, resposta):
        self.resposta = resposta

    def invoke(self, mensagens):
        class R:
            content = self.resposta

        return R()


def _orquestrar(pergunta, resposta_do_modelo):
    from core.llm.orchestrator import run_orchestrator

    state = {
        "question": pergunta,
        "chat_history": [],
        "locale": "es",
        "retrieval_context": [],
        "agent_mode": "question",
    }
    cfg = AgentConfig(id="ops", name="Operaciones", tables=list(OPERACIONES))
    return run_orchestrator(state, cfg, _ModeloQueSoNomeiaARota(resposta_do_modelo))


def test_o_orquestrador_entrega_rota_e_precio_com_o_join():
    state = _orquestrar(PERGUNTA_1, "gasolineras_rota")
    assert state.get("answer") in (None, "")
    assert state["chosen_tables"][0] == "gasolineras_rota"
    assert "gasolineras_precio" in state["chosen_tables"]
    assert "ops.gasolineras_precio" in state["chosen_tables_physical"]
    joins = state.get("join_relationships") or []
    assert any(
        {j["from_column"], j["to_column"]} == {"id_estacion"}
        and {j["from_table"], j["to_table"]}
        == {"gasolineras_rota", "gasolineras_precio"}
        for j in joins
    )


def test_o_especialista_ve_o_preco_e_a_rota():
    """O que o especialista recebe já tem com que escrever o SQL: o preço,
    a rota (origem/destino) e a chave para o JOIN."""
    from core.llm.specialist import _build_multiple_schemas_text

    state = _orquestrar(PERGUNTA_1, "gasolineras_rota")
    por_nome = {t.logical_name: t for t in OPERACIONES}
    texto = _build_multiple_schemas_text(
        [por_nome[n] for n in state["chosen_tables"]],
        state.get("join_relationships"),
    )
    assert "precio_gasoleo_a" in texto
    assert "origem" in texto and "destino" in texto
    assert re.search(
        r"gasolineras_\w+\.id_estacion -> gasolineras_\w+\.id_estacion", texto
    )


def test_a_pergunta_2_fica_so_com_o_historico():
    state = _orquestrar(PERGUNTA_2, "gasoleo_historico_diario")
    assert state["chosen_tables"] == ["gasoleo_historico_diario"]


# ── 2a. «€ €» ────────────────────────────────────────────────────────────

_RESULTADOS = [
    [{"precio_medio": 1.8987}],
    [{"media": 1.8987}],
    [{"avg": 1.8987}],
    [{"precio_medio_diario": "1.8987"}],
    [
        {"data": "2026-10-01", "precio_gasoleo_a": 1.9},
        {"data": "2026-10-02", "precio_gasoleo_a": 1.898},
    ],
    [{"precio_medio_eur_l": 1.8987}],
]

_ESCRITAS_COM_EURO = [
    "El precio medio es de 1,90 €.",
    "El precio medio es de 1,90 €.",
    "El precio medio es de 1,90 €.",
    "El precio medio es de 1,90 €.",
    "El precio medio es de 1,90€.",
    "El precio medio es de 1,90 € €.",
    "El precio medio es de 1,90 € €.",
    "El precio medio es de 1,90 EUR €.",
    "El precio medio es de 1,90 € EUR.",
    "El precio medio es de 1,90 euros €.",
    "El precio medio es de € 1,90 €.",
    "El precio medio es de €1,90.",
    "El precio medio es de 1.90 EUR.",
    "Usted puede observar que el precio medio diario del gasóleo A en los "
    "últimos 30 días es de 1,90 €. El mínimo fue de 1,85 € y el máximo "
    "de 1,95 € €.",
]

_DUPLA = re.compile(
    r"€[\s   ]*(?:€|EUR\b|euros?\b)|(?:EUR|euros?)[\s   ]*€", re.IGNORECASE
)


@pytest.mark.parametrize("linhas", _RESULTADOS)
@pytest.mark.parametrize("texto", _ESCRITAS_COM_EURO)
def test_nunca_euro_euro_no_texto_inteiro(texto, linhas):
    saida = corrigir_resposta(texto, "es", linhas)
    assert not _DUPLA.search(saida), saida
    assert saida.count("€") == len(re.findall(r"\d,\d\d", saida)), saida


@pytest.mark.parametrize("linhas", _RESULTADOS)
@pytest.mark.parametrize("texto", _ESCRITAS_COM_EURO)
def test_nunca_euro_euro_em_nenhum_corte_do_streaming(texto, linhas):
    inteiro = corrigir_resposta(texto, "es", linhas)
    for tamanho in range(1, 1001):
        c = CorrecaoEmFluxo("es", linhas)
        saida = ""
        for i in range(0, len(texto), tamanho):
            saida += c.receber(texto[i : i + tamanho])
        saida += c.terminar()
        assert saida == inteiro, (tamanho, saida)
        assert not _DUPLA.search(saida), (tamanho, saida)
        if tamanho >= len(texto):
            break


def test_o_caso_de_producao():
    assert (
        corrigir_resposta(
            "Usted puede observar que el precio medio diario del gasóleo A en "
            "los últimos 30 días es de 1,90 €.",
            "es",
            [{"precio_medio": 1.8987}],
        )
        == "El precio medio diario del gasóleo A en los últimos 30 días es de 1,90 €."
    )


@pytest.mark.parametrize(
    "lingua,texto,esperado",
    [
        ("pt", "O preço médio é 1,90 € €.", "O preço médio é 1,90 €."),
        ("en", "The average price is €€1.90.", "The average price is €1.90."),
        ("en", "The average price is 1.90 € €.", "The average price is €1.90."),
    ],
)
def test_nunca_euro_euro_em_pt_e_en(lingua, texto, esperado):
    assert corrigir_resposta(texto, lingua, [{"price": 1.9}]) == esperado


# ── €/l só quando a coluna o diz ─────────────────────────────────────────


@pytest.mark.parametrize(
    "coluna,por_litro",
    [
        ("precio_medio_eur_l", True),
        ("gasoleo_eur_l", True),
        ("precio_litro", True),
        ("media", False),
        ("precio_gasoleo_a", False),
        ("fuel_liters", False),  # quantidade, não preço
        ("cost_eur", False),
    ],
)
def test_preco_por_litro_decide_se_pelo_nome(coluna, por_litro):
    assert e_preco_por_litro(coluna) is por_litro


@pytest.mark.parametrize(
    "linhas,texto,esperado",
    [
        ([{"precio_medio_eur_l": 1.8987}], "Fue de 1,90 €.", "Fue de 1,90 €/l."),
        ([{"precio_medio_eur_l": 1.8987}], "Fue de 1,90.", "Fue de 1,90 €/l."),
        ([{"precio_medio_eur_l": 1.8987}], "Fue de 1,90 €/l.", "Fue de 1,90 €/l."),
        (
            [{"precio_medio_eur_l": 1.8987}],
            "Fue de 1,90 € por litro.",
            "Fue de 1,90 € por litro.",
        ),
        ([{"media": 1.8987}], "Fue de 1,90 €.", "Fue de 1,90 €."),
        ([{"precio_medio": 1.8987}], "Fue de 1,90 €.", "Fue de 1,90 €."),
    ],
)
def test_euro_por_litro(linhas, texto, esperado):
    assert corrigir_resposta(texto, "es", linhas) == esperado
    for tamanho in range(1, len(texto) + 1):
        c = CorrecaoEmFluxo("es", linhas)
        saida = "".join(
            c.receber(texto[i : i + tamanho]) for i in range(0, len(texto), tamanho)
        )
        saida += c.terminar()
        assert saida == esperado, (tamanho, saida)


# ── 2b. O anúncio antes do facto ─────────────────────────────────────────


@pytest.mark.parametrize(
    "texto,esperado",
    [
        (
            "Usted puede observar que el precio medio fue de 1,90 €.",
            "El precio medio fue de 1,90 €.",
        ),
        ("Puede observar que el total es 12.", "El total es 12."),
        ("Puede ver que hubo 12 viajes.", "Hubo 12 viajes."),
        ("Como puede ver, hubo 12 viajes.", "Hubo 12 viajes."),
        ("Se puede observar que hubo 12 viajes.", "Hubo 12 viajes."),
        (
            "Hubo 12 viajes. Usted puede ver que 3 fueron a Madrid.",
            "Hubo 12 viajes. 3 fueron a Madrid.",
        ),
        ("Pode observar que o preço médio foi 1,90 €.", "O preço médio foi 1,90 €."),
        ("Você pode ver que houve 12 viagens.", "Houve 12 viagens."),
        ("É possível observar que houve 12 viagens.", "Houve 12 viagens."),
        (
            "You can see that the average price was €1.90.",
            "The average price was €1.90.",
        ),
        ("As you can see, there were 12 trips.", "There were 12 trips."),
        ("We can see that there were 12 trips.", "There were 12 trips."),
    ],
)
def test_sem_anuncio(texto, esperado):
    assert sem_anuncio(texto) == esperado


@pytest.mark.parametrize(
    "texto",
    [
        # No meio da frase não se toca: é conteúdo, não anúncio.
        "El informe dice que usted puede ver que hubo 12 viajes.",
        "Se puede reservar online.",
        "You can see the details in the table below.",
    ],
)
def test_o_anuncio_so_se_corta_no_inicio_da_frase(texto):
    assert sem_anuncio(texto) == texto


@pytest.mark.parametrize(
    "lingua,texto,esperado",
    [
        (
            "es",
            "Usted puede observar que el precio medio diario del gasóleo A en los "
            "últimos 30 días es de 1,90 € €.",
            "El precio medio diario del gasóleo A en los últimos 30 días es de 1,90 €.",
        ),
        (
            "pt",
            "Pode observar que o preço médio diário do gasóleo nos últimos 30 dias "
            "foi de 1,90 €.",
            "O preço médio diário do gasóleo nos últimos 30 dias foi de 1,90 €.",
        ),
        (
            "en",
            "You can see that the average daily diesel price over the last 30 days "
            "was €1.90.",
            "The average daily diesel price over the last 30 days was €1.90.",
        ),
    ],
)
def test_o_anuncio_sai_tambem_no_streaming(lingua, texto, esperado):
    linhas = [{"precio_medio": 1.8987}]
    assert corrigir_resposta(texto, lingua, linhas) == esperado
    for tamanho in range(1, len(texto) + 1):
        c = CorrecaoEmFluxo(lingua, linhas)
        saida = "".join(
            c.receber(texto[i : i + tamanho]) for i in range(0, len(texto), tamanho)
        )
        saida += c.terminar()
        assert saida == esperado, (tamanho, saida)
