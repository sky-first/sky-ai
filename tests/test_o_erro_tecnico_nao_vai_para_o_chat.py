# -*- coding: utf-8 -*-
"""O erro técnico vai para os registos, não para a cara de quem pergunta.

> *"DEBUG? 404? que isso na mensagem?"* — Lucas, com uma captura do
> telemóvel

O que ele viu:

    Algo correu mal do nosso lado ao responder a esta pergunta — não é
    problema dos seus dados nem do seu acesso. O erro ficou registado.
    Tente de novo e avise um administrador se continuar.
    | DEBUG:  (status code: 404)

A frase diz «o erro ficou registado» e logo a seguir despeja-o na mesma.

Havia quatro sítios a colar `| DEBUG: {erro}` na resposta, e **dois deles
juntavam-lhe o traceback inteiro** (`f"\nTRACEBACK: {tb[-2000:]}"`). Um
traceback num balão de chat não é só ruído: mostra caminhos de ficheiros e
nomes internos a quem não tem nada com isso.

Um código de estado também não ajuda ninguém — não diz o que fazer, e dá a
uma avaria nossa o ar de uma coisa que a pessoa devia perceber.
"""
from __future__ import annotations

import inspect

from api.routes import connection_query as m


def _codigo() -> str:
    """A fonte sem os comentários e docstrings que citam o defeito."""
    return "\n".join(
        l for l in inspect.getsource(m).splitlines() if "get_message(" in l
    )


class TestNadaTecnicoNaMensagem:
    def test_o_debug_desapareceu_do_codigo(self):
        assert "| DEBUG:" not in _codigo()

    def test_e_o_traceback_tambem(self):
        assert "TRACEBACK: " not in _codigo()

    def test_ha_um_caminho_so_para_o_erro_tecnico(self):
        """Quatro sítios a montar a mesma frase divergem à primeira mudança —
        e foi assim que dois ganharam traceback e dois não."""
        assert hasattr(m, "_erro_para_quem_pergunta")

    def test_a_mensagem_e_so_a_frase_amigavel(self):
        from core.i18n.i18n import get_message

        for lang in ("pt", "en", "es"):
            devolvido = m._erro_para_quem_pergunta(lang, "status 404", "tb")
            assert devolvido == get_message("TECHNICAL_ERROR", lang)
            assert "404" not in devolvido
            assert "DEBUG" not in devolvido

    def test_sem_detalhe_tambem_responde(self):
        """Nem sempre há erro para registar; a frase não pode depender disso."""
        assert m._erro_para_quem_pergunta("pt") != ""
