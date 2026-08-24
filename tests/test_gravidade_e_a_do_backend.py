"""As gravidades que este servico devolve tem de ser as que o backend aceita.

**O defeito, e foi meu.** Escrevi `med` aqui a 22/08. O esquema do backend tem
um enum `low|medium|high|critical`. Todo o achado que este classificador tocou
passou a rebentar o `GET /agents/{id}` com::

    Input should be 'low', 'medium', 'high' or 'critical' [input: 'med']

Ficou dois dias em producao sem ninguem dar por isso, porque a LISTA de agentes
funciona — nao devolve achados — e so o DETALHE e que parte. Encontrei-o a
percorrer os ecras com o Lucas, e o ecra que ele abriria amanha era esse.

Duas palavras para a mesma coisa, em dois servicos, e a diferenca so aparece
num 500 dois dias depois.
"""

from api.routes.classificar_achado import GRAVIDADES, TIPOS, _limpar


#: Copia do enum do backend (`src/models/agent.py`, `FindingSeverity`). Os dois
#: repositorios nao se importam um ao outro, portanto a unica maneira de os
#: manter alinhados e escrever aqui o que la esta — e falhar alto se divergir.
GRAVIDADES_DO_BACKEND = {"low", "medium", "high", "critical"}
TIPOS_DO_BACKEND = {"risk", "opportunity", "insight"}


def test_todas_as_gravidades_existem_no_backend():
    """**O defeito exacto.** `med` nao existe do outro lado."""
    fora = set(GRAVIDADES) - GRAVIDADES_DO_BACKEND
    assert fora == set(), f"gravidades que o backend recusa: {fora}"


def test_todos_os_tipos_existem_no_backend():
    fora = set(TIPOS) - TIPOS_DO_BACKEND
    assert fora == set(), f"tipos que o backend recusa: {fora}"


def test_o_med_do_modelo_e_traduzido_e_nao_rejeitado():
    """O modelo continua a dizer «med» de vez em quando.

    Estava no prompt ate agora e ha exemplos disso no mundo. Traduzir vale
    mais do que rejeitar e cair no de omissao — a classificacao estava certa,
    so a palavra e que era outra.
    """
    import asyncio
    from unittest.mock import MagicMock, patch

    from api.routes import classificar_achado as mod

    resposta = MagicMock()
    resposta.content = '{"type": "risk", "severity": "med"}'
    with patch.object(mod, "_modelo", lambda: MagicMock(invoke=lambda _: resposta)):
        r = asyncio.run(
            mod.classificar(
                mod.PedidoDeClassificacao(title="t", answer="Ha 17 faturas em atraso.")
            )
        )
    assert r.severity == "medium"
    assert r.type == "risk"


def test_o_de_omissao_tambem_e_valido():
    """Ate a saida de emergencia tem de ser gravavel.

    Um valor que a API nao consegue serializar transforma um achado bom num
    500: o achado fica na base e o ecra nunca o mostra.
    """
    import asyncio
    from unittest.mock import MagicMock, patch

    from api.routes import classificar_achado as mod

    def _rebenta():
        raise RuntimeError("modelo em baixo")

    with patch.object(mod, "_modelo", _rebenta):
        r = asyncio.run(
            mod.classificar(
                mod.PedidoDeClassificacao(title="t", answer="Ha 17 faturas em atraso.")
            )
        )
    assert r.severity in GRAVIDADES_DO_BACKEND
    assert r.type in TIPOS_DO_BACKEND
