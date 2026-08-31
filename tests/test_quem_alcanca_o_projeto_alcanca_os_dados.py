# -*- coding: utf-8 -*-
"""Quem alcança o projeto alcança os dados dele — e a Sky di-lo quando não.

> *"Se tem acesso ao projeto, tem acesso aos dados. Ainda não implementaremos
> o RBAC que controla o que as pessoas dentro daquele projeto podem ver."*
> — Lucas, 27/08/2026

---

**O que custou uma demonstração.**

O Lucas criou um projeto para um cliente, ligou-lhe cinco fontes, e perguntou
«qual o cliente com maior faturação?». A Sky respondeu **«Ainda não há dados
ligados aqui»** — com as cinco ligações à vista no ecrã ao lado.

Duas causas somadas:

1. **O filtro por equipa.** As tabelas eram filtradas por
   `crew_id IS NULL OR crew_id IN (as minhas equipas)`. Bastava a descoberta
   escrever um `crew_id` numa linha para essa tabela desaparecer de quem não
   estivesse nessa equipa exacta. O acesso ao projeto já tinha sido decidido
   antes; este segundo filtro só podia estreitar o que já estava certo.

2. **A mensagem mentia.** Sem tabelas, o servidor respondia «No tables are
   configured for this agent.» — inglês cravado, jargão nosso, e falso no
   caso mais comum: a leitura dos metadados corre em segundo plano e ainda
   não tinha acabado.

A app do telemóvel completava o estrago: qualquer resposta vazia virava «não
há dados ligados». Três camadas a adivinhar, e todas a adivinhar mal.

---

**O que estes testes fixam:** que os dados de um projeto chegam a quem o
alcança, e que as duas situações sem tabelas dizem coisas diferentes —
porque uma pede um minuto de espera e a outra pede que se ligue uma fonte.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from core.i18n.i18n import MESSAGES, SUPPORTED_LANGUAGES, get_message

RAIZ = pathlib.Path(__file__).resolve().parents[1]


def _fonte(rel: str) -> str:
    return (RAIZ / rel).read_text(encoding="utf-8")


class TestSemFiltroPorEquipa:
    def test_a_consulta_das_tabelas_nao_filtra_por_equipa(self):
        """O filtro que fazia as tabelas desaparecerem."""
        fonte = _fonte("core/agents/factory.py")
        # O `crew_id` pode continuar a ser mencionado nos comentários que
        # explicam a decisão — o que não pode é voltar a filtrar.
        linhas_de_codigo = [
            l for l in fonte.splitlines() if not l.lstrip().startswith("#")
        ]
        codigo = "\n".join(linhas_de_codigo)
        assert "TableMetadata.crew_id" not in codigo

    def test_o_projeto_continua_a_delimitar(self):
        """Tirar o filtro da equipa não pode abrir os dados de outro projeto.

        É a distinção que interessa: o projeto é a fronteira, a equipa não.
        Se este `space_id` desaparecesse, uma pergunta num projeto passava a
        ver as tabelas de todos.
        """
        fonte = _fonte("core/agents/factory.py")
        assert "TableMetadata.space_id.in_(effective_space_ids)" in fonte


class TestAsDuasCausasDizemCoisasDiferentes:
    def test_as_duas_mensagens_existem_nas_tres_linguas(self):
        for chave in ("STILL_READING_SOURCES", "NO_SOURCES_CONNECTED"):
            assert chave in MESSAGES, f"{chave} não está no catálogo"
            assert SUPPORTED_LANGUAGES <= set(MESSAGES[chave])

    def test_e_nao_sao_a_mesma_frase(self):
        """Se fossem iguais, a distinção existia no código e não no ecrã."""
        for lang in SUPPORTED_LANGUAGES:
            a = get_message("STILL_READING_SOURCES", lang)
            b = get_message("NO_SOURCES_CONNECTED", lang)
            assert a != b

    def test_uma_manda_esperar_e_a_outra_manda_ligar(self):
        """O passo seguinte tem de estar na frase, não na cabeça de quem lê."""
        esperar = get_message("STILL_READING_SOURCES", "pt").lower()
        ligar = get_message("NO_SOURCES_CONNECTED", "pt").lower()
        assert "outra vez" in esperar or "daqui" in esperar
        assert "ligue" in ligar

    def test_o_ingles_cravado_desapareceu(self):
        fonte = _fonte("core/llm/orchestrator.py")
        codigo = "\n".join(
            l for l in fonte.splitlines() if not l.lstrip().startswith("#")
        )
        assert "No tables are configured for this agent." not in codigo
        assert 'get_message("STILL_READING_SOURCES"' in codigo or "STILL_READING_SOURCES" in codigo

    def test_a_escolha_olha_para_as_ligacoes_do_projeto(self):
        """A distinção tem de vir de um facto, não de um palpite."""
        fonte = _fonte("core/llm/orchestrator.py")
        assert "_projeto_tem_ligacoes" in fonte
        assert "SpaceConnection" in fonte


class TestEmDuvidaNaoMandaEsperar:
    def test_sem_projeto_assume_que_nao_ha_ligacoes(self):
        """Mandar esperar por uma leitura que não acontece deixa a pessoa
        parada; mandar ligar uma fonte que já existe vê-se logo e corrige-se."""
        from core.llm.orchestrator import _projeto_tem_ligacoes

        assert _projeto_tem_ligacoes(None, None) is False
        assert _projeto_tem_ligacoes(None, "") is False

    def test_uma_base_que_rebenta_tambem_nao(self):
        class _DbMau:
            def query(self, *_a, **_k):
                raise RuntimeError("base em baixo")

        from core.llm.orchestrator import _projeto_tem_ligacoes

        assert _projeto_tem_ligacoes(_DbMau(), "algum-id") is False


class TestOTelemovelDeixouDeAdivinhar:
    """A terceira camada a adivinhar. Vive noutro repositório, e por isso só
    se verifica aqui que a responsabilidade mudou de lado — o guarda do lado
    dele está em `chat-sem-resposta.test.ts`."""

    def test_o_servidor_responde_sempre_alguma_coisa_sem_tabelas(self):
        fonte = _fonte("core/llm/orchestrator.py")
        i = fonte.index("if not agent_config.tables:")
        bloco = fonte[i : i + 700]
        # Devolver `state` sem `answer` deixava o fluxo vazio, e era isso que
        # a app interpretava como «não há dados».
        assert 'state["answer"] = get_message(' in bloco
