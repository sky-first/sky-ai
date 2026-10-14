# -*- coding: utf-8 -*-
"""As 10 perguntas mistas do portão (Anexo C do ESTUDO_DADOS_PUBLICOS e §4 do
DADOS_EXTERNOS_COMERCIAL, adaptadas aos dados de demonstração).

Cada pergunta tem:

- ``texto`` — como o cliente a faria (castelhano, o projecto é «Logística y
  Transporte»);
- ``tabelas`` — o que um orquestrador competente escolhe (cliente + mundo);
- ``esperado_sql`` — o número certo, em SQL escrito à mão com as DUAS bases
  à vista (o gabarito; o motor nunca tem as duas bases juntas);
- ``verificar`` — as colunas do gabarito que a resposta tem de conter;
- receitas do ORÁCULO (ver ``oraculo.py``): o SQL que um modelo competente
  escreveria com o que o prompt lhe mostra — por ligação (arquitectura nova)
  e por tabela (arquitectura antiga, a de ``origin/main`` a 13/10/2026).
  ``{t:coluna}`` é substituído pelo ``dataset_i`` que tem essa coluna.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

JANELA = (
    "t.status = 'completed' AND t.departed_at >= TIMESTAMPTZ '2025-10-01 00:00:00+00' "
    "AND t.departed_at < TIMESTAMPTZ '2026-10-01 00:00:00+00'"
)
SETEMBRO = (
    "t.status = 'completed' AND t.departed_at >= TIMESTAMPTZ '2026-09-01 00:00:00+00' "
    "AND t.departed_at < TIMESTAMPTZ '2026-10-01 00:00:00+00'"
)
JANELA_SEM_ALIAS = JANELA.replace("t.", "")
SETEMBRO_SEM_ALIAS = SETEMBRO.replace("t.", "")
NORM = "lower(strip_accents({}))"


def _eq(a: str, b: str) -> str:
    return f"{NORM.format(a)} = {NORM.format(b)}"


@dataclass
class Pergunta:
    id: str
    texto: str
    tabelas: List[str]
    esperado_sql: str
    verificar: List[str]
    fatias: Dict[str, str] = field(default_factory=dict)  # "cliente" | "mundo" → SQL
    merger: str = ""
    por_tabela: Dict[str, str] = field(default_factory=dict)  # tabela → SQL
    merger_por_tabela: str = ""
    nota: str = ""


PERGUNTAS: List[Pergunta] = [
    Pergunta(
        id="P1",
        texto=(
            "¿Cuánto nos habríamos ahorrado en septiembre de 2026 en la ruta Badajoz–Madrid "
            "repostando en el surtidor más barato a menos de 3 km de la ruta, frente al precio "
            "medio de septiembre en la provincia de Badajoz?"
        ),
        tabelas=[
            "trips",
            "routes",
            "gasolineras_rota",
            "gasolineras_precio",
            "gasoleo_historico_diario",
        ],
        esperado_sql=f"""
            WITH l AS (SELECT SUM(t.fuel_litres) AS litros FROM ops.trips t JOIN ops.routes r ON r.id = t.route_id
                       WHERE r.origin = 'Badajoz' AND r.destination = 'Madrid' AND {SETEMBRO}),
                 m AS (SELECT AVG(media) AS media FROM mundo.gasoleo_historico_diario
                       WHERE provincia = 'BADAJOZ' AND data BETWEEN DATE '2026-09-01' AND DATE '2026-09-30'),
                 b AS (SELECT MIN(p.precio_gasoleo_a) AS minimo FROM mundo.gasolineras_rota g
                       JOIN mundo.gasolineras_precio p ON p.id_estacion = g.id_estacion
                       WHERE g.origem = 'Badajoz' AND g.destino = 'Madrid' AND g.dist_km < 3)
            SELECT ROUND(l.litros * (m.media - b.minimo), 2) AS ahorro FROM l, m, b""",
        verificar=["ahorro"],
        fatias={
            "cliente": f"""SELECT r.origin, r.destination, SUM(t.fuel_litres) AS litros
                FROM ops.trips t JOIN ops.routes r ON r.id = t.route_id
                WHERE r.origin = 'Badajoz' AND r.destination = 'Madrid' AND {SETEMBRO}
                GROUP BY r.origin, r.destination""",
            "mundo": """SELECT g.origem, g.destino, MIN(p.precio_gasoleo_a) AS precio_minimo,
                (SELECT AVG(h.media) FROM mundo.gasoleo_historico_diario h WHERE h.provincia = 'BADAJOZ'
                   AND h.data BETWEEN DATE '2026-09-01' AND DATE '2026-09-30') AS media_badajoz
                FROM mundo.gasolineras_rota g JOIN mundo.gasolineras_precio p ON p.id_estacion = g.id_estacion
                WHERE g.origem = 'Badajoz' AND g.destino = 'Madrid' AND g.dist_km < 3
                GROUP BY g.origem, g.destino""",
        },
        merger=(
            "SELECT ROUND(a.litros * (b.media_badajoz - b.precio_minimo), 2) AS ahorro "
            "FROM {t:litros} a JOIN {t:precio_minimo} b ON "
            + _eq("a.origin", "b.origem")
            + " AND "
            + _eq("a.destination", "b.destino")
        ),
        por_tabela={
            "trips": f"SELECT route_id, SUM(fuel_litres) AS litros FROM ops.trips WHERE {SETEMBRO_SEM_ALIAS} GROUP BY route_id",
            "routes": "SELECT id, origin, destination FROM ops.routes",
            "gasolineras_rota": "SELECT origem, destino, id_estacion, dist_km FROM mundo.gasolineras_rota WHERE dist_km < 3",
            "gasolineras_precio": "SELECT id_estacion, precio_gasoleo_a FROM mundo.gasolineras_precio",
            "gasoleo_historico_diario": "SELECT data, media FROM mundo.gasoleo_historico_diario WHERE provincia = 'BADAJOZ' AND data BETWEEN DATE '2026-09-01' AND DATE '2026-09-30'",
        },
        merger_por_tabela=(
            "WITH l AS (SELECT SUM(t.litros) AS litros FROM {t:litros} t JOIN {t:origin} r ON r.id = t.route_id "
            "WHERE r.origin = 'Badajoz' AND r.destination = 'Madrid'), "
            "b AS (SELECT MIN(p.precio_gasoleo_a) AS minimo FROM {t:dist_km} g JOIN {t:precio_gasoleo_a} p "
            "ON p.id_estacion = g.id_estacion WHERE g.origem = 'Badajoz' AND g.destino = 'Madrid'), "
            "m AS (SELECT AVG(media) AS media FROM {t:media}) "
            "SELECT ROUND(l.litros * (m.media - b.minimo), 2) AS ahorro FROM l, b, m"
        ),
        nota="Pergunta-estrela do Anexo C (C.6 #1).",
    ),
    Pergunta(
        id="P2",
        texto=(
            "¿Cuántos litros consumieron en septiembre de 2026 nuestros viajes completados con destino "
            "Madrid y cuánto costarían al precio medio del gasóleo en la provincia de Madrid del día de salida?"
        ),
        tabelas=["trips", "routes", "gasoleo_historico_diario"],
        esperado_sql=f"""
            SELECT ROUND(SUM(t.fuel_litres), 2) AS litros, ROUND(SUM(t.fuel_litres * h.media), 2) AS coste
            FROM ops.trips t JOIN ops.routes r ON r.id = t.route_id
            JOIN mundo.gasoleo_historico_diario h ON h.provincia = 'MADRID' AND h.data = CAST(t.departed_at AS DATE)
            WHERE r.destination = 'Madrid' AND {SETEMBRO}""",
        verificar=["coste"],
        fatias={
            "cliente": f"""SELECT CAST(t.departed_at AS DATE) AS dia, SUM(t.fuel_litres) AS litros
                FROM ops.trips t JOIN ops.routes r ON r.id = t.route_id
                WHERE r.destination = 'Madrid' AND {SETEMBRO} GROUP BY 1""",
            "mundo": """SELECT data, media FROM mundo.gasoleo_historico_diario
                WHERE provincia = 'MADRID' AND data BETWEEN DATE '2026-09-01' AND DATE '2026-09-30'""",
        },
        merger=(
            "SELECT ROUND(SUM(a.litros), 2) AS litros, ROUND(SUM(a.litros * b.media), 2) AS coste "
            "FROM {t:litros} a JOIN {t:media} b ON CAST(a.dia AS DATE) = CAST(b.data AS DATE)"
        ),
        por_tabela={
            "trips": f"SELECT route_id, CAST(departed_at AS DATE) AS dia, SUM(fuel_litres) AS litros FROM ops.trips WHERE {SETEMBRO_SEM_ALIAS} GROUP BY 1, 2",
            "routes": "SELECT id, origin, destination FROM ops.routes",
            "gasoleo_historico_diario": "SELECT data, media FROM mundo.gasoleo_historico_diario WHERE provincia = 'MADRID' AND data BETWEEN DATE '2026-09-01' AND DATE '2026-09-30'",
        },
        merger_por_tabela=(
            "SELECT ROUND(SUM(t.litros), 2) AS litros, ROUND(SUM(t.litros * h.media), 2) AS coste "
            "FROM {t:litros} t JOIN {t:origin} r ON r.id = t.route_id JOIN {t:media} h "
            "ON CAST(h.data AS DATE) = CAST(t.dia AS DATE) WHERE r.destination = 'Madrid'"
        ),
    ),
    Pergunta(
        id="P3",
        texto=(
            "¿Cuánto imputamos en peajes entre octubre de 2025 y septiembre de 2026 en viajes completados "
            "por rutas cuyo recorrido no tiene peaje según la tarifa pública para camiones de 4 o más ejes?"
        ),
        tabelas=["trips", "routes", "portagens"],
        esperado_sql=f"""
            WITH libres AS (SELECT origem, destino FROM mundo.portagens WHERE classe = 'pesado_4_mais_eixos'
                            GROUP BY 1, 2 HAVING bool_and(gratuita))
            SELECT ROUND(SUM(r.toll_cost), 2) AS imputado FROM ops.trips t JOIN ops.routes r ON r.id = t.route_id
            JOIN libres l ON l.origem = r.origin AND l.destino = r.destination WHERE {JANELA}""",
        verificar=["imputado"],
        fatias={
            "cliente": f"""SELECT r.origin, r.destination, COUNT(*) AS viajes, SUM(r.toll_cost) AS peaje_imputado
                FROM ops.trips t JOIN ops.routes r ON r.id = t.route_id WHERE {JANELA}
                GROUP BY r.origin, r.destination""",
            "mundo": """SELECT origem, destino, bool_and(gratuita) AS gratuita FROM mundo.portagens
                WHERE classe = 'pesado_4_mais_eixos' GROUP BY origem, destino""",
        },
        merger=(
            "SELECT ROUND(SUM(a.peaje_imputado), 2) AS imputado FROM {t:peaje_imputado} a JOIN {t:gratuita} b ON "
            + _eq("a.origin", "b.origem")
            + " AND "
            + _eq("a.destination", "b.destino")
            + " WHERE b.gratuita"
        ),
        por_tabela={
            "trips": f"SELECT route_id, COUNT(*) AS viajes FROM ops.trips WHERE {JANELA_SEM_ALIAS} GROUP BY route_id",
            "routes": "SELECT id, origin, destination, toll_cost FROM ops.routes",
            "portagens": "SELECT origem, destino, gratuita FROM mundo.portagens WHERE classe = 'pesado_4_mais_eixos'",
        },
        merger_por_tabela=(
            "WITH libres AS (SELECT origem, destino FROM {t:gratuita} GROUP BY 1, 2 HAVING bool_and(gratuita)) "
            "SELECT ROUND(SUM(v.viajes * r.toll_cost), 2) AS imputado FROM {t:viajes} v JOIN {t:toll_cost} r "
            "ON r.id = v.route_id JOIN libres l ON l.origem = r.origin AND l.destino = r.destination"
        ),
        nota="Anexo C #4: a sementeira imputa portagem a corredores gratuitos (A-5, A-66).",
    ),
    Pergunta(
        id="P4",
        texto=(
            "¿Cuántos viajes completados salieron en un festivo nacional de España entre octubre de 2025 "
            "y septiembre de 2026, y cuántas horas de conductor sumaron?"
        ),
        tabelas=["trips", "festivos"],
        esperado_sql=f"""
            SELECT COUNT(*) AS viajes, ROUND(SUM(t.driver_hours), 2) AS horas FROM ops.trips t
            JOIN mundo.festivos f ON f.data = CAST(t.departed_at AS DATE) AND f.pais = 'ES' AND f.regiao IS NULL
            WHERE {JANELA}""",
        verificar=["viajes", "horas"],
        fatias={
            "cliente": f"""SELECT CAST(t.departed_at AS DATE) AS dia, COUNT(*) AS viajes, SUM(t.driver_hours) AS horas
                FROM ops.trips t WHERE {JANELA} GROUP BY 1""",
            "mundo": "SELECT data FROM mundo.festivos WHERE pais = 'ES' AND regiao IS NULL",
        },
        merger=(
            "SELECT SUM(a.viajes) AS viajes, ROUND(SUM(a.horas), 2) AS horas FROM {t:viajes} a "
            "JOIN {t:data} b ON CAST(a.dia AS DATE) = CAST(b.data AS DATE)"
        ),
        por_tabela={
            "trips": f"SELECT CAST(departed_at AS DATE) AS dia, COUNT(*) AS viajes, SUM(driver_hours) AS horas FROM ops.trips WHERE {JANELA_SEM_ALIAS} GROUP BY 1",
            "festivos": "SELECT data FROM mundo.festivos WHERE pais = 'ES' AND regiao IS NULL",
        },
        merger_por_tabela=(
            "SELECT SUM(a.viajes) AS viajes, ROUND(SUM(a.horas), 2) AS horas FROM {t:viajes} a "
            "JOIN {t:data} b ON CAST(a.dia AS DATE) = CAST(b.data AS DATE)"
        ),
        nota="Anexo C #6. A fatia do cliente ao grão do dia tem ~365 linhas.",
    ),
    Pergunta(
        id="P5",
        texto=(
            "¿Cuánto nos costaron en horas de conductor (horas por coste por hora del conductor) los viajes "
            "completados que salieron en festivo nacional de España entre octubre de 2025 y septiembre de 2026?"
        ),
        tabelas=["trips", "drivers", "festivos"],
        esperado_sql=f"""
            SELECT ROUND(SUM(t.driver_hours * d.cost_per_hour), 2) AS coste FROM ops.trips t
            JOIN fleet.drivers d ON d.id = t.driver_id
            JOIN mundo.festivos f ON f.data = CAST(t.departed_at AS DATE) AND f.pais = 'ES' AND f.regiao IS NULL
            WHERE {JANELA}""",
        verificar=["coste"],
        fatias={
            "cliente": f"""SELECT CAST(t.departed_at AS DATE) AS dia, SUM(t.driver_hours * d.cost_per_hour) AS coste_conductor
                FROM ops.trips t JOIN fleet.drivers d ON d.id = t.driver_id WHERE {JANELA} GROUP BY 1""",
            "mundo": "SELECT data FROM mundo.festivos WHERE pais = 'ES' AND regiao IS NULL",
        },
        merger=(
            "SELECT ROUND(SUM(a.coste_conductor), 2) AS coste FROM {t:coste_conductor} a "
            "JOIN {t:data} b ON CAST(a.dia AS DATE) = CAST(b.data AS DATE)"
        ),
        por_tabela={
            "trips": f"SELECT CAST(departed_at AS DATE) AS dia, driver_id, SUM(driver_hours) AS horas FROM ops.trips WHERE {JANELA_SEM_ALIAS} GROUP BY 1, 2",
            "drivers": "SELECT id, cost_per_hour FROM fleet.drivers",
            "festivos": "SELECT data FROM mundo.festivos WHERE pais = 'ES' AND regiao IS NULL",
        },
        merger_por_tabela=(
            "SELECT ROUND(SUM(t.horas * d.cost_per_hour), 2) AS coste FROM {t:horas} t "
            "JOIN {t:cost_per_hour} d ON d.id = t.driver_id JOIN {t:data} f ON CAST(f.data AS DATE) = CAST(t.dia AS DATE)"
        ),
        nota="Anexo C #6 (custo). trips × drivers é da mesma ligação.",
    ),
    Pergunta(
        id="P6",
        texto=(
            "¿Cuántos viajes completados salieron de Badajoz o de Mérida en un festivo regional de "
            "Extremadura entre octubre de 2025 y septiembre de 2026?"
        ),
        tabelas=["trips", "routes", "festivos"],
        esperado_sql=f"""
            SELECT COUNT(*) AS viajes FROM ops.trips t JOIN ops.routes r ON r.id = t.route_id
            JOIN mundo.festivos f ON f.data = CAST(t.departed_at AS DATE) AND f.regiao = 'ES-EX'
            WHERE r.origin IN ('Badajoz', 'Mérida') AND {JANELA}""",
        verificar=["viajes"],
        fatias={
            "cliente": f"""SELECT CAST(t.departed_at AS DATE) AS dia, COUNT(*) AS viajes
                FROM ops.trips t JOIN ops.routes r ON r.id = t.route_id
                WHERE r.origin IN ('Badajoz', 'Mérida') AND {JANELA} GROUP BY 1""",
            "mundo": "SELECT data FROM mundo.festivos WHERE regiao = 'ES-EX'",
        },
        merger=(
            "SELECT SUM(a.viajes) AS viajes FROM {t:viajes} a JOIN {t:data} b ON CAST(a.dia AS DATE) = CAST(b.data AS DATE)"
        ),
        por_tabela={
            "trips": f"SELECT route_id, CAST(departed_at AS DATE) AS dia, COUNT(*) AS viajes FROM ops.trips WHERE {JANELA_SEM_ALIAS} GROUP BY 1, 2",
            "routes": "SELECT id, origin FROM ops.routes",
            "festivos": "SELECT data FROM mundo.festivos WHERE regiao = 'ES-EX'",
        },
        merger_por_tabela=(
            "SELECT SUM(t.viajes) AS viajes FROM {t:viajes} t JOIN {t:origin} r ON r.id = t.route_id "
            "JOIN {t:data} f ON CAST(f.data AS DATE) = CAST(t.dia AS DATE) WHERE r.origin IN ('Badajoz', 'Mérida')"
        ),
    ),
    Pergunta(
        id="P7",
        texto=(
            "¿Cuántos viajes completados de semirremolque con destino Madrid salieron en un día con "
            "restricción de la DGT para camiones en la A-5, entre octubre de 2025 y septiembre de 2026?"
        ),
        tabelas=["trips", "vehicles", "routes", "restricoes_pesados"],
        esperado_sql=f"""
            SELECT COUNT(*) AS viajes FROM ops.trips t JOIN fleet.vehicles v ON v.id = t.vehicle_id
            JOIN ops.routes r ON r.id = t.route_id
            WHERE v.class = 'semirremolque' AND r.destination = 'Madrid' AND {JANELA}
              AND CAST(t.departed_at AS DATE) IN (SELECT data FROM mundo.restricoes_pesados WHERE carretera = 'A-5')""",
        verificar=["viajes"],
        fatias={
            "cliente": f"""SELECT CAST(t.departed_at AS DATE) AS dia, COUNT(*) AS viajes
                FROM ops.trips t JOIN fleet.vehicles v ON v.id = t.vehicle_id JOIN ops.routes r ON r.id = t.route_id
                WHERE v.class = 'semirremolque' AND r.destination = 'Madrid' AND {JANELA} GROUP BY 1""",
            "mundo": "SELECT DISTINCT data FROM mundo.restricoes_pesados WHERE carretera = 'A-5'",
        },
        merger=(
            "SELECT SUM(a.viajes) AS viajes FROM {t:viajes} a JOIN {t:data} b ON CAST(a.dia AS DATE) = CAST(b.data AS DATE)"
        ),
        por_tabela={
            "trips": f"SELECT vehicle_id, route_id, CAST(departed_at AS DATE) AS dia, COUNT(*) AS viajes FROM ops.trips WHERE {JANELA_SEM_ALIAS} GROUP BY 1, 2, 3",
            "vehicles": "SELECT id, class FROM fleet.vehicles",
            "routes": "SELECT id, destination FROM ops.routes",
            "restricoes_pesados": "SELECT DISTINCT data, carretera FROM mundo.restricoes_pesados WHERE carretera = 'A-5'",
        },
        merger_por_tabela=(
            "SELECT SUM(t.viajes) AS viajes FROM {t:vehicle_id} t JOIN {t:class} v ON v.id = t.vehicle_id "
            "JOIN {t:destination} r ON r.id = t.route_id WHERE v.class = 'semirremolque' AND r.destination = 'Madrid' "
            "AND CAST(t.dia AS DATE) IN (SELECT CAST(data AS DATE) FROM {t:carretera})"
        ),
        nota="Anexo C #7 (restrições DGT a >7,5 t).",
    ),
    Pergunta(
        id="P8",
        texto=(
            "¿Cuánto subió el precio medio del gasóleo en la provincia de Badajoz de julio a septiembre de 2026 "
            "y cuánto nos costaría esa subida en un mes con los litros de septiembre de las rutas que salen de Badajoz?"
        ),
        tabelas=["trips", "routes", "gasoleo_historico_diario"],
        esperado_sql=f"""
            WITH s AS (SELECT AVG(media) AS m FROM mundo.gasoleo_historico_diario WHERE provincia = 'BADAJOZ'
                       AND data BETWEEN DATE '2026-09-01' AND DATE '2026-09-30'),
                 j AS (SELECT AVG(media) AS m FROM mundo.gasoleo_historico_diario WHERE provincia = 'BADAJOZ'
                       AND data BETWEEN DATE '2026-07-01' AND DATE '2026-07-31'),
                 l AS (SELECT SUM(t.fuel_litres) AS litros FROM ops.trips t JOIN ops.routes r ON r.id = t.route_id
                       WHERE r.origin = 'Badajoz' AND {SETEMBRO})
            SELECT ROUND(s.m - j.m, 4) AS subida, ROUND((s.m - j.m) * l.litros, 2) AS coste_mes FROM s, j, l""",
        verificar=["coste_mes"],
        fatias={
            "cliente": f"""SELECT r.origin, SUM(t.fuel_litres) AS litros FROM ops.trips t JOIN ops.routes r ON r.id = t.route_id
                WHERE r.origin = 'Badajoz' AND {SETEMBRO} GROUP BY r.origin""",
            "mundo": """SELECT provincia,
                AVG(media) FILTER (WHERE data BETWEEN DATE '2026-09-01' AND DATE '2026-09-30') AS media_sep,
                AVG(media) FILTER (WHERE data BETWEEN DATE '2026-07-01' AND DATE '2026-07-31') AS media_jul
                FROM mundo.gasoleo_historico_diario WHERE provincia = 'BADAJOZ' GROUP BY provincia""",
        },
        merger=(
            "SELECT ROUND(b.media_sep - b.media_jul, 4) AS subida, ROUND((b.media_sep - b.media_jul) * a.litros, 2) AS coste_mes "
            "FROM {t:litros} a JOIN {t:media_sep} b ON "
            + _eq("a.origin", "b.provincia")
        ),
        por_tabela={
            "trips": f"SELECT route_id, SUM(fuel_litres) AS litros FROM ops.trips WHERE {SETEMBRO_SEM_ALIAS} GROUP BY route_id",
            "routes": "SELECT id, origin FROM ops.routes",
            "gasoleo_historico_diario": "SELECT data, media FROM mundo.gasoleo_historico_diario WHERE provincia = 'BADAJOZ' AND data BETWEEN DATE '2026-07-01' AND DATE '2026-09-30'",
        },
        merger_por_tabela=(
            "WITH l AS (SELECT SUM(t.litros) AS litros FROM {t:litros} t JOIN {t:origin} r ON r.id = t.route_id "
            "WHERE r.origin = 'Badajoz'), h AS (SELECT AVG(media) FILTER (WHERE month(data) = 9) AS s, "
            "AVG(media) FILTER (WHERE month(data) = 7) AS j FROM {t:media}) "
            "SELECT ROUND(h.s - h.j, 4) AS subida, ROUND((h.s - h.j) * l.litros, 2) AS coste_mes FROM l, h"
        ),
        nota="Anexo C #8. 'BADAJOZ' (MITECO) × 'Badajoz' (cliente): junção sem acentos/maiúsculas.",
    ),
    Pergunta(
        id="P9",
        texto=(
            "Según el último boletín semanal europeo, ¿cuánto nos habríamos ahorrado en los viajes "
            "completados Lisboa–Madrid de septiembre de 2026 pagando el gasóleo al precio medio de España "
            "en vez del de Portugal?"
        ),
        tabelas=["trips", "routes", "gasoleo_ue_semanal"],
        esperado_sql=f"""
            WITH u AS (SELECT MAX(data) AS d FROM mundo.gasoleo_ue_semanal),
                 p AS (SELECT MAX(CASE WHEN pais = 'PT' THEN gasoleo_eur_l END)
                              - MAX(CASE WHEN pais = 'ES' THEN gasoleo_eur_l END) AS dif
                       FROM mundo.gasoleo_ue_semanal WHERE data = (SELECT d FROM u)),
                 l AS (SELECT SUM(t.fuel_litres) AS litros FROM ops.trips t JOIN ops.routes r ON r.id = t.route_id
                       WHERE r.origin = 'Lisboa' AND r.destination = 'Madrid' AND {SETEMBRO})
            SELECT ROUND(p.dif * l.litros, 2) AS ahorro FROM p, l""",
        verificar=["ahorro"],
        fatias={
            "cliente": f"""SELECT r.origin, r.destination, SUM(t.fuel_litres) AS litros
                FROM ops.trips t JOIN ops.routes r ON r.id = t.route_id
                WHERE r.origin = 'Lisboa' AND r.destination = 'Madrid' AND {SETEMBRO} GROUP BY 1, 2""",
            "mundo": """SELECT data, MAX(CASE WHEN pais = 'PT' THEN gasoleo_eur_l END) AS precio_pt,
                MAX(CASE WHEN pais = 'ES' THEN gasoleo_eur_l END) AS precio_es
                FROM mundo.gasoleo_ue_semanal WHERE data = (SELECT MAX(data) FROM mundo.gasoleo_ue_semanal)
                GROUP BY data""",
        },
        merger="SELECT ROUND((b.precio_pt - b.precio_es) * a.litros, 2) AS ahorro FROM {t:litros} a, {t:precio_pt} b",
        por_tabela={
            "trips": f"SELECT route_id, SUM(fuel_litres) AS litros FROM ops.trips WHERE {SETEMBRO_SEM_ALIAS} GROUP BY route_id",
            "routes": "SELECT id, origin, destination FROM ops.routes",
            "gasoleo_ue_semanal": "SELECT data, pais, gasoleo_eur_l FROM mundo.gasoleo_ue_semanal WHERE pais IN ('ES', 'PT')",
        },
        merger_por_tabela=(
            "WITH l AS (SELECT SUM(t.litros) AS litros FROM {t:litros} t JOIN {t:origin} r ON r.id = t.route_id "
            "WHERE r.origin = 'Lisboa' AND r.destination = 'Madrid'), "
            "u AS (SELECT * FROM {t:gasoleo_eur_l} WHERE data = (SELECT MAX(data) FROM {t:gasoleo_eur_l})) "
            "SELECT ROUND((MAX(CASE WHEN u.pais = 'PT' THEN u.gasoleo_eur_l END) - "
            "MAX(CASE WHEN u.pais = 'ES' THEN u.gasoleo_eur_l END)) * MAX(l.litros), 2) AS ahorro FROM u, l"
        ),
        nota="Anexo C #10 (WOB: ES vs PT).",
    ),
    Pergunta(
        id="P10",
        texto=(
            "¿Cuántas de nuestras rutas tienen previsión de rachas de viento de más de 50 km/h en la ciudad "
            "de origen o en la de destino el 14 de octubre de 2026?"
        ),
        tabelas=["routes", "tempo_cidades"],
        esperado_sql="""
            SELECT COUNT(*) AS rutas FROM ops.routes r WHERE EXISTS (
              SELECT 1 FROM mundo.tempo_cidades c WHERE c.data = DATE '2026-10-14' AND c.rajada_max_kmh > 50
              AND c.cidade IN (r.origin, r.destination))""",
        verificar=["rutas"],
        fatias={
            "cliente": "SELECT id, origin, destination FROM ops.routes",
            "mundo": "SELECT cidade, rajada_max_kmh FROM mundo.tempo_cidades WHERE data = DATE '2026-10-14' AND rajada_max_kmh > 50",
        },
        merger=(
            "SELECT COUNT(DISTINCT a.id) AS rutas FROM {t:origin} a JOIN {t:rajada_max_kmh} b ON "
            f"{NORM.format('b.cidade')} IN ({NORM.format('a.origin')}, {NORM.format('a.destination')})"
        ),
        por_tabela={
            "routes": "SELECT id, origin, destination FROM ops.routes",
            "tempo_cidades": "SELECT cidade, rajada_max_kmh FROM mundo.tempo_cidades WHERE data = DATE '2026-10-14' AND rajada_max_kmh > 50",
        },
        merger_por_tabela=(
            "SELECT COUNT(DISTINCT a.id) AS rutas FROM {t:origin} a JOIN {t:rajada_max_kmh} b ON "
            "b.cidade IN (a.origin, a.destination)"
        ),
        nota="Anexo C #3 (tempo). A fonte do tempo está atrasada no gabarito → a citação tem de o dizer.",
    ),
]
