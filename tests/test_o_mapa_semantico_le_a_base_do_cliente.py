# -*- coding: utf-8 -*-
"""O universo vazio com 59 embeddings na base.

> «cade aqui no sky universe todo o dado ao rededor desse globo de
>  raio? deveria aparecer todo o dado do cliente ai»
> — Lucas, 07/10/2026

Medido, antes de mexer em nada:

    embeddings do projecto Logística, na base do cliente      59
    /semantic/map SEM  X-Tenant-Slug   → HTTP 200, count=0
    /semantic/map COM  X-Tenant-Slug   → HTTP 200, count=0

As duas iguais, e é isso que diz tudo: o cabeçalho **chegava** e era
ignorado. O `post_semantic_map` abria `AsyncSessionLocal()` — a ligação
GLOBAL — e consultava a base da plataforma, onde os embeddings deste
cliente não estão.

── Porquê um teste, se a correcção é uma linha ─────────────────────

Porque é a terceira vez.

    05/10  o semeador, no `sincronizar_metadados`
    08/10  o `BackendClient`, sem cabeçalho nenhum
    08/10  isto

Sempre o mesmo desenho: o caminho novo usa o gestor de ligações, o
caminho esquecido usa a sessão global. E nunca rebenta — devolve zero
linhas, que o ecrã mostra correctamente como «não há nada aqui».
Nenhum erro, nenhum registo. Custou contar linhas em duas bases, três
vezes.

Este teste não verifica que a consulta funciona: verifica que ninguém
volta a abrir a sessão global num caminho que serve um cliente.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from api.routes import semantic_map

RAIZ = Path(__file__).resolve().parents[1]


class TestASessaoEDoCliente:
    def test_o_mapa_usa_o_gestor_de_ligacoes(self):
        fonte = inspect.getsource(semantic_map.post_semantic_map)
        assert "tenant_connection_manager.async_session_for()" in fonte, (
            "o /semantic/map voltou a abrir a sessão global — vai ler a base "
            "da plataforma e devolver count=0 em silêncio"
        )

    def test_e_a_busca_tambem(self):
        fonte = inspect.getsource(semantic_map.post_semantic_search)
        assert "tenant_connection_manager.async_session_for()" in fonte

    def test_nenhum_caminho_do_ficheiro_abre_a_sessao_global(self):
        """O contrapeso: corrigir dois e deixar um terceiro.

        Foi exactamente assim que isto chegou a três sítios — cada
        correcção tratou do caminho que estava à vista.
        """
        fonte = (RAIZ / "api" / "routes" / "semantic_map.py").read_text(
            encoding="utf-8"
        )
        # Fora dos comentários: a nota que explica o defeito cita o nome.
        sem_comentarios = re.sub(r"^\s*#.*$", "", fonte, flags=re.M)
        assert "AsyncSessionLocal(" not in sem_comentarios


class TestOQueONaoMudou:
    def test_um_ambito_vazio_continua_a_devolver_lista_vazia(self):
        """E não um erro.

        Um utilizador sem projectos nem equipas não tem embeddings
        visíveis, e isso não é uma avaria: o ecrã tem um estado próprio
        para o dizer.
        """
        fonte = inspect.getsource(semantic_map._load_embeddings)
        assert "if not conditions:" in fonte
        assert "return []" in fonte

    def test_a_visibilidade_continua_a_ser_por_pertenca(self):
        """A sessão passou a ser do cliente; quem vê o quê não mudou.

        Dentro da base do cliente continua a filtrar-se por
        utilizador, projecto e equipa — trocar a ligação não pode
        transformar-se em «toda a gente vê tudo».
        """
        fonte = inspect.getsource(semantic_map._load_embeddings)
        for campo in ("user_id", "space_id", "crew_id"):
            assert campo in fonte, f"o filtro por {campo} desapareceu"


@pytest.mark.parametrize(
    "ficheiro",
    ["api/routes/pipeline.py"],
)
def test_os_outros_caminhos_ficam_assinalados(ficheiro):
    """Um aviso, não uma falha.

    O `pipeline.py` abre a sessão global em três sítios. Não sei se
    serve conteúdo de cliente — não o investiguei, e marcá-lo como
    falha sem saber seria ruído. Este teste falha **se alguém o
    corrigir**, e nessa altura apaga-se a linha.

    Fica aqui para a dívida não desaparecer da cabeça de ninguém.
    """
    fonte = (RAIZ / ficheiro).read_text(encoding="utf-8")
    assert "AsyncSessionLocal()" in fonte, (
        f"{ficheiro} deixou de usar a sessão global — tire-o desta lista"
    )
