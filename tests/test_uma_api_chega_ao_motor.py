# -*- coding: utf-8 -*-
"""Uma ligação a uma API tem de chegar ao motor.

> *"quero fazer pergunta com alguma api publica que possa existir por
> exemplo de temperatura"* — Lucas, 31/08/2026

---

**Fui fazer a pergunta, e a cadeia partia-se em três sítios.**

Liguei a Open-Meteo, declarei o ponto de acesso `/forecast`, perguntei «Qual
a temperatura em Lisboa agora?». Cada correcção destapava a seguinte:

1. **`table_metadata` ficava vazia.** A ingestão grava uma linha por COLUNA,
   e o conector REST expõe cada ponto de acesso como uma tabela **sem
   colunas** — de propósito, porque não se sabem até à primeira resposta. O
   ciclo não corria uma única vez: `tables_discovered: 1`,
   `metadata_rows_inserted: 0`.

2. **O filtro por equipa, outra vez.** A consulta do `/query` fazia
   ``if crew_ids: ... else: AND crew_id IS NULL``. Eu tinha tirado este
   filtro do `factory.py` e dado a fatia por fechada — estava copiado em
   mais quatro sítios, e este era o do caminho quente.

3. **A fábrica não reconhecia o conector.** Esperava o tipo `"api"` e o que
   chega é o **id do conector**: `rest-api`. Rebentava com *"Unsupported
   data source type: 'rest-api'"* com todo o resto já a funcionar.

No fim, o `APISource` devolveu, ao vivo:

    {"time": "2026-08-31T14:30", "interval": 900, "temperature_2m": 25.4}

Nada disto aparecia a ler código. Apareceu a pôr o motor de pé e a
perguntar-lhe.
"""
from __future__ import annotations

import inspect
import json

import pytest

from core.data_sources import factory as fabrica
from core.ingestion import db_metadata


class TestAFabricaReconheceOsConectoresDeApi:
    def test_o_id_do_conector_e_normalizado(self):
        fonte = inspect.getsource(fabrica.DataSourceFactory.build_from_dataconnection)
        assert '"rest-api"' in fonte
        assert 'ds_type = "api"' in fonte

    @pytest.mark.parametrize("nome", ["rest-api", "rest_api", "graphql", "http"])
    def test_os_nomes_conhecidos_estao_na_lista(self, nome):
        """Uma lista num sítio só. Espalhar `or` pelo ramo garantia que o
        próximo conector de API voltava a falhar em silêncio."""
        fonte = inspect.getsource(fabrica.DataSourceFactory.build_from_dataconnection)
        i = fonte.index('ds_type = "api"')
        assert f'"{nome}"' in fonte[max(0, i - 400) : i]


class TestUmaTabelaSemColunasContinuaAExistir:
    def test_a_ingestao_trata_o_caso(self):
        fonte = inspect.getsource(db_metadata.ingest_from_connection_metadata_cache)
        assert "if not columns:" in fonte

    def test_grava_uma_linha_ancora(self):
        """`table_metadata` exige `column_name`; `*` diz «a tabela toda»."""
        fonte = inspect.getsource(db_metadata.ingest_from_connection_metadata_cache)
        i = fonte.index("if not columns:")
        bloco = fonte[i : i + 1800]
        assert 'column_name="*"' in bloco
        assert "inserted += 1" in bloco
        assert "continue" in bloco

    def test_a_descricao_cai_para_o_metodo_e_caminho(self):
        """Sem descrição o orquestrador não tem como escolher esta e não
        outra. `GET /forecast` é pouco, e é muito melhor do que nada."""
        fonte = inspect.getsource(db_metadata.ingest_from_connection_metadata_cache)
        i = fonte.index("if not columns:")
        bloco = fonte[i : i + 1800]
        assert "extra_meta.get(\"description\")" in bloco
        assert "method" in bloco and "path" in bloco

    def test_e_marca_a_linha_como_sem_colunas(self):
        """Para se distinguir de uma tabela a sério com uma coluna `*`."""
        fonte = inspect.getsource(db_metadata.ingest_from_connection_metadata_cache)
        assert '"sem_colunas": True' in fonte


class TestAApiResponde:
    """O elo final, contra a API pública a sério.

    Marcado `network`: numa máquina sem saída para a internet isto não pode
    fazer a suite falhar."""

    @pytest.mark.network
    def test_a_open_meteo_devolve_a_temperatura(self):
        from core.data_sources.base import DataSourceConfig
        from core.data_sources.api_source import APISource

        fonte = APISource(
            DataSourceConfig(
                id="teste",
                type="api",
                default_schema=None,
                extra={"base_url": "https://api.open-meteo.com/v1"},
            ),
            label="api:teste",
        )
        linhas = fonte.run_query(
            json.dumps(
                {
                    "method": "GET",
                    "endpoint": "/forecast",
                    "params": {
                        "latitude": 38.72,
                        "longitude": -9.14,
                        "current": "temperature_2m",
                    },
                }
            )
        )
        assert len(linhas) == 1
        assert "temperature_2m" in linhas[0].get("current", {})
