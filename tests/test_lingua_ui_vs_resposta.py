"""Duas línguas, não uma — regra do Lucas, 12/10/2026.

1. A língua da APP («Idioma») manda em todo o texto de interface, incluindo
   as frases de estado do stream («A analisar a pergunta…»).
2. «Sky responde en» manda na língua da RESPOSTA: «Sigue su pregunta»
   (sem `locale`) detecta a língua da pergunta; uma escolha explícita força.

Defeitos apanhados em produção (Android, app em castelhano):
  A. «Analisando pergunta…» em português do Brasil, cravado no stream.
  B. Com «Sigue su pregunta», «cuál ha sido mi facturación» respondida em
     português: o histórico do stream é por utilizador+ligação e a primeira
     pergunta dele era portuguesa — a língua da conversa ganhava à pergunta.
"""

import json

import pytest

from core.i18n.i18n import (
    PROGRESS_KEYS,
    _lingua_pelas_marcas,
    deteccao_confiante,
    language_decision,
    progress_event,
    resolve_language,
    thread_language_from_history,
)

PERGUNTA = "cuál ha sido mi facturación"

HISTORICO_PT = [
    {"role": "user", "content": "quais foram as vendas do mês passado?"},
    {"role": "assistant", "content": "As vendas foram 1,2 milhões."},
]


class TestSigueSuPregunta:
    def test_a_pergunta_exacta_e_espanhol_sem_conversa(self):
        assert resolve_language(PERGUNTA) == "es"
        assert language_decision(PERGUNTA) == (False, "es")

    def test_a_pergunta_exacta_ganha_a_uma_conversa_portuguesa(self):
        """O defeito B: a conversa era PT e a pergunta é ES → ES."""
        lingua_da_conversa = thread_language_from_history(HISTORICO_PT)
        assert lingua_da_conversa == "pt"
        assert resolve_language(PERGUNTA, thread_language=lingua_da_conversa) == "es"
        assert language_decision(PERGUNTA, thread_language=lingua_da_conversa) == (
            False,
            "es",
        )

    @pytest.mark.parametrize(
        "pergunta",
        [
            "cual ha sido mi facturacion",  # sem acentos
            "¿cuál ha sido mi facturación?",
            "ventas de este mes",  # curta: o detector sozinho dava PT
            "y el mes pasado?",
            "cuántos clientes tengo",
        ],
    )
    def test_espanhol_curto_ou_sem_acentos_numa_conversa_pt(self, pergunta):
        assert resolve_language(pergunta, thread_language="pt") == "es"

    def test_seguimento_curto_continua_a_seguir_a_conversa(self):
        assert resolve_language("sim", thread_language="pt") == "pt"
        assert resolve_language("ok", thread_language="en") == "en"
        assert deteccao_confiante("sim") is None

    def test_pergunta_inglesa_numa_conversa_pt_responde_em_ingles(self):
        assert (
            resolve_language("what was my revenue last month?", thread_language="pt")
            == "en"
        )

    def test_portugues_com_jargao_nunca_vira_espanhol(self):
        q = "qual o win rate do time de sales no último quarter?"
        assert resolve_language(q) == "pt"
        assert resolve_language(q, thread_language="pt") == "pt"

    def test_lingua_que_nao_falamos_continua_bloqueada_sem_conversa(self):
        blocked, _ = language_decision(
            "quel a été le chiffre d'affaires du mois dernier en France?"
        )
        assert blocked is True

    def test_lingua_que_nao_falamos_numa_conversa_nao_e_bloqueada(self):
        assert language_decision(
            "quel a été le chiffre d'affaires?", thread_language="en"
        ) == (False, "en")


class TestEscolhaExplicita:
    def test_portugues_forca_portugues(self):
        assert resolve_language(PERGUNTA, locale="pt") == "pt"
        assert language_decision(PERGUNTA, locale="pt") == (False, "pt")

    def test_ingles_forca_ingles(self):
        assert resolve_language(PERGUNTA, locale="en", thread_language="pt") == "en"


class TestMarcas:
    """Sem o `lingua` instalado, as marcas são o que separa ES de PT."""

    @pytest.mark.parametrize(
        "texto,esperado",
        [
            (PERGUNTA, "es"),
            ("cual ha sido mi facturacion", "es"),
            ("¿cuánto vendimos?", "es"),
            ("qual foi a minha faturação", "pt"),
            ("quantos clientes não compraram", "pt"),
            ("what was my revenue", None),
        ],
    )
    def test_marcas(self, texto, esperado):
        assert _lingua_pelas_marcas(texto) == esperado


class TestProgressoNaLinguaDaApp:
    def test_cada_etapa_tem_chave(self):
        for etapa, chave in PROGRESS_KEYS.items():
            ev = progress_event(etapa, "es")
            assert ev["type"] == "progress"
            assert ev["stage"] == etapa
            assert ev["key"] == chave
            assert ev["message"]

    def test_app_em_espanhol_recebe_espanhol(self):
        assert (
            progress_event("orchestrator", "es")["message"] == "Analizando la pregunta…"
        )

    def test_app_em_portugues_recebe_portugues_de_portugal(self):
        msg = progress_event("orchestrator", "pt-PT")["message"]
        assert msg == "A analisar a pergunta…"

    def test_sem_lingua_da_app_sai_em_ingles_e_nunca_pt_br(self):
        for etapa in PROGRESS_KEYS:
            msg = progress_event(etapa)["message"]
            assert "Analisando" not in msg and "Gerando" not in msg
            assert "Executando" not in msg

    def test_serializa_para_o_stream(self):
        json.dumps(progress_event("specialist", "es"))

    def test_nenhuma_frase_cravada_nas_rotas(self):
        import pathlib

        raiz = pathlib.Path(__file__).resolve().parents[1]
        for rota in ("api/routes/connection_query.py", "api/routes/agents.py"):
            texto = (raiz / rota).read_text(encoding="utf-8")
            for frase in (
                "Analisando pergunta",
                "Executando query",
                "Gerando resposta",
            ):
                assert frase not in texto, f"{frase!r} cravado em {rota}"

    def test_o_pedido_aceita_ui_locale(self):
        from api.schemas import QueryRequest

        body = QueryRequest(question="x", ui_locale="es")
        assert body.ui_locale == "es"
        assert QueryRequest(question="x").ui_locale is None
