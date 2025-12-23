# core/sql/relationships.py
"""
Módulo para detectar e gerenciar relacionamentos entre tabelas (FKs).
Usado para permitir JOINs automáticos quando múltiplas tabelas são necessárias.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass

from core.agents.generic_sql_agent import TableSchema, TableColumn


@dataclass
class TableRelationship:
    """Representa um relacionamento entre duas tabelas via FK."""
    from_table: str  # logical_name da tabela origem
    from_column: str  # coluna FK na tabela origem
    to_table: str  # logical_name da tabela destino
    to_column: str  # coluna PK na tabela destino (geralmente "id" ou similar)
    
    def __str__(self) -> str:
        return f"{self.from_table}.{self.from_column} -> {self.to_table}.{self.to_column}"


def detect_relationships(tables: List[TableSchema]) -> List[TableRelationship]:
    """
    Detecta relacionamentos entre tabelas baseado em:
    1. Colunas marcadas como FK (is_foreign_key=True)
    2. Convenções de nomenclatura (ex: user_id -> users.id)
    3. Nomes de colunas que sugerem relacionamento (ex: customer_id, order_id)
    
    Retorna lista de TableRelationship ordenada por relevância.
    """
    relationships: List[TableRelationship] = []
    
    # Mapear tabelas por logical_name para acesso rápido
    table_map: Dict[str, TableSchema] = {t.logical_name: t for t in tables}
    
    # Passo 1: Detectar FKs explícitas (is_foreign_key=True)
    for table in tables:
        for col in table.columns:
            col_dict = col if isinstance(col, dict) else {
                "name": col.name,
                "is_foreign_key": getattr(col, "is_foreign_key", False),
            }
            
            if col_dict.get("is_foreign_key", False):
                col_name = col_dict["name"]
                # Tentar inferir tabela destino pelo nome da coluna
                # Ex: user_id -> users, customer_id -> customers
                target_table = _infer_target_table_from_fk(col_name, table_map.keys())
                
                if target_table and target_table in table_map:
                    # Tentar encontrar PK na tabela destino
                    target_pk = _find_primary_key(table_map[target_table])
                    if target_pk:
                        relationships.append(
                            TableRelationship(
                                from_table=table.logical_name,
                                from_column=col_name,
                                to_table=target_table,
                                to_column=target_pk,
                            )
                        )
    
    # Passo 2: Detectar por convenção de nomenclatura (ex: user_id, order_id)
    # Só se não encontrou FK explícita
    if not relationships:
        for table in tables:
            for col in table.columns:
                col_dict = col if isinstance(col, dict) else {
                    "name": col.name,
                    "is_primary_key": getattr(col, "is_primary_key", False),
                }
                
                col_name = col_dict["name"]
                # Ignorar se já é PK
                if col_dict.get("is_primary_key", False):
                    continue
                
                # Padrão: *_id sugere FK
                if col_name.endswith("_id") and len(col_name) > 3:
                    target_table = _infer_target_table_from_fk(col_name, table_map.keys())
                    
                    if target_table and target_table in table_map:
                        target_pk = _find_primary_key(table_map[target_table])
                        if target_pk:
                            relationships.append(
                                TableRelationship(
                                    from_table=table.logical_name,
                                    from_column=col_name,
                                    to_table=target_table,
                                    to_column=target_pk,
                                )
                            )
    
    # Remover duplicatas
    seen = set()
    unique_rels = []
    for rel in relationships:
        key = (rel.from_table, rel.from_column, rel.to_table, rel.to_column)
        if key not in seen:
            seen.add(key)
            unique_rels.append(rel)
    
    return unique_rels


def _infer_target_table_from_fk(fk_column_name: str, available_tables: Set[str]) -> Optional[str]:
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
        col_dict = col if isinstance(col, dict) else {
            "name": col.name,
            "is_primary_key": getattr(col, "is_primary_key", False),
        }
        
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
            if (rel.from_table == table1 and rel.to_table == table2) or \
               (rel.from_table == table2 and rel.to_table == table1):
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
    
    Args:
        relationships: Lista de relacionamentos ordenados
        table_aliases: Mapeamento opcional de logical_name -> alias
    
    Returns:
        String SQL com cláusulas JOIN (ex: "JOIN users u ON orders.user_id = u.id")
    """
    if not relationships:
        return ""
    
    if table_aliases is None:
        table_aliases = {}
    
    join_parts = []
    for rel in relationships:
        from_alias = table_aliases.get(rel.from_table, rel.from_table)
        to_alias = table_aliases.get(rel.to_table, rel.to_table)
        
        join_parts.append(
            f"JOIN {rel.to_table} {to_alias} "
            f"ON {from_alias}.{rel.from_column} = {to_alias}.{rel.to_column}"
        )
    
    return " ".join(join_parts)
