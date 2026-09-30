"""O cliente do modelo tem de desistir a certa altura.

⚠️ **Sem isto, uma paragem do fornecedor pendurava o pedido.**

A 29/09/2026 o smoke test de producao estourou aos 120 s numa pergunta, e
o pod nao escreveu UMA linha durante esse tempo:

    14:37:15  context_bundle_built
              ...silencio total...
    14:39:15  (a pergunta seguinte, ja da cache)

No dia anterior, uma pergunta real da app demorou **76,171 s** e passou.
Quem esperava nao via erro nenhum — via uma app parada, e lia isso como
avaria do backend. Foi o que o Lucas relatou.

── Porque e que ficava pendurado ────────────────────────────────────

O `ChatOpenAI` sem `timeout` herda o valor por omissao do SDK (600 s) e
ainda repete: meia hora de silencio no pior caso. O provedor do Ollama,
no mesmo ficheiro, ja tinha `timeout=300`.

**Isto nao torna o modelo mais rapido.** Torna a lentidao visivel, que e o
que falta hoje — e e por isso que nao se fecha o assunto da lentidao com
este teste.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

import core.llm.providers as providers  # noqa: E402


def test_o_provedor_openai_tem_limite_de_espera():
    fonte = (RAIZ / "core" / "llm" / "providers.py").read_text(encoding="utf-8")
    inicio = fonte.index("class LangChainChatOpenAIProvider")
    bloco = fonte[inicio : inicio + 2500]
    assert "timeout=" in bloco, "o ChatOpenAI voltou a ficar sem limite de tempo"


def test_o_limite_e_curto_o_bastante_para_se_ver():
    """Dois minutos ja e mais do que o cliente da app espera.

    Um limite maior do que o do cliente nao serve para nada: quem espera
    desiste primeiro e o pedido continua a ocupar o servidor.
    """
    assert 0 < providers._LIMITE_DE_ESPERA <= 120


def test_o_limite_e_configuravel_sem_mexer_em_codigo():
    """Se o fornecedor mudar de velocidade, muda-se a variavel."""
    fonte = (RAIZ / "core" / "llm" / "providers.py").read_text(encoding="utf-8")
    assert "LLM_TIMEOUT_SECONDS" in fonte


def test_nao_repete_sem_limite():
    """Tres tentativas de 90 s sao quatro minutos e meio de silencio.

    O valor por omissao do SDK sao duas repeticoes. Com o limite posto mas
    sem mexer nas repeticoes, o pior caso quase nao melhorava.
    """
    fonte = (RAIZ / "core" / "llm" / "providers.py").read_text(encoding="utf-8")
    inicio = fonte.index("class LangChainChatOpenAIProvider")
    bloco = fonte[inicio : inicio + 2500]
    assert "max_retries=" in bloco


def test_o_provedor_do_ollama_continua_com_o_dele():
    """Ja tinha 300 s — nao se mexe no que nao esta partido."""
    fonte = (RAIZ / "core" / "llm" / "providers.py").read_text(encoding="utf-8")
    assert "timeout=300" in fonte
