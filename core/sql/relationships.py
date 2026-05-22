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

    # ── 4. Remover duplicatas em inferred e combinar ─────────────────────────
    seen: Set[Tuple[str, str, str, str]] = set()
    unique_inferred: List[TableRelationship] = []
    for rel in inferred:
        key = (rel.from_table, rel.from_column, rel.to_table, rel.to_column)
        if key not in seen:
            seen.add(key)
            unique_inferred.append(rel)

    return explicit + unique_inferred


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
