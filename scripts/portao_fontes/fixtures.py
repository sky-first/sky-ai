# -*- coding: utf-8 -*-
"""Duas bases SEPARADAS, como em produção: a do cliente e a ``sky_world``.

- **cliente** — esquemas ``fleet`` e ``ops`` com as colunas da sementeira
  «Logística y Transporte» (sky-backend ``scripts/demo/seed_transport.sql``):
  viaturas, motoristas, rotas e ~1.500 viagens entre 01/10/2025 e 30/09/2026.
- **mundo** — esquema ``mundo`` com as colunas do carregador
  (``scripts/dados_publicos/mundo/esquema.py``): postos MITECO e a sua
  proximidade às rotas, gasóleo por província e dia, boletim semanal da UE,
  feriados, portagens, restrições DGT, tempo, e ``fontes`` (frescura/licença).

São duas ligações DuckDB distintas (dialecto Postgres): uma consulta numa
não vê a outra, tal como o Postgres do cliente não vê o ``sky_world``. Tudo
determinístico (semente fixa) para que os números esperados sejam estáveis.
"""

from __future__ import annotations

import datetime as dt
import random
import threading
from typing import Any, Dict, List, Optional

import duckdb

from core.agents.generic_sql_agent import AgentConfig, TableSchema
from core.dialects import Dialect

LIGACAO_CLIENTE = "11111111-1111-4111-8111-111111111111"
LIGACAO_MUNDO = "22222222-2222-4222-8222-222222222222"

INICIO = dt.date(2025, 10, 1)
FIM = dt.date(2026, 9, 30)

ROTAS = [
    # id, origem, destino, km, minutos padrão
    (1, "Badajoz", "Madrid", 402, 300),
    (2, "Lisboa", "Madrid", 625, 470),
    (3, "Porto", "Madrid", 560, 492),
    (4, "Mérida", "Sevilla", 195, 150),
    (5, "Badajoz", "Sevilla", 220, 170),
    (6, "Lisboa", "Badajoz", 230, 180),
    (7, "Mérida", "Madrid", 340, 260),
]

VIATURAS = [
    (1, "1234-KLM", "Volvo FH 500", "semirremolque", "2021-03-01", 24000, 2100.00),
    (2, "2345-KLN", "Scania R450", "semirremolque", "2020-06-15", 24000, 1950.00),
    (3, "3456-KLP", "DAF XF 480", "semirremolque", "2022-01-10", 24000, 2200.00),
    (4, "4567-KLR", "MAN TGX", "semirremolque", "2019-09-20", 24000, 1800.00),
    (5, "5678-KLS", "Iveco S-Way frigo", "frigorífico", "2021-11-05", 18000, 2400.00),
    (6, "6789-KLT", "Renault T frigo", "frigorífico", "2022-04-18", 18000, 2350.00),
    (7, "7890-KLV", "Mercedes Sprinter", "ligero", "2023-02-01", 1500, 650.00),
    (8, "8901-KLW", "Iveco Daily", "ligero", "2023-05-12", 1500, 620.00),
]

MOTORISTAS = [
    (1, "Ana Ruiz", "C+E", "2019-01-10", 21.50),
    (2, "Bruno Costa", "C+E", "2020-03-01", 19.80),
    (3, "Carlos Díaz", "C+E", "2018-07-15", 23.40),
    (4, "Diana Lopes", "C", "2021-09-01", 17.60),
    (5, "Eduardo Gil", "C+E", "2017-02-20", 24.10),
    (6, "Filipa Sousa", "C", "2022-05-05", 18.30),
]

# Feriados (subconjunto realista; regiões ISO 3166-2).
FESTIVOS = [
    ("2025-10-12", "ES", None, "Fiesta Nacional de España"),
    ("2025-11-01", "ES", None, "Todos los Santos"),
    ("2025-12-06", "ES", None, "Día de la Constitución"),
    ("2025-12-08", "ES", None, "Inmaculada Concepción"),
    ("2025-12-25", "ES", None, "Navidad"),
    ("2026-01-01", "ES", None, "Año Nuevo"),
    ("2026-01-06", "ES", None, "Epifanía del Señor"),
    ("2026-04-03", "ES", None, "Viernes Santo"),
    ("2026-05-01", "ES", None, "Fiesta del Trabajo"),
    ("2026-08-15", "ES", None, "Asunción de la Virgen"),
    ("2026-04-02", "ES", "ES-EX", "Jueves Santo"),
    ("2026-09-08", "ES", "ES-EX", "Día de Extremadura"),
    ("2026-02-28", "ES", "ES-AN", "Día de Andalucía"),
    ("2026-04-02", "ES", "ES-MD", "Jueves Santo"),
    ("2026-05-02", "ES", "ES-MD", "Fiesta de la Comunidad de Madrid"),
    ("2025-10-05", "PT", None, "Implantação da República"),
    ("2025-11-01", "PT", None, "Dia de Todos os Santos"),
    ("2025-12-01", "PT", None, "Restauração da Independência"),
    ("2025-12-08", "PT", None, "Imaculada Conceição"),
    ("2025-12-25", "PT", None, "Natal"),
    ("2026-01-01", "PT", None, "Ano Novo"),
    ("2026-04-03", "PT", None, "Sexta-feira Santa"),
    ("2026-04-25", "PT", None, "Dia da Liberdade"),
    ("2026-05-01", "PT", None, "Dia do Trabalhador"),
    ("2026-06-10", "PT", None, "Dia de Portugal"),
    ("2026-08-15", "PT", None, "Assunção de Nossa Senhora"),
]

# Dias com restrição DGT a >7,5 t (subconjunto; A-5 e A-4).
RESTRICOES = [
    ("2025-10-12", "A-5", 0.0, 60.0, "Salida Madrid", "08:00", "15:00"),
    ("2025-12-05", "A-5", 0.0, 60.0, "Salida Madrid", "15:00", "22:00"),
    ("2025-12-08", "A-5", 0.0, 60.0, "Entrada Madrid", "15:00", "22:00"),
    ("2026-01-06", "A-5", 0.0, 60.0, "Entrada Madrid", "15:00", "22:00"),
    ("2026-04-01", "A-5", 0.0, 60.0, "Salida Madrid", "13:00", "22:00"),
    ("2026-04-02", "A-5", 0.0, 60.0, "Salida Madrid", "08:00", "15:00"),
    ("2026-04-06", "A-5", 0.0, 60.0, "Entrada Madrid", "15:00", "24:00"),
    ("2026-07-31", "A-5", 0.0, 60.0, "Salida Madrid", "15:00", "22:00"),
    ("2026-08-14", "A-5", 0.0, 60.0, "Salida Madrid", "15:00", "22:00"),
    ("2026-08-30", "A-5", 0.0, 60.0, "Entrada Madrid", "15:00", "24:00"),
    ("2026-04-02", "A-4", 0.0, 50.0, "Salida Madrid", "08:00", "15:00"),
    ("2026-08-14", "A-4", 0.0, 50.0, "Salida Madrid", "15:00", "22:00"),
]

# Portagens públicas (pesado 4+ eixos). A A-5 e a A-66 são gratuitas.
PORTAGENS = [
    ("A-5", "Badajoz", "Madrid", "pesado_4_mais_eixos", "ES", 402, 0.0, True),
    ("A-5", "Mérida", "Madrid", "pesado_4_mais_eixos", "ES", 340, 0.0, True),
    ("A-66", "Mérida", "Sevilla", "pesado_4_mais_eixos", "ES", 195, 0.0, True),
    ("A-66", "Badajoz", "Sevilla", "pesado_4_mais_eixos", "ES", 220, 0.0, True),
    ("A6/A2", "Lisboa", "Madrid", "pesado_4_mais_eixos", "PT", 225, 31.85, False),
    ("A-5", "Lisboa", "Madrid", "pesado_4_mais_eixos", "ES", 400, 0.0, True),
    ("A1/A25", "Porto", "Madrid", "pesado_4_mais_eixos", "PT", 210, 27.40, False),
    ("A-62", "Porto", "Madrid", "pesado_4_mais_eixos", "ES", 350, 0.0, True),
    ("A6/A2", "Lisboa", "Badajoz", "pesado_4_mais_eixos", "PT", 225, 31.85, False),
]

CIDADES = ["Lisboa", "Porto", "Badajoz", "Mérida", "Sevilla", "Madrid"]


class DuckFonte:
    """Fonte de dados DuckDB com a interface do ``SQLAlchemyDataSource``.

    Dialecto Postgres: o DuckDB aceita o SQL que o especialista escreve para
    Postgres (``::date``, ``DATE_TRUNC``, ``FILTER``, ``ILIKE``…).
    """

    dialect = Dialect.POSTGRES

    def __init__(self, conn: duckdb.DuckDBPyConnection, label: str):
        self._conn = conn
        self._lock = threading.Lock()
        self.label = label
        self.sqls: List[str] = []

    def run_query(self, sql: str) -> List[Dict[str, Any]]:
        with self._lock:
            self.sqls.append(sql)
            cur = self._conn.cursor()
            try:
                # Arrow e não fetchall(): TIMESTAMPTZ pelo fetchall exige pytz.
                return cur.execute(sql).to_arrow_table().to_pylist()
            finally:
                cur.close()

    def run_query_arrow(self, sql: str):
        import pyarrow as pa

        rows = self.run_query(sql)
        return pa.Table.from_pylist(rows) if rows else pa.Table.from_pylist([])

    def sample_table_rows(self, table_name: str, limit: int = 3):
        try:
            cur = self._conn.cursor()
            return (
                cur.execute(f"SELECT * FROM {table_name} LIMIT {int(limit)}")
                .to_arrow_table()
                .to_pylist()
            )
        except Exception:
            return []


class DuckFonteMundo(DuckFonte):
    """O mesmo, com a atribuição das fontes da ligação sky-world."""

    sistema = True
    connector_id = "sky-world"

    def atribuicao(self, tabelas):
        from core.data_sources.sky_world import (
            atribuicoes_das_linhas,
            fontes_das_tabelas,
        )

        linhas = self.run_query(
            "SELECT nome, descricao, licenca, atribuicao, dado_de, ultima_actualizacao, estado "
            "FROM mundo.fontes"
        )
        return atribuicoes_das_linhas(linhas, fontes_das_tabelas(tabelas), agora=AGORA)


AGORA = dt.datetime(2026, 10, 13, 12, 0, tzinfo=dt.timezone.utc)


def _viagens() -> List[tuple]:
    rnd = random.Random(20261013)
    linhas = []
    tid = 0
    dia = INICIO
    while dia <= FIM:
        for _ in range(rnd.choice((3, 4, 4, 5, 5))):
            tid += 1
            rota = rnd.choices(ROTAS, weights=(30, 14, 10, 12, 12, 10, 12))[0]
            rid, _, _, km, padrao = rota
            veh = rnd.randint(1, 8)
            drv = rnd.randint(1, 6)
            h = rnd.randint(4, 18)
            partida = dt.datetime(
                dia.year,
                dia.month,
                dia.day,
                h,
                rnd.choice((0, 15, 30, 45)),
                tzinfo=dt.timezone.utc,
            )
            atraso = rnd.randint(-20, 90)
            prevista = partida + dt.timedelta(minutes=padrao)
            chegada = prevista + dt.timedelta(minutes=atraso)
            km_run = km + rnd.randint(0, 12)
            consumo = 0.31 if veh <= 4 else (0.29 if veh <= 6 else 0.11)
            litros = round(km_run * consumo * rnd.uniform(0.93, 1.08), 2)
            horas = round((padrao + atraso) / 60.0 + rnd.uniform(0.2, 0.8), 2)
            estado = "cancelled" if rnd.random() < 0.05 else "completed"
            linhas.append(
                (
                    tid,
                    veh,
                    drv,
                    rid,
                    partida,
                    prevista,
                    chegada,
                    km_run,
                    litros,
                    horas,
                    estado,
                )
            )
        dia += dt.timedelta(days=1)
    return linhas


def _base_cliente() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect(":memory:")
    c.execute("SET TimeZone='UTC'")
    c.execute("CREATE SCHEMA fleet; CREATE SCHEMA ops;")
    c.execute(
        "CREATE TABLE fleet.vehicles (id INT PRIMARY KEY, plate TEXT, model TEXT, class TEXT,"
        " acquired_on DATE, capacity_kg INT, fixed_cost_month DECIMAL(8,2))"
    )
    c.executemany("INSERT INTO fleet.vehicles VALUES (?,?,?,?,?,?,?)", VIATURAS)
    c.execute(
        "CREATE TABLE fleet.drivers (id INT PRIMARY KEY, name TEXT, licence TEXT, hired_on DATE,"
        " cost_per_hour DECIMAL(6,2))"
    )
    c.executemany("INSERT INTO fleet.drivers VALUES (?,?,?,?,?)", MOTORISTAS)
    c.execute(
        "CREATE TABLE ops.routes (id INT PRIMARY KEY, origin TEXT, destination TEXT,"
        " distance_km INT, standard_minutes INT, toll_cost DECIMAL(8,2))"
    )
    c.executemany(
        "INSERT INTO ops.routes VALUES (?,?,?,?,?,?)",
        # A sementeira imputa portagem a TODAS as rotas: km × 0,072 (Anexo C ⚠).
        [(r[0], r[1], r[2], r[3], r[4], round(r[3] * 0.072, 2)) for r in ROTAS],
    )
    c.execute(
        "CREATE TABLE ops.trips (id INT PRIMARY KEY, vehicle_id INT, driver_id INT, route_id INT,"
        " departed_at TIMESTAMPTZ, planned_arrival TIMESTAMPTZ, arrived_at TIMESTAMPTZ, km_run INT,"
        " fuel_litres DECIMAL(8,2), driver_hours DECIMAL(6,2), status TEXT)"
    )
    c.executemany("INSERT INTO ops.trips VALUES (?,?,?,?,?,?,?,?,?,?,?)", _viagens())
    return c


def _base_mundo() -> duckdb.DuckDBPyConnection:
    rnd = random.Random(7)
    c = duckdb.connect(":memory:")
    c.execute("SET TimeZone='UTC'")
    c.execute("CREATE SCHEMA mundo")
    c.execute(
        "CREATE TABLE mundo.fontes (nome TEXT PRIMARY KEY, descricao TEXT, url TEXT, licenca TEXT,"
        " uso_comercial BOOLEAN, atribuicao TEXT, frequencia TEXT, ultima_actualizacao TIMESTAMPTZ,"
        " dado_de TIMESTAMPTZ, linhas INT, estado TEXT, erro TEXT, duracao_ms INT)"
    )
    fontes = [
        (
            "gasolineras",
            "Precio actual por puesto (MITECO)",
            "Reutilização sem autorização expressa (Lei 37/2007)",
            "Fuente: Ministerio para la Transición Ecológica (Geoportal de Gasolineras). Não alterar a data de actualização",
            AGORA - dt.timedelta(minutes=25),
        ),
        (
            "gasoleo_historico",
            "Gasóleo A por província e dia (MITECO)",
            "Idem MITECO",
            "Fuente: Ministerio para la Transición Ecológica",
            AGORA - dt.timedelta(hours=11),
        ),
        (
            "gasoleo_ue",
            "Weekly Oil Bulletin",
            "Reutilização com citação (Decisão 2011/833/UE)",
            "Fonte: Comissão Europeia, Weekly Oil Bulletin",
            AGORA - dt.timedelta(days=1),
        ),
        (
            "festivos",
            "Feriados ES (BOE) e PT (DRE)",
            "BOE — Licencia tipo BOE; DRE",
            "Basado en datos de la Agencia Estatal Boletín Oficial del Estado (boe.es); Fonte: Diário da República",
            AGORA - dt.timedelta(days=3),
        ),
        (
            "portagens",
            "Portagens de referência 2026",
            "Tarifas públicas; compilação própria",
            "Fontes por linha (BOE, Brisa, administracion.gob.es)",
            AGORA - dt.timedelta(days=40),
        ),
        (
            "restricoes",
            "Restrições DGT 2026 a >7.500 kg",
            "BOE: licencia tipo",
            "Basado en datos de la DGT / Agencia Estatal Boletín Oficial del Estado",
            AGORA - dt.timedelta(days=40),
        ),
        # Tempo parado há 2 dias com cadência de 6 h → atrasado (S5).
        (
            "tempo",
            "Previsão diária 7 dias",
            "AEMET · Open-Meteo (subscrição)",
            "Fuente: AEMET · Weather data by Open-Meteo.com (CC BY 4.0)",
            AGORA - dt.timedelta(days=2),
        ),
    ]
    for nome, desc, lic, atr, dado in fontes:
        c.execute(
            "INSERT INTO mundo.fontes VALUES (?,?,?,?,TRUE,?,?,?,?,?, 'ok', NULL, 100)",
            (nome, desc, "https://exemplo", lic, atr, "x", dado, dado, 10),
        )

    c.execute(
        "CREATE TABLE mundo.gasolineras_precio (id_estacion INT PRIMARY KEY, rotulo TEXT, direccion TEXT,"
        " cp TEXT, localidad TEXT, municipio TEXT, provincia TEXT, cod_provincia TEXT, lat DOUBLE,"
        " lon DOUBLE, carretera TEXT, pk DOUBLE, margen TEXT, horario TEXT, tipo_venta TEXT,"
        " precio_gasoleo_a DOUBLE, precio_gasoleo_premium DOUBLE, precio_gasolina_95 DOUBLE,"
        " actualizado_em TIMESTAMPTZ, fonte TEXT, licenca TEXT)"
    )
    postos = []
    corredores = {
        ("Badajoz", "Madrid"): [
            ("BADAJOZ", "Badajoz"),
            ("BADAJOZ", "Mérida"),
            ("CÁCERES", "Trujillo"),
            ("CÁCERES", "Navalmoral de la Mata"),
            ("TOLEDO", "Talavera de la Reina"),
            ("TOLEDO", "Santa Olalla"),
            ("MADRID", "Navalcarnero"),
            ("MADRID", "Móstoles"),
            ("MADRID", "Alcorcón"),
            ("MADRID", "Madrid"),
        ],
        ("Mérida", "Madrid"): [
            ("BADAJOZ", "Mérida"),
            ("CÁCERES", "Trujillo"),
            ("CÁCERES", "Almaraz"),
            ("TOLEDO", "Oropesa"),
            ("TOLEDO", "Talavera de la Reina"),
            ("MADRID", "Móstoles"),
            ("MADRID", "Alcorcón"),
            ("MADRID", "Madrid"),
        ],
        ("Badajoz", "Sevilla"): [
            ("BADAJOZ", "Badajoz"),
            ("BADAJOZ", "Zafra"),
            ("BADAJOZ", "Monesterio"),
            ("SEVILLA", "Santa Olalla del Cala"),
            ("SEVILLA", "Sevilla"),
        ],
        ("Mérida", "Sevilla"): [
            ("BADAJOZ", "Mérida"),
            ("BADAJOZ", "Zafra"),
            ("SEVILLA", "El Ronquillo"),
            ("SEVILLA", "Sevilla"),
        ],
        ("Lisboa", "Madrid"): [
            ("BADAJOZ", "Badajoz"),
            ("BADAJOZ", "Mérida"),
            ("CÁCERES", "Trujillo"),
            ("TOLEDO", "Talavera de la Reina"),
            ("MADRID", "Móstoles"),
            ("MADRID", "Madrid"),
        ],
    }
    rota_linhas = []
    pid = 1000
    for (o, d), lista in corredores.items():
        for k, (prov, mun) in enumerate(lista):
            pid += 1
            preco = round(rnd.uniform(1.389, 1.619), 3)
            postos.append(
                (
                    pid,
                    rnd.choice(
                        ["REPSOL", "CEPSA", "GALP", "BP", "PLENOIL", "BALLENOIL"]
                    ),
                    f"A-5 km {k*40}",
                    "06000",
                    mun,
                    mun,
                    prov,
                    "06",
                    38.8 + k * 0.1,
                    -6.9 + k * 0.3,
                    "A-5",
                    k * 40.0,
                    "D",
                    "L-D: 24H",
                    "P",
                    preco,
                    round(preco + 0.08, 3),
                    round(preco + 0.05, 3),
                    AGORA - dt.timedelta(minutes=25),
                    "MITECO",
                    "MITECO — reutilização (Lei 37/2007, RD 1495/2011)",
                )
            )
            dist = round(rnd.uniform(0.2, 4.9), 2)
            rota_linhas.append(
                (
                    o,
                    d,
                    pid,
                    dist,
                    k * 40.0,
                    AGORA - dt.timedelta(days=5),
                    "MITECO + traçado",
                    "MITECO",
                )
            )
    c.executemany(
        "INSERT INTO mundo.gasolineras_precio VALUES (" + ",".join("?" * 21) + ")",
        postos,
    )
    c.execute(
        "CREATE TABLE mundo.gasolineras_rota (origem TEXT, destino TEXT, id_estacion INT, dist_km DOUBLE,"
        " km_desde_origem DOUBLE, calculado_em TIMESTAMPTZ, fonte TEXT, licenca TEXT)"
    )
    c.executemany(
        "INSERT INTO mundo.gasolineras_rota VALUES (?,?,?,?,?,?,?,?)", rota_linhas
    )

    c.execute(
        "CREATE TABLE mundo.gasoleo_historico_diario (data DATE, provincia TEXT, n_postos INT,"
        " minimo DOUBLE, media DOUBLE, mediana DOUBLE, maximo DOUBLE, origem TEXT, fonte TEXT, licenca TEXT)"
    )
    hist = []
    dia = dt.date(2026, 6, 1)
    base = {"BADAJOZ": 1.452, "MADRID": 1.497, "ESPAÑA": 1.481}
    while dia <= dt.date(2026, 10, 12):
        tendencia = (dia - dt.date(2026, 6, 1)).days * 0.0006
        for prov, b in base.items():
            media = round(b + tendencia + rnd.uniform(-0.012, 0.012), 3)
            hist.append(
                (
                    dia,
                    prov,
                    300,
                    round(media - 0.09, 3),
                    media,
                    media,
                    round(media + 0.12, 3),
                    "historico",
                    "MITECO",
                    "MITECO — reutilização (Lei 37/2007, RD 1495/2011)",
                )
            )
        dia += dt.timedelta(days=1)
    c.executemany(
        "INSERT INTO mundo.gasoleo_historico_diario VALUES (?,?,?,?,?,?,?,?,?,?)", hist
    )

    c.execute(
        "CREATE TABLE mundo.gasoleo_ue_semanal (data DATE, pais TEXT, gasoleo_eur_l DOUBLE,"
        " gasolina95_eur_l DOUBLE, fonte TEXT, licenca TEXT)"
    )
    ue = []
    seg = dt.date(2026, 7, 6)
    while seg <= dt.date(2026, 10, 5):
        es = round(1.47 + rnd.uniform(-0.02, 0.03), 3)
        pt = round(es + 0.19 + rnd.uniform(0.0, 0.05), 3)
        for pais, v in (("ES", es), ("PT", pt), ("EU", round(es + 0.12, 3))):
            ue.append(
                (
                    seg,
                    pais,
                    v,
                    round(v + 0.11, 3),
                    "Weekly Oil Bulletin",
                    "Comissão Europeia",
                )
            )
        seg += dt.timedelta(days=7)
    c.executemany("INSERT INTO mundo.gasoleo_ue_semanal VALUES (?,?,?,?,?,?)", ue)

    c.execute(
        "CREATE TABLE mundo.festivos (chave TEXT PRIMARY KEY, data DATE, pais TEXT, regiao TEXT, nome TEXT,"
        " nome_en TEXT, dia_semana TEXT, nota TEXT, fonte TEXT, licenca TEXT)"
    )
    c.executemany(
        "INSERT INTO mundo.festivos VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            (
                f"{p}|{r or 'NAC'}|{d}",
                d,
                p,
                r,
                n,
                None,
                None,
                None,
                "BOE / DRE",
                "BOE — Licencia tipo BOE",
            )
            for (d, p, r, n) in FESTIVOS
        ],
    )

    c.execute(
        "CREATE TABLE mundo.portagens (corredor TEXT, origem TEXT, destino TEXT, classe TEXT, pais TEXT,"
        " km DOUBLE, preco_eur DOUBLE, gratuita BOOLEAN, rota_demo BOOLEAN, valido_de DATE, fonte TEXT,"
        " nota TEXT, licenca TEXT)"
    )
    c.executemany(
        "INSERT INTO mundo.portagens VALUES (?,?,?,?,?,?,?,?,TRUE,DATE '2026-01-01','BOE / Brisa',NULL,"
        "'Tarifas públicas')",
        PORTAGENS,
    )

    c.execute(
        "CREATE TABLE mundo.restricoes_pesados (data DATE, carretera TEXT, pk_inicio DOUBLE, pk_fim DOUBLE,"
        " sentido TEXT, hora_inicio TEXT, hora_fim TEXT, troco TEXT, ambito TEXT, motivo TEXT,"
        " valido_de DATE, valido_ate DATE, confianca TEXT, fonte TEXT, nota TEXT, licenca TEXT)"
    )
    c.executemany(
        "INSERT INTO mundo.restricoes_pesados VALUES (?,?,?,?,?,?,?,'troço','>7.500 kg','operação especial',"
        "DATE '2026-01-01',DATE '2026-12-31','lido_no_pdf','DGT/BOE',NULL,'BOE: licencia tipo')",
        RESTRICOES,
    )

    c.execute(
        "CREATE TABLE mundo.tempo_cidades (cidade TEXT, data DATE, pais TEXT, lat DOUBLE, lon DOUBLE,"
        " temp_min DOUBLE, temp_max DOUBLE, precipitacao_mm DOUBLE, vento_max_kmh DOUBLE,"
        " rajada_max_kmh DOUBLE, codigo INT, descricao TEXT, actualizado_em TIMESTAMPTZ, licenca TEXT, fonte TEXT)"
    )
    tempo = []
    for cid in CIDADES:
        for k in range(7):
            d = dt.date(2026, 10, 13) + dt.timedelta(days=k)
            rajada = round(rnd.uniform(20, 75), 1)
            tempo.append(
                (
                    cid,
                    d,
                    "PT" if cid in ("Lisboa", "Porto") else "ES",
                    0.0,
                    0.0,
                    11.0,
                    22.0,
                    round(rnd.uniform(0, 12), 1),
                    round(rajada * 0.6, 1),
                    rajada,
                    3,
                    "nublado",
                    AGORA - dt.timedelta(days=2),
                    "AEMET",
                    "AEMET",
                )
            )
    c.executemany(
        "INSERT INTO mundo.tempo_cidades VALUES (" + ",".join("?" * 15) + ")", tempo
    )
    return c


def _col(nome, tipo, desc=None):
    d = {"name": nome, "type": tipo}
    if desc:
        d["description"] = desc
    return d


def tabelas() -> List[TableSchema]:
    """O catálogo como o agente o recebe (nomes, tipos e descrições reais)."""
    C, M = LIGACAO_CLIENTE, LIGACAO_MUNDO
    t = TableSchema
    return [
        t(
            "vehicles",
            "fleet.vehicles",
            "Viaturas da frota",
            [
                _col("id", "integer"),
                _col("plate", "text", "Matrícula"),
                _col("model", "text"),
                _col("class", "text", "semirremolque | frigorífico | ligero"),
                _col("acquired_on", "date"),
                _col("capacity_kg", "integer"),
                _col("fixed_cost_month", "numeric", "Custo fixo mensal €"),
            ],
            C,
        ),
        t(
            "drivers",
            "fleet.drivers",
            "Motoristas",
            [
                _col("id", "integer"),
                _col("name", "text"),
                _col("licence", "text"),
                _col("hired_on", "date"),
                _col("cost_per_hour", "numeric", "Custo por hora do motorista, €"),
            ],
            C,
        ),
        t(
            "routes",
            "ops.routes",
            "Rotas origem–destino",
            [
                _col("id", "integer"),
                _col("origin", "text", "Cidade de origem"),
                _col("destination", "text", "Cidade de destino"),
                _col("distance_km", "integer"),
                _col("standard_minutes", "integer"),
                _col("toll_cost", "numeric", "Portagem imputada por viagem, €"),
            ],
            C,
        ),
        t(
            "trips",
            "ops.trips",
            "Viagens (uma por saída)",
            [
                _col("id", "integer"),
                _col("vehicle_id", "integer", "FK fleet.vehicles.id"),
                _col("driver_id", "integer", "FK fleet.drivers.id"),
                _col("route_id", "integer", "FK ops.routes.id"),
                _col("departed_at", "timestamptz", "Hora de partida"),
                _col("planned_arrival", "timestamptz"),
                _col("arrived_at", "timestamptz"),
                _col("km_run", "integer"),
                _col("fuel_litres", "numeric", "Litros de gasóleo"),
                _col("driver_hours", "numeric", "Horas de motorista"),
                _col("status", "text", "completed | cancelled"),
            ],
            C,
        ),
        t(
            "gasolineras_precio",
            "mundo.gasolineras_precio",
            "Postos de combustível de Espanha (MITECO), preço actual",
            [
                _col("id_estacion", "integer", "IDEESS do MITECO"),
                _col("rotulo", "text"),
                _col("municipio", "text"),
                _col("provincia", "text", "Província (maiúsculas, como no MITECO)"),
                _col("carretera", "text"),
                _col("precio_gasoleo_a", "numeric", "Gasóleo A, €/l, preço de bomba"),
                _col("actualizado_em", "timestamptz"),
                _col("fonte", "text"),
                _col("licenca", "text"),
            ],
            M,
        ),
        t(
            "gasolineras_rota",
            "mundo.gasolineras_rota",
            "Postos espanhóis a ≤5 km do traçado de cada rota da demo",
            [
                _col("origem", "text", "Cidade de origem (= ops.routes.origin)"),
                _col("destino", "text", "Cidade de destino (= ops.routes.destination)"),
                _col("id_estacion", "integer", "FK gasolineras_precio.id_estacion"),
                _col(
                    "dist_km",
                    "numeric",
                    "Distância do posto ao traçado da rota (km, até 5)",
                ),
                _col("km_desde_origem", "numeric"),
            ],
            M,
        ),
        t(
            "gasoleo_historico_diario",
            "mundo.gasoleo_historico_diario",
            "Gasóleo A por província e dia (MITECO)",
            [
                _col("data", "date"),
                _col("provincia", "text", "Província em maiúsculas; ESPAÑA = total"),
                _col("n_postos", "integer"),
                _col("minimo", "numeric"),
                _col("media", "numeric", "Gasóleo A, média simples, €/l"),
                _col("mediana", "numeric"),
                _col("maximo", "numeric"),
            ],
            M,
        ),
        t(
            "gasoleo_ue_semanal",
            "mundo.gasoleo_ue_semanal",
            "Weekly Oil Bulletin: médias nacionais semanais ES/PT/EU",
            [
                _col("data", "date", "Segunda-feira de referência do boletim"),
                _col("pais", "text", "ES | PT | EU"),
                _col(
                    "gasoleo_eur_l",
                    "numeric",
                    "Gasóleo rodoviário, média nacional com impostos, €/l",
                ),
                _col("gasolina95_eur_l", "numeric"),
            ],
            M,
        ),
        t(
            "festivos",
            "mundo.festivos",
            "Feriados nacionais e regionais ES (BOE) e nacionais PT",
            [
                _col("chave", "text"),
                _col("data", "date"),
                _col("pais", "text", "ES | PT"),
                _col("regiao", "text", "ISO 3166-2 (ES-EX, ES-MD…); NULL = nacional"),
                _col("nome", "text"),
            ],
            M,
        ),
        t(
            "portagens",
            "mundo.portagens",
            "Portagens de referência (tarifas 2026)",
            [
                _col("corredor", "text"),
                _col("origem", "text"),
                _col("destino", "text"),
                _col(
                    "classe", "text", "ligeiro | pesado_2_3_eixos | pesado_4_mais_eixos"
                ),
                _col("pais", "text"),
                _col("km", "numeric"),
                _col("preco_eur", "numeric"),
                _col("gratuita", "boolean", "True se o troço não tem portagem"),
            ],
            M,
        ),
        t(
            "restricoes_pesados",
            "mundo.restricoes_pesados",
            "Restrições DGT 2026 a >7.500 kg",
            [
                _col("data", "date"),
                _col("carretera", "text"),
                _col("pk_inicio", "numeric"),
                _col("pk_fim", "numeric"),
                _col("sentido", "text"),
                _col("hora_inicio", "text"),
                _col("hora_fim", "text"),
            ],
            M,
        ),
        t(
            "tempo_cidades",
            "mundo.tempo_cidades",
            "Previsão diária 7 dias nas cidades das rotas",
            [
                _col("cidade", "text", "= ops.routes.origin/destination"),
                _col("data", "date"),
                _col("pais", "text"),
                _col("temp_min", "numeric"),
                _col("temp_max", "numeric"),
                _col("precipitacao_mm", "numeric"),
                _col("vento_max_kmh", "numeric"),
                _col("rajada_max_kmh", "numeric"),
            ],
            M,
        ),
    ]


class Ambiente:
    """As duas bases + o catálogo + o dispatch_map, prontos a usar."""

    def __init__(self):
        self.cliente = _base_cliente()
        self.mundo = _base_mundo()
        self.fonte_cliente = DuckFonte(self.cliente, "Operaciones (postgres)")
        self.fonte_mundo = DuckFonteMundo(self.mundo, "Dados públicos (sky-world)")
        self.dispatch_map = {
            LIGACAO_CLIENTE: self.fonte_cliente,
            LIGACAO_MUNDO: self.fonte_mundo,
        }
        self.config = AgentConfig(
            id="portao", name="portao", tables=tabelas(), dialect=Dialect.POSTGRES
        )

    def esperado(self, sql: str) -> List[Dict[str, Any]]:
        """Corre o SQL escrito à mão com as DUAS bases à vista (só para o gabarito)."""
        g = duckdb.connect(":memory:")
        g.execute("SET TimeZone='UTC'")
        for nome, conn in (("cli", self.cliente), ("mun", self.mundo)):
            for schema, tabela in conn.execute(
                "SELECT table_schema, table_name FROM information_schema.tables"
            ).fetchall():
                df = conn.execute(f"SELECT * FROM {schema}.{tabela}").to_arrow_table()
                g.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
                g.register(f"_{nome}_{tabela}", df)
                g.execute(
                    f"CREATE TABLE {schema}.{tabela} AS SELECT * FROM _{nome}_{tabela}"
                )
        return g.execute(sql).to_arrow_table().to_pylist()
