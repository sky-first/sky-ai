"""A Sky sabe que dia é hoje.

> «pergunto que dia é hoje. E ele não tem essa informação» — Lucas, 10/10/2026
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from core.llm.conversa_specialist import agora_para, run_conversa_specialist


class _LLM:
    def __init__(self):
        self.visto = None

    def invoke(self, mensagens):
        self.visto = mensagens

        class R:
            content = "Hoy es sábado."

        return R()


def test_a_instrucao_leva_a_data_de_hoje():
    llm = _LLM()
    run_conversa_specialist({"question": "¿Qué día es hoy?", "language": "es"}, llm)
    sistema = llm.visto[0]["content"]
    hoje = datetime.now(ZoneInfo("Europe/Madrid")).strftime("%Y-%m-%d")
    assert hoje in sistema
    assert "you DO know these" in sistema


def test_o_fuso_do_pedido_manda():
    assert "Atlantic/Canary" in agora_para("es", "Atlantic/Canary")


def test_um_fuso_invalido_cai_em_utc():
    assert "(UTC)" in agora_para("es", "Lua/Base")
