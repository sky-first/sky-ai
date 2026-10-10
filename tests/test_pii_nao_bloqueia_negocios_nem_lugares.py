"""O guarda de PII recusava a lista de gasolineiras como «dados pessoais».

Produção, 10/10/2026, `locale=es`:

    «Lista las 5 gasolineras con el gasóleo A más barato en la tabla
     gasolineras_rota para la ruta Badajoz-Madrid»
    → «I cannot display sensitive personal information in the results.»

Duas coisas erradas: a recusa era falsa, e vinha em inglês.

Porque era falsa — três padrões a disparar sobre dados públicos (MITECO):

* o BIC sem contexto era «qualquer palavra de 8 ou 11 maiúsculas» e era
  BLOCK: ESTACION, SERVICIO, EXTREMADURA;
* «Nome + valor monetário» tinha ``re.IGNORECASE`` e ``.*``: duas palavras
  quaisquer e um € em qualquer ponto da frase — «El precio medio fue 1,45 €»
  era um salário vazado;
* o rótulo e o município de um posto colados a um preço («Plenoil Mérida
  1,399 €») têm a forma de «Nome Apelido 1,399 €».

Estes testes fixam o COMPORTAMENTO dos dois lados: o que não é de pessoas
passa, e o que é de pessoas continua a ser travado.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.security.pii_scanner import (
    scan_answer_for_pii,
    scan_data_for_pii,
    scan_text_for_pii,
)

# Como o MITECO publica: maiúsculas, moradas de estrada, coordenadas.
GASOLINERAS = [
    {
        "rotulo": "PETRONOR",
        "direccion": "CARRETERA N-V KM 345",
        "cp": "06800",
        "localidad": "MERIDA",
        "municipio": "Mérida",
        "provincia": "BADAJOZ",
        "lat": 38.9161,
        "lon": -6.3437,
        "carretera": "N-V",
        "precio_gasoleo_a": 1.399,
    },
    {
        "rotulo": "ESTACION DE SERVICIO EXTREMADURA",
        "direccion": "AVENIDA DE EXTREMADURA 12",
        "cp": "06200",
        "localidad": "ALMENDRALEJO",
        "municipio": "Almendralejo",
        "provincia": "BADAJOZ",
        "lat": 38.6833,
        "lon": -6.4072,
        "carretera": "A-66",
        "precio_gasoleo_a": 1.419,
    },
    {
        "rotulo": "Plenoil Mérida",
        "direccion": "CALLE RONDA DEL SUR 4",
        "cp": "06800",
        "localidad": "MERIDA",
        "municipio": "Mérida",
        "provincia": "BADAJOZ",
        "lat": 38.90,
        "lon": -6.33,
        "carretera": None,
        "precio_gasoleo_a": 1.389,
    },
]

RESPOSTA = (
    "Las 3 gasolineras más baratas de gasóleo A en la ruta Badajoz–Madrid son:\n"
    "1. Plenoil Mérida 1,389 € — CALLE RONDA DEL SUR 4, Mérida (BADAJOZ)\n"
    "2. PETRONOR 1,399 € — CARRETERA N-V KM 345, Mérida\n"
    "3. ESTACION DE SERVICIO EXTREMADURA 1,419 € — AVENIDA DE EXTREMADURA 12, "
    "Almendralejo"
)


# ── O que não é de pessoas passa ──────────────────────────────────────


def test_dados_de_gasolineiras_nao_sao_dados_pessoais():
    assert not scan_data_for_pii(GASOLINERAS).should_block


def test_a_resposta_que_cita_as_gasolineiras_nao_e_recusada():
    assert not scan_answer_for_pii(RESPOSTA, GASOLINERAS).should_block


@pytest.mark.parametrize(
    "texto",
    [
        "El precio medio diario del gasóleo A fue 1,45 €.",
        "La facturación total de marzo fue de 12.300 €.",
        "O preço médio em Badajoz foi 1,452 €/l.",
        "ESTACION DE SERVICIO REPSOL, CARRETERA N-V KM 345, MERIDA (BADAJOZ)",
        "AVENIDA DE EXTREMADURA 12",
        "Hay 4 incidencias activas en la A-5 entre el km 340 y el 360.",
    ],
)
def test_texto_de_negocio_com_euros_ou_maiusculas_nao_e_travado(texto):
    assert not scan_text_for_pii(texto).should_block


# ── O que é de pessoas continua travado ───────────────────────────────


@pytest.mark.parametrize(
    "texto",
    [
        "John Doe - $50,000",
        "Maria Silva: R$ 5.000,00",
        "Maria Silva: 5.000,00 €",
        "John Smith 12 Calle Mayor",
        "CPF: 123.456.789-00",
        "BIC: BBPIPTPL",
        "IBAN PT50 0002 0123 1234 5678 9015 4",
        "Cartão 4111 1111 1111 1111",
    ],
)
def test_dados_pessoais_continuam_a_ser_travados(texto):
    assert scan_text_for_pii(texto).should_block


def test_nome_de_pessoa_ao_lado_de_valor_continua_travado_mesmo_com_dados():
    """Só se tiram do texto valores de colunas de negócio/lugar. O nome de um
    cliente numa coluna `cliente` continua a ser analisado."""
    dados = [{"cliente": "Maria Silva", "municipio": "Mérida", "saldo": 5000}]
    assert scan_answer_for_pii("Maria Silva: 5.000,00 € (Mérida)", dados).should_block


def test_coluna_de_pessoa_com_dados_pessoais_continua_travada():
    dados = [{"nome": "Ana Costa", "iban": "PT50000201231234567890154"}]
    assert scan_data_for_pii(dados).should_block


def test_morada_de_cliente_nao_e_tratada_como_lugar_publico():
    """A morada fica de fora da isenção: numa tabela de clientes é pessoal.
    Um CPF metido na morada continua a ser apanhado."""
    dados = [{"direccion": "Rua A 1, CPF 123.456.789-00"}]
    assert scan_data_for_pii(dados).should_block


# ── A recusa vem na língua do pedido ──────────────────────────────────


@pytest.mark.parametrize("locale", ["es", "pt", "en"])
def test_a_recusa_de_pii_vem_na_lingua_do_pedido(locale):
    from api.routes.connection_query import _lingua_da_recusa
    from core.i18n.i18n import get_message

    pedido = SimpleNamespace(
        question="Lista las 5 gasolineras con el gasóleo A más barato",
        locale=locale,
    )
    assert _lingua_da_recusa(pedido) == locale
    for chave in ("PII_RESPONSE_BLOCKED", "PII_BLOCKED", "SECURITY_BLOCKED"):
        assert get_message(chave, _lingua_da_recusa(pedido)) == get_message(
            chave, locale
        )


def test_as_recusas_em_espanhol_e_portugues_nao_sao_o_ingles():
    from core.i18n.i18n import get_message

    for chave in ("PII_RESPONSE_BLOCKED", "PII_BLOCKED", "SECURITY_BLOCKED"):
        en = get_message(chave, "en")
        assert get_message(chave, "es") != en
        assert get_message(chave, "pt") != en
    assert "datos personales" in get_message("PII_RESPONSE_BLOCKED", "es")
