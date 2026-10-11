# core/sql/relationships.py
"""
Módulo para detectar e gerenciar relacionamentos entre tabelas (FKs).
Usado para permitir JOINs automáticos quando múltiplas tabelas são necessárias.

Suporta dois modos:
  - explicit: definido pelo cliente via UI (join_type + label + confidence="explicit")
  - inferred: detectado automaticamente por heurística de nomes de coluna

Relacionamentos explícitos têm SEMPRE prioridade sobre os inferidos.
Relacionamentos são filtrados por permissão antes de chegarem ao prompt da IA.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field

from core.agents.generic_sql_agent import TableSchema, TableColumn


@dataclass
class TableRelationship:
    """Representa um relacionamento entre duas tabelas via FK."""

    from_table: str  # logical_name da tabela origem
    from_column: str  # coluna FK na tabela origem
    to_table: str  # logical_name da tabela destino
    to_column: str  # coluna PK na tabela destino
    join_type: str = "INNER"  # INNER | LEFT | RIGHT | FULL
    label: Optional[str] = None  # Descrição legível (ex: "Venda pertence ao Cliente")
    confidence: str = "inferred"  # "explicit" | "inferred"

    def __str__(self) -> str:
        return (
            f"{self.join_type} JOIN {self.to_table} ON "
            f"{self.from_table}.{self.from_column} = {self.to_table}.{self.to_column}"
        )


def filter_relationships_by_permissions(
    relationships: List[TableRelationship],
    allowed_table_names: Set[str],
) -> List[TableRelationship]:
    """
    Remove relacionamentos onde o usuário não tem acesso a uma das tabelas.

    Regra: um relacionamento só é válido se AMBAS as tabelas (from_table e
    to_table) estiverem na lista de tabelas autorizadas para o usuário.

    Deve ser chamada APÓS _filter_tables_by_permissions() e ANTES de
    detect_relationships(), passando o resultado como explicit_relationships.

    Args:
        relationships: Lista de relacionamentos candidatos (explicit ou inferred)
        allowed_table_names: Conjunto de logical_names que o usuário pode acessar

    Returns:
        Lista filtrada contendo apenas JOINs autorizados
    """
    if not allowed_table_names:
        # sem tables autorizadas → nenhum relacionamento faz sentido
        return []

    filtered = [
        rel
        for rel in relationships
        if rel.from_table in allowed_table_names and rel.to_table in allowed_table_names
    ]
    return filtered


def detect_relationships(
    tables: List[TableSchema],
    explicit_relationships: Optional[List[dict]] = None,
) -> List[TableRelationship]:
    """
    Detecta relacionamentos entre tabelas.

    Prioridade:
      1. explicit_relationships (definidos pelo cliente via UI) — confidence="explicit"
      2. FK marcadas via is_foreign_key=True — confidence="inferred"
      3. Heurística por nome de coluna (*_id) — confidence="inferred"

    Relacionamentos explícitos nunca são sobrescritos pela heurística.
    O par (from_table, to_table) já coberto por um explicit não gera inferred duplicado.

    Args:
        tables: Lista de TableSchema disponíveis para o agente
        explicit_relationships: Lista de dicts com relacionamentos documentados pelo cliente.
            Cada dict deve ter: from_table, from_column, to_table, to_column,
            opcionalmente join_type (default INNER) e label.

    Returns:
        Lista de TableRelationship: explicit primeiro, depois inferred sem duplicatas.
    """
    table_map: Dict[str, TableSchema] = {t.logical_name: t for t in tables}

    # ── 1. Processar explicit_relationships (máxima prioridade) ──────────────
    explicit: List[TableRelationship] = []
    explicit_pairs: Set[Tuple[str, str]] = set()  # (from_table, to_table)

    if explicit_relationships:
        for rel_dict in explicit_relationships:
            from_t = rel_dict.get("from_table", "")
            to_t = rel_dict.get("to_table", "")
            from_c = rel_dict.get("from_column", "")
            to_c = rel_dict.get("to_column", "")
            if not (from_t and to_t and from_c and to_c):
                continue
            explicit.append(
                TableRelationship(
                    from_table=from_t,
                    from_column=from_c,
                    to_table=to_t,
                    to_column=to_c,
                    join_type=rel_dict.get("join_type", "INNER").upper(),
                    label=rel_dict.get("label"),
                    confidence="explicit",
                )
            )
            explicit_pairs.add((from_t, to_t))
            explicit_pairs.add((to_t, from_t))  # bidirecional

    # ── 2. Inferência por FK marcada (is_foreign_key=True) ───────────────────
    inferred: List[TableRelationship] = []

    for table in tables:
        for col in table.columns:
            col_dict = (
                col
                if isinstance(col, dict)
                else {
                    "name": col.name,
                    "is_foreign_key": getattr(col, "is_foreign_key", False),
                }
            )
            if not col_dict.get("is_foreign_key", False):
                continue
            col_name = col_dict["name"]
            target_table = _infer_target_table_from_fk(col_name, table_map.keys())
            if target_table and target_table in table_map:
                # Não duplicar se explicit já cobre este par
                if (table.logical_name, target_table) in explicit_pairs:
                    continue
                target_pk = _find_primary_key(table_map[target_table])
                if target_pk:
                    inferred.append(
                        TableRelationship(
                            from_table=table.logical_name,
                            from_column=col_name,
                            to_table=target_table,
                            to_column=target_pk,
                            confidence="inferred",
                        )
                    )

    # ── 3. Heurística por nome de coluna (*_id) — só se nada inferido acima ──
    if not inferred:
        for table in tables:
            for col in table.columns:
                col_dict = (
                    col
                    if isinstance(col, dict)
                    else {
                        "name": col.name,
                        "is_primary_key": getattr(col, "is_primary_key", False),
                    }
                )
                col_name = col_dict["name"]
                if col_dict.get("is_primary_key", False):
                    continue
                if col_name.endswith("_id") and len(col_name) > 3:
                    target_table = _infer_target_table_from_fk(
                        col_name, table_map.keys()
                    )
                    if target_table and target_table in table_map:
                        if (table.logical_name, target_table) in explicit_pairs:
                            continue
                        target_pk = _find_primary_key(table_map[target_table])
                        if target_pk:
                            inferred.append(
                                TableRelationship(
                                    from_table=table.logical_name,
                                    from_column=col_name,
                                    to_table=target_table,
                                    to_column=target_pk,
                                    confidence="inferred",
                                )
                            )

    # ── 3b. Chaves que a heurística *_id não via ─────────────────────────────
    # `gasolineras_rota.id_estacion` → `gasolineras_precio.id_estacion`
    # (dados públicos, 11/10/2026): prefixo `id_` à castelhana, sem FK
    # declarada no Postgres e sem PK no metadado que chega aqui. A ligação
    # não existia para ninguém — e o especialista, só com a tabela de rota,
    # respondia «no dispongo de la información» a «gasolineras con el gasóleo
    # más barato en gasolineras_rota».
    inferred += _relacoes_por_descricao_e_chave_partilhada(
        tables, explicit_pairs, inferred
    )

    # ── 4. Remover duplicatas em inferred e combinar ─────────────────────────
    seen: Set[Tuple[str, str, str, str]] = set()
    unique_inferred: List[TableRelationship] = []
    for rel in inferred:
        key = (rel.from_table, rel.from_column, rel.to_table, rel.to_column)
        if key not in seen:
            seen.add(key)
            unique_inferred.append(rel)

    return explicit + unique_inferred


def _nome_e_descricao(col) -> Tuple[str, str]:
    if isinstance(col, dict):
        return str(col.get("name") or ""), str(col.get("description") or "")
    return str(getattr(col, "name", "") or ""), str(
        getattr(col, "description", "") or ""
    )


#: «FK gasolineras_precio.id_estacion», «= ops.routes.origin»: uma referência
#: `tabela.coluna` (com esquema opcional) escrita no comentário da coluna.
_REFERENCIA = re.compile(r"\b(?:[A-Za-z_]\w*\.)?([A-Za-z_]\w*)\.([A-Za-z_]\w*)\b")


def _palavras_do_nome(nome: str) -> Set[str]:
    return set(re.split(r"[^a-z0-9]+", (nome or "").lower())) - {""}


def _relacoes_por_descricao_e_chave_partilhada(
    tables: List[TableSchema],
    explicit_pairs: Set[Tuple[str, str]],
    ja_inferidas: List[TableRelationship],
) -> List[TableRelationship]:
    """Duas fontes de ligação que o resto deste módulo não lia.

    1. O comentário da coluna diz para onde aponta: «FK tabela.coluna» ou
       «= esquema.tabela.coluna». Só conta se a tabela e a coluna existem.
    2. Uma coluna-chave (com «id» no nome, mas não só «id») com o MESMO nome
       em exactamente duas tabelas: `id_estacion`, `route_id`. Mais de duas
       já é um nome genérico, não uma ligação.
    """
    por_nome: Dict[str, TableSchema] = {t.logical_name: t for t in tables}
    colunas: Dict[str, Set[str]] = {
        t.logical_name: {_nome_e_descricao(c)[0] for c in (t.columns or [])}
        for t in tables
    }
    vistos: Set[Tuple[str, str]] = set(explicit_pairs)
    for r in ja_inferidas:
        vistos.add((r.from_table, r.to_table))
        vistos.add((r.to_table, r.from_table))

    novas: List[TableRelationship] = []

    def juntar(a: str, ca: str, b: str, cb: str) -> None:
        if a == b or (a, b) in vistos:
            return
        vistos.add((a, b))
        vistos.add((b, a))
        novas.append(
            TableRelationship(
                from_table=a,
                from_column=ca,
                to_table=b,
                to_column=cb,
                confidence="inferred",
            )
        )

    # 1. Referências no comentário.
    for t in tables:
        for col in t.columns or []:
            nome, descricao = _nome_e_descricao(col)
            if not nome or not descricao:
                continue
            for m in _REFERENCIA.finditer(descricao):
                alvo, coluna_alvo = m.group(1), m.group(2)
                if alvo in por_nome and coluna_alvo in colunas.get(alvo, set()):
                    juntar(t.logical_name, nome, alvo, coluna_alvo)

    # 2. A mesma chave em exactamente duas tabelas.
    onde: Dict[str, List[str]] = {}
    for t in tables:
        for c in colunas[t.logical_name]:
            p = _palavras_do_nome(c)
            if "id" in p and len(p) > 1:
                onde.setdefault(c, []).append(t.logical_name)
    for c, donos in onde.items():
        if len(donos) == 2:
            juntar(donos[0], c, donos[1], c)

    return novas


def tabelas_vizinhas_que_a_pergunta_pede(
    pergunta: str,
    escolhidas: List[str],
    tables: List[TableSchema],
    relationships: List[TableRelationship],
    maximo: int = 2,
) -> List[str]:
    """As tabelas ligadas às escolhidas que têm o que a pergunta pede.

    O orquestrador escolhe a tabela que a pessoa nomeia. Em «las 5
    gasolineras con el gasóleo A más barato en la tabla gasolineras_rota»
    escolhe só `gasolineras_rota` — que tem a rota e o posto, mas não o
    preço; o preço está em `gasolineras_precio`, ligada por `id_estacion`.
    O especialista só vê as colunas das tabelas escolhidas, não encontra
    nenhum gasóleo e recusa.

    Regra: uma tabela a UM salto (por uma relação conhecida) entra quando
    uma palavra da pergunta está nas colunas DELA e em nenhuma coluna das
    escolhidas. Determinístico, sem chamar o modelo, e no máximo `maximo`.
    """
    if not escolhidas or not relationships:
        return []

    def normalizar(s: str) -> str:
        s = unicodedata.normalize("NFKD", (s or "").lower())
        return "".join(ch for ch in s if not unicodedata.combining(ch))

    def raiz(p: str) -> str:
        return p[:-1] if len(p) > 4 and p.endswith("s") else p

    def palavras(s: str) -> Set[str]:
        return {
            raiz(p)
            for p in re.split(r"[^a-z0-9]+", normalizar(s))
            if len(p) >= 4 and p not in _PALAVRAS_GENERICAS
        }

    por_nome = {t.logical_name: t for t in tables}

    def palavras_das_colunas(nome_tabela: str) -> Set[str]:
        t = por_nome.get(nome_tabela)
        if not t:
            return set()
        out: Set[str] = set()
        for c in t.columns or []:
            out |= palavras(_nome_e_descricao(c)[0])
        return out

    da_pergunta = palavras(pergunta)
    ja_cobertas: Set[str] = set()
    for e in escolhidas:
        ja_cobertas |= palavras_das_colunas(e)
    pedidas = da_pergunta - ja_cobertas
    if not pedidas:
        return []

    escolhidas_set = set(escolhidas)
    novas: List[str] = []
    for rel in relationships:
        for de, para in (
            (rel.from_table, rel.to_table),
            (rel.to_table, rel.from_table),
        ):
            if de not in escolhidas_set or para in escolhidas_set or para in novas:
                continue
            if pedidas & palavras_das_colunas(para):
                novas.append(para)
                if len(novas) >= maximo:
                    return novas
    return novas


#: Palavras que estão em colunas de quase todas as tabelas e em quase todas
#: as frases: não dizem que tabela a pergunta pede.
_PALAVRAS_GENERICAS = {
    "data",
    "date",
    "fecha",
    "nome",
    "name",
    "nombre",
    "estado",
    "status",
    "tipo",
    "type",
    "valor",
    "value",
    "fonte",
    "source",
    "nota",
    "note",
    "descricao",
    "descripcion",
    "description",
    "codigo",
    "code",
    "total",
    "tabla",
    "tabela",
    "table",
    "lista",
    "para",
    "with",
    "from",
    "como",
    "cual",
    "cuales",
    "qual",
    "quais",
    "what",
    "which",
    "todos",
    "todas",
    "desde",
    "hasta",
    "entre",
    "sobre",
    "segun",
    "this",
    "that",
    "esta",
    "este",
    "actualizado",
    "updated",
    "created",
    "criado",
    "calculado",
}


def _infer_target_table_from_fk(
    fk_column_name: str, available_tables: Set[str]
) -> Optional[str]:
    """
    Infere a tabela destino de uma FK baseado no nome da coluna.
    Exemplos:
      - user_id -> users, silver_users_enriquecido
      - customer_id -> customers, silver_customers_enriquecido
      - order_id -> orders, silver_orders_enriquecido
      - product_id -> products
    """
    # Remove sufixo _id
    if fk_column_name.endswith("_id"):
        base_name = fk_column_name[:-3]  # remove "_id"
    else:
        return None

    # Tentar match exato pluralizado
    plural = f"{base_name}s"
    if plural in available_tables:
        return plural

    # Tentar match exato singular
    if base_name in available_tables:
        return base_name

    # Tentar match com padrões comuns (silver_*_enriquecido, *s_enriquecido, etc)
    # Ex: user_id -> silver_users_enriquecido
    patterns = [
        f"silver_{plural}_enriquecido",
        f"silver_{base_name}_enriquecido",
        f"{plural}_enriquecido",
        f"{base_name}_enriquecido",
    ]

    for pattern in patterns:
        if pattern in available_tables:
            return pattern

    # Tentar match parcial (ex: customer_id -> customer_orders, silver_customers_*)
    for table_name in available_tables:
        # Remove prefixos comuns e sufixos para comparação
        normalized = table_name
        if normalized.startswith("silver_"):
            normalized = normalized[7:]  # remove "silver_"
        if normalized.endswith("_enriquecido"):
            normalized = normalized[:-12]  # remove "_enriquecido"

        # Verifica se contém o base_name ou plural
        if normalized == plural or normalized == base_name:
            return table_name
        if normalized.startswith(plural) or normalized.startswith(base_name):
            return table_name

    return None


def _find_primary_key(table: TableSchema) -> Optional[str]:
    """Encontra a coluna PK de uma tabela, ou retorna 'id' como padrão."""
    for col in table.columns:
        col_dict = (
            col
            if isinstance(col, dict)
            else {
                "name": col.name,
                "is_primary_key": getattr(col, "is_primary_key", False),
            }
        )

        if col_dict.get("is_primary_key", False):
            return col_dict["name"]

    # Fallback: procurar coluna chamada "id"
    for col in table.columns:
        col_dict = col if isinstance(col, dict) else {"name": col.name}
        if col_dict["name"].lower() == "id":
            return col_dict["name"]

    return None


def find_join_path(
    tables: List[str],
    relationships: List[TableRelationship],
) -> Optional[List[TableRelationship]]:
    """
    Encontra um caminho de JOINs para conectar múltiplas tabelas.

    Args:
        tables: Lista de logical_names das tabelas que precisam ser unidas
        relationships: Lista de relacionamentos disponíveis

    Returns:
        Lista ordenada de TableRelationship representando o caminho de JOINs,
        ou None se não houver caminho possível.
    """
    if len(tables) < 2:
        return []

    if len(tables) == 2:
        # Caso simples: duas tabelas
        table1, table2 = tables[0], tables[1]

        # Procurar relacionamento direto
        for rel in relationships:
            if (rel.from_table == table1 and rel.to_table == table2) or (
                rel.from_table == table2 and rel.to_table == table1
            ):
                return [rel]

        return None

    # Caso complexo: 3+ tabelas - usar busca em largura (BFS)
    # Por simplicidade, vamos tentar encontrar um caminho sequencial
    # (tabela1 -> tabela2 -> tabela3 ...)

    path: List[TableRelationship] = []
    remaining = set(tables[1:])
    current = tables[0]

    while remaining:
        found = False
        for rel in relationships:
            if rel.from_table == current and rel.to_table in remaining:
                path.append(rel)
                remaining.remove(rel.to_table)
                current = rel.to_table
                found = True
                break
            elif rel.to_table == current and rel.from_table in remaining:
                # Relacionamento reverso - criar rel reverso
                reverse_rel = TableRelationship(
                    from_table=rel.to_table,
                    from_column=rel.to_column,
                    to_table=rel.from_table,
                    to_column=rel.from_column,
                )
                path.append(reverse_rel)
                remaining.remove(rel.from_table)
                current = rel.from_table
                found = True
                break

        if not found:
            # Não encontrou caminho
            return None

    return path if path else None


def build_join_clause(
    relationships: List[TableRelationship],
    table_aliases: Optional[Dict[str, str]] = None,
) -> str:
    """
    Constrói a cláusula JOIN para um conjunto de relacionamentos.

    Usa rel.join_type (INNER | LEFT | RIGHT | FULL) definido pelo cliente.
    Para relacionamentos inferred, o default é INNER.

    Args:
        relationships: Lista de relacionamentos ordenados
        table_aliases: Mapeamento opcional de logical_name -> alias

    Returns:
        String SQL com cláusulas JOIN.
        Ex: "LEFT JOIN clientes c ON vendas.cli_id = c.id"
    """
    if not relationships:
        return ""

    if table_aliases is None:
        table_aliases = {}

    join_parts = []
    for rel in relationships:
        from_alias = table_aliases.get(rel.from_table, rel.from_table)
        to_alias = table_aliases.get(rel.to_table, rel.to_table)
        join_type = getattr(rel, "join_type", "INNER").upper()

        join_parts.append(
            f"{join_type} JOIN {rel.to_table} {to_alias} "
            f"ON {from_alias}.{rel.from_column} = {to_alias}.{rel.to_column}"
        )

    return " ".join(join_parts)
