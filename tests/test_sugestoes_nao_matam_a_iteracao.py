# -*- coding: utf-8 -*-
"""Um ecrã vazio deixa de ser um beco.

> *"na conexao que fazemos, já gerarmos ali algumas perguntas e respostas...
> ou até mesmo na tela de descobertas apresentarmos um: olha nao encontramos
> isso, mas essas outras opcoes parecem também ser interessantes, quer saber
> mais sobre 1 2 3 (opcoes como botões) assim nao matamos a iteração, mas
> claro isso precisa ser por projeto"*
> — Lucas, 31/08/2026

---

**O motor já existia. Estava desligado há seis meses.**

`DISABLE_BOOTSTRAP_EXECUTION = True  # PAUSADO A PEDIDO DO CLIENTE (Step
547)`, escrito a 05/02/2026 dentro de um PR sobre a lógica dos dashboards.
Ninguém voltou lá. O `/chat/bootstrap` respondia «Bootstrap is paused
(Maintenance Mode)» com zero sugestões, e a web caía nas duas frases de
reserva mais genéricas que há.

Passa a ser uma variável de ambiente, ligada por omissão. Uma pausa
operacional — custo, latência, um modelo em baixo — resolve-se sem tocar no
código nem esperar por uma imagem nova, que foi exactamente o que fez esta
ficar seis meses ligada ao contrário.

**E a lista de reserva falava sempre inglês.** O `lang` chegava à função e
era ignorado: com `language=pt` saíam «Monthly performance», «Top results»,
«Time-based analysis». É a lista que aparece mais vezes, não menos — serve
qualquer projeto acabado de ligar, ou seja, o primeiro ecrã de quem chega.
"""
from __future__ import annotations

import os
import importlib

import pytest


def _modulo():
    import api.routes.connection_query as m

    return importlib.reload(m)


class TestOInterruptorDeixouDeEstarCravado:
    def test_por_omissao_as_sugestoes_estao_ligadas(self, monkeypatch):
        monkeypatch.delenv("DISABLE_BOOTSTRAP_EXECUTION", raising=False)
        assert _modulo().DISABLE_BOOTSTRAP_EXECUTION is False

    @pytest.mark.parametrize("valor", ["1", "true", "TRUE", "yes", "on"])
    def test_e_pode_desligar_se_preciso(self, monkeypatch, valor):
        monkeypatch.setenv("DISABLE_BOOTSTRAP_EXECUTION", valor)
        assert _modulo().DISABLE_BOOTSTRAP_EXECUTION is True

    def test_um_valor_qualquer_nao_desliga(self, monkeypatch):
        """Uma variável mal escrita não pode apagar a funcionalidade em
        silêncio — foi assim que esta esteve desligada sem ninguém saber."""
        monkeypatch.setenv("DISABLE_BOOTSTRAP_EXECUTION", "talvez")
        assert _modulo().DISABLE_BOOTSTRAP_EXECUTION is False


class TestAReservaFalaALinguaDeQuemPergunta:
    def _sugestoes(self, lang: str):
        m = _modulo()
        return m._fallback_bootstrap(lang, 3)

    def test_portugues(self):
        r = self._sugestoes("pt")
        assert "ajudá-lo" in r.greeting
        assert all("?" in (s.question or "") for s in r.suggestions)
        assert not any("performance" in s.title.lower() for s in r.suggestions)

    def test_espanhol(self):
        r = self._sugestoes("es")
        assert r.greeting.startswith("¿")

    def test_ingles_continua_a_ser_o_que_era(self):
        r = self._sugestoes("en")
        assert r.greeting == "How can I help you with your data?"

    def test_uma_lingua_desconhecida_cai_no_ingles(self):
        assert self._sugestoes("de").greeting == "How can I help you with your data?"

    def test_devolve_o_numero_pedido(self):
        assert len(_modulo()._fallback_bootstrap("pt", 3).suggestions) == 3

    def test_cada_pergunta_e_uma_frase_inteira(self):
        """**«Os maiores» — os maiores quê?**

        O rótulo dos botões passou a ser a PERGUNTA e não o título, porque
        os títulos são etiquetas de categoria e liam-se como fragmentos —
        o Lucas apanhou-o numa captura, com a frase a morrer a meio.

        Uma pergunta que não se percebe sozinha não serve de convite: quem
        lê não sabe o que vai acontecer se tocar.
        """
        for lang in ("pt", "en", "es"):
            for sg in _modulo()._fallback_bootstrap(lang, 4).suggestions:
                pergunta = sg.question or ""
                assert pergunta.endswith("?"), (lang, pergunta)
                # Uma frase de três palavras é um fragmento, nao uma pergunta.
                assert len(pergunta.split()) >= 6, (lang, pergunta)

    def test_e_o_enchimento_tambem_e_traduzido(self):
        """Pedir mais do que a lista tem enchia com um «Example» inglês."""
        r = _modulo()._fallback_bootstrap("pt", 6)
        assert len(r.suggestions) == 6
        assert not any(s.title == "Example" for s in r.suggestions)
