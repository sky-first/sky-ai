"""Produção, 14/10/2026 — tenant sandbox, projecto Restauración, três ligações
(Tiendas / Servicio / Cocina), caminho multi-fonte por ligação (opção B).

«¿Cuáles fueron las ventas por tienda y familia de producto el último mes?»

- fatia ``stores`` OK; fatia ``orders``+``order_items`` OK (com um CTE);
- fatia ``products`` (Cocina): ``semantic_check_parse_error`` «Unexpected
  token» logo a seguir à linha do ``JOIN (SELECT DISTINCT ...) oi`` e depois
  «Table 'step' is not allowed». A fatia foi dada como falhada sem nova
  tentativa e a resposta saiu sem a família de produto.

Causa reproduzida: o modelo escreveu o SQL e, a seguir, uma frase («...the
join step matches them...» — palavras do próprio contrato da fatia). A
extracção do SQL guarda tudo desde o SELECT até ao fim, o sqlglot não percebe
a frase e o validador, que procurava tabelas com uma regex ``FROM|JOIN <x>``
no texto inteiro, leu «join step» como a tabela ``step``.

Testa-se o comportamento: o que o validador deixa passar e o que bloqueia, o
que chega à base e o que acontece a uma fatia que falha.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.agents.generic_sql_agent import AgentConfig, TableSchema
from core.sql.validator_advanced import AdvancedSQLValidator

PERGUNTA = "¿Cuáles fueron las ventas por tienda y familia de producto el último mes?"

PERMITIDAS = [
    "stores.stores",
    "service.orders",
    "service.order_items",
    "kitchen.products",
]


def _validar(sql, dialecto="postgres"):
    return AdvancedSQLValidator(PERMITIDAS).validate(sql, dialecto)


# ── 1. Validador: CTEs, subconsultas derivadas, comentários ─────────────

SQL_SERVICIO_CTE = """WITH order_items_agg AS (
  SELECT oi.order_id, oi.product_id, SUM(oi.quantity * oi.unit_price) AS ventas
  FROM service.order_items oi
  GROUP BY oi.order_id, oi.product_id
)
SELECT o.store_id, a.product_id, SUM(a.ventas) AS ventas
FROM service.orders o
JOIN order_items_agg a ON a.order_id = o.order_id
WHERE o.created_at >= date_trunc('month', now()) - interval '1 month'
GROUP BY o.store_id, a.product_id
LIMIT 5000"""

SQL_COCINA_DERIVADA = """SELECT p."id" AS product_id, p."name", p."family"
FROM kitchen.products p
JOIN (SELECT DISTINCT "id" AS product_id FROM kitchen.products) oi
  ON p."id" = oi."product_id"
LIMIT 5000"""


def test_cte_da_fatia_servicio_passa():
    assert _validar(SQL_SERVICIO_CTE) == (True, None)


def test_subconsulta_derivada_com_alias_passa():
    assert _validar(SQL_COCINA_DERIVADA) == (True, None)


def test_comentario_com_from_ou_join_nao_e_tabela():
    """«-- ... the join step ...» num comentário não é uma tabela: o
    comentário nunca chega a correr."""
    sql = (
        "SELECT p.id, p.name, p.family\n"
        "FROM kitchen.products p\n"
        "-- products come whole, the join step matches them from step 1\n"
        "LIMIT 5000"
    )
    assert _validar(sql) == (True, None)


def test_tabela_nao_autorizada_dentro_de_um_cte_continua_bloqueada():
    """A regex só olhava para o nível de topo quando lá havia alguma tabela:
    dentro do CTE ninguém verificava."""
    sql = (
        "WITH x AS (SELECT s.salary FROM hr.salaries s)\n"
        "SELECT x.salary FROM x LIMIT 10"
    )
    ok, erro = _validar(sql)
    assert not ok
    assert "hr.salaries" in erro


def test_tabela_nao_autorizada_numa_subconsulta_continua_bloqueada():
    sql = (
        "SELECT p.id FROM kitchen.products p\n"
        "WHERE p.id IN (SELECT s.product_id FROM hr.salaries s)\n"
        "LIMIT 10"
    )
    ok, erro = _validar(sql)
    assert not ok
    assert "hr.salaries" in erro


def test_cte_com_o_nome_de_uma_tabela_nao_esconde_a_tabela_qualificada():
    """``private.secret`` é a tabela física, não o CTE ``secret``."""
    sql = (
        "WITH secret AS (SELECT p.id FROM kitchen.products p)\n"
        "SELECT s.id FROM private.secret s LIMIT 10"
    )
    ok, erro = _validar(sql)
    assert not ok
    assert "private.secret" in erro


def test_cte_fora_do_seu_ambito_nao_autoriza_a_tabela_com_o_mesmo_nome():
    """O CTE ``secret`` só existe dentro da subconsulta; o ``FROM secret`` de
    fora é a tabela física ``secret`` do search_path."""
    sql = (
        "SELECT secret.a FROM secret,\n"
        "  (WITH secret AS (SELECT p.id AS a FROM kitchen.products p)\n"
        "   SELECT secret.a FROM secret) x\n"
        "LIMIT 10"
    )
    ok, erro = _validar(sql)
    assert not ok
    assert "secret" in erro


def test_bigquery_com_crases_continua_a_passar():
    v = AdvancedSQLValidator(["proj.ds.vendas"])
    sql = "SELECT v.loja, SUM(v.total) AS t FROM `proj.ds.vendas` v GROUP BY v.loja"
    assert v.validate(sql, "bigquery") == (True, None)


# ── 2. Especialista: prosa depois do SQL ────────────────────────────────


def _products():
    return TableSchema(
        logical_name="products",
        physical_name="kitchen.products",
        description="Platos de la carta.",
        data_connection_id="d553b700",
        columns=[
            {"name": "id", "type": "integer"},
            {"name": "name", "type": "text"},
            {"name": "family", "type": "text"},
        ],
    )


def _stores():
    return TableSchema(
        logical_name="stores",
        physical_name="stores.stores",
        description="Tiendas de la cadena.",
        data_connection_id="611b5fb0",
        columns=[
            {"name": "id", "type": "integer"},
            {"name": "name", "type": "text"},
        ],
    )


def _orders():
    return TableSchema(
        logical_name="orders",
        physical_name="service.orders",
        description="Pedidos.",
        data_connection_id="006f2967",
        columns=[
            {"name": "order_id", "type": "integer"},
            {"name": "store_id", "type": "integer"},
            {"name": "created_at", "type": "timestamp"},
        ],
    )


def _order_items():
    return TableSchema(
        logical_name="order_items",
        physical_name="service.order_items",
        description="Líneas de pedido.",
        data_connection_id="006f2967",
        columns=[
            {"name": "order_id", "type": "integer"},
            {"name": "product_id", "type": "integer"},
            {"name": "quantity", "type": "integer"},
            {"name": "unit_price", "type": "numeric"},
        ],
    )


def _cfg():
    return AgentConfig(
        id="t",
        name="t",
        tables=[_stores(), _orders(), _order_items(), _products()],
    )


class _Fonte:
    dialect = "postgres"

    def __init__(self, linhas):
        self.linhas = linhas
        self.consultas = []

    def sample_table_rows(self, *_a, **_k):
        return []

    def run_query(self, sql):
        self.consultas.append(sql)
        if sql.strip().upper().startswith("SELECT DISTINCT"):
            return []
        return list(self.linhas)


class _Modelo:
    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.chamadas = []

    def invoke(self, mensagens, *_a, **_k):
        self.chamadas.append(mensagens)
        i = min(len(self.chamadas) - 1, len(self.respostas) - 1)
        return SimpleNamespace(content=self.respostas[i])


LINHAS_PRODUCTS = [
    {"product_id": 1, "name": "Paella", "family": "Arroces"},
    {"product_id": 2, "name": "Gazpacho", "family": "Entrantes"},
]

RESPOSTA_COM_PROSA = (
    "-- TITLE: Productos y familia\n"
    'SELECT p."id" AS product_id, p."name", p."family"\n'
    "FROM kitchen.products p\n"
    "LIMIT 5000\n"
    "\n"
    "Note: products are returned whole, the join step matches them with the "
    "order lines by product_id."
)


def _estado_fatia():
    return {
        "question": PERGUNTA,
        "detected_language": "es",
        "chosen_table": "products",
        "chosen_table_physical": "kitchen.products",
        "chosen_tables": ["products"],
        "chosen_tables_physical": ["kitchen.products"],
        "join_relationships": None,
        "multi_source_subquery": True,
        "contrato_da_fatia": "MULTI-SOURCE SLICE CONTRACT (mandatory): ...",
    }


def test_prosa_depois_do_sql_nao_mata_a_fatia_e_nao_chega_a_base():
    from core.llm.specialist import run_specialist

    fonte = _Fonte(LINHAS_PRODUCTS)
    st = run_specialist(_estado_fatia(), _cfg(), fonte, _Modelo(RESPOSTA_COM_PROSA))
    assert not st.get("error"), st.get("error")
    assert st.get("data") == LINHAS_PRODUCTS
    corridas = [c for c in fonte.consultas if "kitchen.products" in c]
    assert corridas, fonte.consultas
    assert all("Note:" not in c and "join step" not in c for c in corridas)


def test_sql_invalido_sem_prosa_nao_e_cortado():
    """Cortar só a prosa: uma cláusula SQL estragada não é «prosa» e não pode
    ser deitada fora (dava uma consulta diferente que corria)."""
    from core.sql.tabelas import cortar_prosa_final

    sql = (
        "SELECT p.id, p.family\n"
        "FROM kitchen.products p\n"
        "WHERE p.family = = 'Arroces'\n"
        "LIMIT 5000"
    )
    assert cortar_prosa_final(sql, "postgres") == sql


def test_sql_valido_nunca_e_mexido():
    from core.sql.tabelas import cortar_prosa_final

    assert cortar_prosa_final(SQL_SERVICIO_CTE, "postgres") == SQL_SERVICIO_CTE


# ── 3. executar_fatias: uma nova tentativa com o erro como feedback ─────


class _Amb:
    def __init__(self):
        self.cfg = _cfg()
        self.fontes = {
            "611b5fb0": SimpleNamespace(label="Tiendas", dialect="postgres"),
            "006f2967": SimpleNamespace(label="Servicio", dialect="postgres"),
            "d553b700": SimpleNamespace(label="Cocina", dialect="postgres"),
        }


def _especialista_falso(respostas_por_ligacao):
    """run_specialist falso: por ligação, devolve as respostas por ordem."""
    chamadas = []

    def run(st, cfg, src, llm):
        chamadas.append(dict(st))
        cid = next(
            t.data_connection_id
            for t in cfg.tables
            if t.physical_name == st["chosen_tables_physical"][0]
        )
        fila = respostas_por_ligacao[cid]
        n = sum(
            1
            for c in chamadas
            if c["chosen_tables_physical"] == st["chosen_tables_physical"]
        )
        r = dict(st)
        r.update(fila[min(n - 1, len(fila) - 1)])
        return r

    return run, chamadas


def test_fatia_com_erro_de_validacao_tenta_outra_vez_com_o_erro():
    from core.llm.multi_fonte import executar_fatias

    amb = _Amb()
    run, chamadas = _especialista_falso(
        {
            "611b5fb0": [{"data": [{"id": 1, "name": "Centro"}], "sql": "s"}],
            "006f2967": [{"data": [{"store_id": 1, "ventas": 9}], "sql": "o"}],
            "d553b700": [
                {
                    "data": None,
                    "sql": "SELECT bad",
                    "error": "Table 'step' is not allowed",
                },
                {"data": LINHAS_PRODUCTS, "sql": "SELECT p.id FROM kitchen.products p"},
            ],
        }
    )
    parciais, _, falhadas = executar_fatias(
        {"question": PERGUNTA},
        amb.cfg,
        ["stores", "orders", "order_items", "products"],
        amb.fontes,
        None,
        llm=None,
        run_specialist=run,
    )
    assert falhadas == []
    assert [p["connection_id"] for p in parciais] == [
        "611b5fb0",
        "006f2967",
        "d553b700",
    ]
    cocina = [
        c for c in chamadas if c["chosen_tables_physical"] == ["kitchen.products"]
    ]
    assert len(cocina) == 2
    assert not cocina[0].get("feedback_da_fatia")
    fb = cocina[1]["feedback_da_fatia"]
    assert "Table 'step' is not allowed" in fb and "SELECT bad" in fb
    # as outras fatias correram uma vez só
    assert len(chamadas) == 4


def test_fatia_que_falha_duas_vezes_fica_falhada_sem_terceira_tentativa():
    from core.llm.multi_fonte import executar_fatias

    amb = _Amb()
    run, chamadas = _especialista_falso(
        {
            "611b5fb0": [{"data": [{"id": 1}], "sql": "s"}],
            "d553b700": [
                {"data": None, "sql": "x", "error": "Error executing query: boom"}
            ],
        }
    )
    parciais, _, falhadas = executar_fatias(
        {"question": PERGUNTA},
        amb.cfg,
        ["stores", "products"],
        amb.fontes,
        None,
        llm=None,
        run_specialist=run,
    )
    assert len(parciais) == 1
    assert falhadas and "boom" in falhadas[0]["reason"]
    assert (
        len(
            [c for c in chamadas if c["chosen_tables_physical"] == ["kitchen.products"]]
        )
        == 2
    )


def test_impossible_nao_gasta_nova_tentativa():
    """IMPOSSIBLE é uma resposta, não um erro: o guardrail já tem a sua."""
    from core.llm.multi_fonte import executar_fatias

    amb = _Amb()
    run, chamadas = _especialista_falso(
        {
            "611b5fb0": [{"data": [{"id": 1}], "sql": "s"}],
            "d553b700": [{"data": None, "impossible_reason": "no family column"}],
        }
    )
    _, _, falhadas = executar_fatias(
        {"question": PERGUNTA},
        amb.cfg,
        ["stores", "products"],
        amb.fontes,
        None,
        llm=None,
        run_specialist=run,
    )
    assert len(falhadas) == 1
    assert len(chamadas) == 2


def test_nova_tentativa_ponta_a_ponta_leva_o_erro_ao_modelo():
    """Com o especialista verdadeiro: 1.ª resposta chumba no validador
    (SELECT *), a 2.ª vem corrigida — e o modelo viu o erro."""
    from core.llm.multi_fonte import executar_fatias

    amb = _Amb()
    fonte = _Fonte(LINHAS_PRODUCTS)
    amb.fontes["d553b700"] = fonte
    modelo = _Modelo(
        "-- TITLE: Productos\nSELECT * FROM kitchen.products LIMIT 5000",
        '-- TITLE: Productos\nSELECT p."id", p."name", p."family" '
        "FROM kitchen.products p LIMIT 5000",
    )
    parciais, _, falhadas = executar_fatias(
        {"question": PERGUNTA, "detected_language": "es"},
        amb.cfg,
        ["products"],
        amb.fontes,
        fonte,
        llm=modelo,
    )
    assert falhadas == [], falhadas
    assert parciais and parciais[0]["data"] == LINHAS_PRODUCTS
    segundo_prompt = "\n".join(m["content"] for m in modelo.chamadas[-1])
    assert "SELECT * is not allowed" in segundo_prompt


# ── 4. Contrato: tabelas de dimensão vêm inteiras ───────────────────────


def test_contrato_diz_que_tabela_de_entidades_vem_inteira_sem_join():
    from core.llm.multi_fonte import agrupar_por_ligacao, contrato_da_fatia

    amb = _Amb()
    fatias = agrupar_por_ligacao(
        ["stores", "orders", "order_items", "products"], amb.cfg, amb.fontes
    )
    cocina = next(f for f in fatias if f.connection_id == "d553b700")
    texto = contrato_da_fatia(cocina, [f for f in fatias if f is not cocina])
    assert "describes entities" in texto
    assert "no JOIN" in texto
    assert "plain text after the SQL" in texto


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
