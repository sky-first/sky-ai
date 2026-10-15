"""Palavra-chave do detector de dados pessoais é palavra inteira (14/10/2026).

Produção, projecto «Alimentación Selecta y Vinos»: «¿Qué referencias no han
tenido ni una sola venta?» → «No puedo mostrar este resultado porque contiene
datos personales sensibles». Eram vinhos: «Vino **tin**to» casava com o padrão
do número fiscal (`\\b(tin|…)` sem fronteira à direita) e «**nin**guna» com o
National Insurance Number.

Os dois lados ficam presos aqui: respostas de negócio passam; documentos,
emails, telefones e contas continuam a ser apanhados.
"""

import pytest

from core.security.pii_scanner import scan_answer_for_pii, scan_text_for_pii

RESPOSTAS_DE_NEGOCIO = [
    # as do defeito
    "Hay 4 referencias sin ventas: Vino tinto Reserva 12 (REF-0012), Queso "
    "Artesano 40 (REF-0040), Aceite Origen 23 (REF-0023) y Cava Tradicional 39.",
    "Las referencias que no han tenido ninguna venta son:\n\n- **Cava Reserva "
    "15** (SKU REF-0015)\n- **Aceite Artesano 16** (SKU REF-0016)",
    "1. Vino tinto Gran Selección 18 — 12,50 €",
    # as mesmas sílabas noutras palavras
    "Ninguno de los productos de la familia Vino tinto bajó de 200 unidades.",
    "O tinteiro e a tinta 4 vendem mais em Abril.",
    "Las tiendas de Badajoz abarcan 3 rutas; el abastecimiento llega a 120 kg.",
    "El autor del pedido 5512 es el canal tienda.",
    "El DNI de cada empleado está en la tabla de personal.",
]


@pytest.mark.parametrize("texto", RESPOSTAS_DE_NEGOCIO)
def test_respostas_de_negocio_nao_sao_bloqueadas(texto):
    r = scan_text_for_pii(texto)
    assert not r.should_block, (texto, r.pii_types, r.patterns_matched)


DADOS_PESSOAIS = [
    "TIN: 123-45-678",
    "Tax ID 98765432",
    "NIN: AB 12 34 56 C",
    "DNI: 12345678Z",
    "dni 12345678Z",
    "Pasaporte número A1234567",
    "IBAN: ES91 2100 0418 4502 0005 1332",
    "Tarjeta: 4111 1111 1111 1111",
    "CPF: 123.456.789-00",
    "contraseña: hunter2025",
    "Juan Pérez juan.perez@example.com",
    "María López +34 612 345 678",
]


@pytest.mark.parametrize("texto", DADOS_PESSOAIS)
def test_dados_pessoais_continuam_bloqueados(texto):
    assert scan_text_for_pii(texto).should_block, texto


def test_email_e_telefone_continuam_detectados():
    assert scan_text_for_pii("escreva para ana@empresa.pt").detected
    assert scan_text_for_pii("telefone: 912 345 678").detected


def test_resposta_completa_do_defeito_passa_com_os_dados():
    data = [
        {"sku": "REF-0012", "name": "Vino tinto Reserva 12", "family": "Vino tinto"},
        {"sku": "REF-0040", "name": "Queso Artesano 40", "family": "Queso"},
    ]
    resposta = (
        "Hay 2 referencias sin ninguna venta: **Vino tinto Reserva 12** "
        "(REF-0012) y **Queso Artesano 40** (REF-0040)."
    )
    assert not scan_answer_for_pii(resposta, data).should_block
