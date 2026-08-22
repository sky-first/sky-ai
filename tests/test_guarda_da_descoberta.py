"""O guarda da descoberta olhava para a tabela errada.

Duas tabelas com nomes parecidos e donos diferentes:

  · `connection_metadata` — do BACKEND. Diz que tabelas a ligação TEM.
    Escrita pelo `sync_connection`, que corre sozinho.
  · `table_metadata`      — da DESCOBERTA. É o que o `/query` lê.

O guarda do `/discover` perguntava só «há quanto tempo o `connection_metadata`
foi actualizado?». Bastava o backend sincronizar uma ligação para a janela
ficar fresca e a descoberta ser saltada — e cada nova tentativa encontrava-a
fresca outra vez, portanto **para sempre**.

Visto em produção a 22/08/2026 no cliente `sandbox`: `connection_metadata`
fresca, `table_metadata` a ZERO, e o `/query` a devolver 404 a todos os
agentes. Nenhum agente daquele cliente conseguia produzir um único achado, e
a resposta ao pedido de descoberta era «skipped — recent metadata exists».
"""

from __future__ import annotations

import inspect


def _fonte_sem_comentarios() -> str:
    from api.routes import connection_discover

    return "\n".join(
        l
        for l in inspect.getsource(connection_discover).splitlines()
        if not l.lstrip().startswith("#")
    )


def test_o_guarda_conta_as_linhas_da_tabela_que_a_descoberta_escreve():
    fonte = _fonte_sem_comentarios()
    assert "FROM table_metadata tm" in fonte
    assert 'and (row["linhas"] or 0) > 0' in fonte


def test_saltar_exige_as_duas_condicoes():
    """Recente E com linhas.

    Só a idade era o defeito; só as linhas seria o outro extremo — uma
    descoberta que nunca mais se refazia depois da primeira.
    """
    fonte = _fonte_sem_comentarios()
    i = fonte.index('row["age"] is not None')
    bloco = fonte[i : i + 400]
    assert "row[\"age\"] < skip_if_recent_seconds" in bloco
    assert 'row["linhas"]' in bloco


def test_ter_catalogo_nao_e_ter_metadados():
    """O `metadata-status` tinha o mesmo engano com outra cara: respondia
    «tem metadados» só por haver catálogo do backend, e quem o consultasse
    decidia não descobrir sobre uma base onde o `/query` daria 404."""
    fonte = _fonte_sem_comentarios()
    assert "linhas_reais = await _contar_table_metadata(db, connection_id)" in fonte
    assert "has_metadata = tables_discovered > 0 and linhas_reais > 0" in fonte


def test_falhar_a_contar_manda_descobrir():
    """Zero é o lado seguro: descobrir a mais custa tempo, descobrir a menos
    deixa o cliente sem respostas."""
    from api.routes.connection_discover import _contar_table_metadata

    fonte = inspect.getsource(_contar_table_metadata)
    assert "return 0" in fonte
