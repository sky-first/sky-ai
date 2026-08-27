# -*- coding: utf-8 -*-
"""O espanhol tem resposta própria — não cai no inglês.

---

**O que acontecia.** Quinze sítios escreviam a mensagem assim::

    if lang == "pt":
        state["answer"] = "Não encontrei tabelas..."
    else:
        state["answer"] = "I couldn't find any relevant tables..."

Quem usa a Sky em espanhol tinha a interface em espanhol e as respostas da
IA em inglês.

A ironia é que o `core/llm/lingua_da_resposta.py` avisa exactamente disto no
seu cabeçalho — *"pôr espanhol na app sem o pôr aqui dá interface em
espanhol e respostas em inglês, que é pior do que não ter espanhol porque
parece que funciona até se ler a resposta"*. A **regra** foi centralizada; as
**frases** ficaram espalhadas. Aconteceu à mesma.

O caso mais grave era o aviso de período: a frase que impede alguém de ler
números de Março a pensar que são de Maio, entregue em inglês a quem
trabalha em espanhol.

---

**O que se fixa aqui** é a regra, não as frases: toda a mensagem que a IA
mostra vive no catálogo, tem as três línguas, e nenhuma delas é a inglesa
por copiar.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from core.i18n.i18n import MESSAGES, SUPPORTED_LANGUAGES, get_message


def _fonte(rel: str) -> str:
    # `encoding` explícito: sem ele o Windows lê em cp1252 e os guardas
    # bilingues morriam com UnicodeDecodeError — verdes na CI, mortos na
    # máquina de quem escreve o código.
    return pathlib.Path(rel).read_text(encoding="utf-8")


class TestCatalogoCompleto:
    def test_toda_a_chave_tem_as_tres_linguas(self):
        faltam = {
            chave: sorted(SUPPORTED_LANGUAGES - set(trad))
            for chave, trad in MESSAGES.items()
            if not SUPPORTED_LANGUAGES <= set(trad)
        }
        assert faltam == {}

    def test_nenhuma_traducao_esta_vazia(self):
        vazias = [
            f"{chave}.{lang}"
            for chave, trad in MESSAGES.items()
            for lang, texto in trad.items()
            if not (texto or "").strip()
        ]
        assert vazias == []

    def test_o_espanhol_nao_e_o_ingles_por_copiar(self):
        """Uma tradução por fazer costuma ser a inglesa colada.

        `SUGGESTION_LABEL` fica de fora com razão: «Suggestion» e
        «Sugerencia» são diferentes, mas há rótulos curtos que legitimamente
        coincidem, e um teste que grita por eles ensina a ignorá-lo.
        """
        iguais = [
            chave
            for chave, trad in MESSAGES.items()
            if trad.get("es") and trad["es"] == trad.get("en")
        ]
        assert iguais == []

    def test_o_portugues_tambem_nao(self):
        iguais = [
            chave
            for chave, trad in MESSAGES.items()
            if trad.get("pt") and trad["pt"] == trad.get("en")
        ]
        assert iguais == []

    def test_as_variaveis_sobrevivem_a_traducao(self):
        """`{topic}`, `{ate}`, `{de}` — se se perderem, a frase mente.

        Uma varredura de ortografia já partiu `{project}` em nove frases
        noutro repositório. O sintoma é uma frase que fica com um buraco.
        """
        for chave, trad in MESSAGES.items():
            esperadas = set(re.findall(r"\{(\w+)\}", trad["en"]))
            for lang, texto in trad.items():
                assert set(re.findall(r"\{(\w+)\}", texto)) == esperadas, (
                    f"{chave}.{lang} não tem as mesmas variáveis que o inglês"
                )


class TestPortuguesDePortugal:
    """O `pt` é de Portugal, e o tratamento é o mesmo em todas as frases."""

    # Só os inequívocos. `registro`/`registrado` não entram porque aparecem
    # como jargão técnico legítimo noutros contextos.
    BRASILEIRISMOS = re.compile(
        r"\b(voc[êe]|solicita[çc][ãa]o|entre em contato|planilha|"
        r"usu[áa]rio|conex[ãa]o|time\s+de|ger[êe]nci)",
        re.IGNORECASE,
    )
    # Tratar por «tu» no meio de frases que tratam por «você» lê-se como
    # descuido — e era o caso do TECHNICAL_ERROR, que dizia «os teus dados».
    TU = re.compile(r"\b(teus?|tuas?|tenta|avisa|reformula)\b")

    def test_sem_brasileirismos(self):
        achados = [
            f"{chave}: {trad['pt']}"
            for chave, trad in MESSAGES.items()
            if self.BRASILEIRISMOS.search(trad.get("pt", ""))
        ]
        assert achados == []

    def test_tratamento_uniforme(self):
        achados = [
            f"{chave}: {trad['pt']}"
            for chave, trad in MESSAGES.items()
            if self.TU.search(trad.get("pt", ""))
        ]
        assert achados == []

    def test_o_varrimento_apanha_de_facto(self):
        """Um teste que não vê nada passa sempre."""
        assert self.BRASILEIRISMOS.search("Reformule sua solicitação")
        assert self.TU.search("Tenta de novo com os teus dados")
        assert not self.BRASILEIRISMOS.search("Reformule o seu pedido")
        assert not self.TU.search("Tente de novo com os seus dados")


class TestNadaCravadoNoCodigo:
    """As frases vivem no catálogo, não em `if lang == "pt"`."""

    FICHEIROS = ["core/llm/orchestrator.py", "core/llm/periodo_decision.py"]

    def test_nao_ha_ramos_por_lingua_a_produzir_texto(self):
        """O padrão que deixava o espanhol de fora.

        Um `if lang == "pt"` seguido de uma STRING é uma frase que só existe
        em duas línguas. A comparação em si é legítima (escolher um formato
        de data, por exemplo); o que não pode é decidir texto.
        """
        for rel in self.FICHEIROS:
            linhas = _fonte(rel).split("\n")
            for i, linha in enumerate(linhas):
                if not re.search(r'lang(?:\.startswith)?\s*(?:==|\()\s*"pt"', linha):
                    continue
                # Comentários e docstrings falam do defeito e citam-no.
                if linha.strip().startswith("#") or linha.strip().startswith("*"):
                    continue
                vizinhas = "\n".join(linhas[i : i + 4])
                assert not re.search(r'"[A-Z][a-z]{4,}|"[NnÃã]o [a-z]', vizinhas), (
                    f"{rel}:{i + 1} decide TEXTO por língua — mova a frase "
                    f"para core/i18n/i18n.py\n{vizinhas}"
                )


class TestAsMensagensSaemMesmo:
    @pytest.mark.parametrize("lang", sorted(SUPPORTED_LANGUAGES))
    def test_cada_lingua_recebe_a_sua(self, lang):
        fora = get_message("OUT_OF_SCOPE", lang)
        assert fora and fora == MESSAGES["OUT_OF_SCOPE"][lang]

    def test_uma_lingua_que_nao_falamos_cai_no_ingles(self):
        # Responder em inglês a quem escreveu em alemão é honesto.
        assert get_message("OUT_OF_SCOPE", "de") == MESSAGES["OUT_OF_SCOPE"]["en"]

    def test_as_variaveis_sao_preenchidas(self):
        saida = get_message("PERIOD_OUT_OF_RANGE", "es", de="01/01/2026", ate="31/05/2026")
        assert "01/01/2026" in saida and "31/05/2026" in saida
        assert "{de}" not in saida

    def test_uma_variavel_em_falta_nao_rebenta_a_resposta(self):
        """Melhor a frase com o marcador do que uma excepção a meio da resposta."""
        saida = get_message("PERIOD_OUT_OF_RANGE", "pt")
        assert saida  # não levanta
