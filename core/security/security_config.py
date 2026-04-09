# core/security/security_config.py
"""
Configuração de Segurança Dinâmica por Conexão.

Este módulo define os modelos e funções para aplicar regras de segurança
configuráveis pelo backend, incluindo:
- Row-Level Security (RLS): filtros WHERE automáticos por space/crew
- Column-Level Security: colunas permitidas/bloqueadas por tabela
- SQL Keywords bloqueadas: DDL/DML proibidos

O backend é responsável por calcular e enviar o security_config apropriado
para cada usuário/space/crew. A IA apenas aplica as regras recebidas.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
import re


# ============================================================================
# MODELOS PYDANTIC
# ============================================================================

class TableSecurityConfig(BaseModel):
    """
    Configuração de segurança para uma tabela específica.
    
    Attributes:
        row_filter: Cláusula WHERE a ser injetada automaticamente.
                   Exemplo: "region = 'UK'" ou "department_id IN (1, 2, 3)"
        allowed_columns: Lista de colunas permitidas. Se None, todas são permitidas.
                        Se definido, APENAS essas colunas podem ser acessadas.
        blocked_columns: Lista de colunas bloqueadas. Sempre aplicado.
                        Exemplo: ["password", "ssn", "credit_score"]
    """
    row_filter: Optional[str] = Field(
        default=None,
        description="Cláusula WHERE a ser injetada automaticamente. Ex: region = 'UK'"
    )
    allowed_columns: Optional[List[str]] = Field(
        default=None,
        description="Lista de colunas permitidas. Se None, todas são permitidas."
    )
    blocked_columns: Optional[List[str]] = Field(
        default=None,
        description="Lista de colunas bloqueadas."
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "row_filter": "region = 'UK'",
                "allowed_columns": ["id", "name", "amount", "date"],
                "blocked_columns": ["cost_price", "internal_notes"]
            }
        }


class SecurityConfig(BaseModel):
    """
    Configuração de segurança completa para uma conexão/usuário.
    
    Enviada pelo backend em cada request, contém todas as regras
    de segurança que a IA deve aplicar.
    
    Attributes:
        blocked_sql_keywords: Palavras-chave SQL proibidas (DDL/DML).
        tables: Configurações específicas por tabela (RLS + colunas).
        global_blocked_columns: Colunas bloqueadas em TODAS as tabelas.
        max_rows_limit: Limite máximo de linhas por query.
        allow_joins: Se permite JOINs entre tabelas.
        allow_subqueries: Se permite subqueries.
    """
    blocked_sql_keywords: List[str] = Field(
        default=[
            "DROP", "ALTER", "INSERT", "UPDATE", "DELETE",
            "TRUNCATE", "CREATE", "GRANT", "REVOKE", "MERGE",
            "EXEC", "EXECUTE", "COMMIT", "ROLLBACK"
        ],
        description="Palavras-chave SQL proibidas."
    )
    tables: Dict[str, TableSecurityConfig] = Field(
        default_factory=dict,
        description="Configurações de segurança por tabela (nome lógico)."
    )
    global_blocked_columns: List[str] = Field(
        default_factory=list,
        description="Colunas bloqueadas em todas as tabelas."
    )
    max_rows_limit: int = Field(
        default=5000,
        description="Limite máximo de linhas por query."
    )
    allow_joins: bool = Field(
        default=True,
        description="Se permite JOINs entre tabelas."
    )
    allow_subqueries: bool = Field(
        default=False,
        description="Se permite subqueries (mais restritivo por padrão)."
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "blocked_sql_keywords": ["DROP", "INSERT", "UPDATE", "DELETE"],
                "tables": {
                    "invoices": {
                        "row_filter": "region = 'UK'",
                        "blocked_columns": ["cost_price"]
                    },
                    "customers": {
                        "row_filter": "country = 'UK'",
                        "allowed_columns": ["id", "name", "email"]
                    }
                },
                "global_blocked_columns": ["password", "ssn", "credit_score"],
                "max_rows_limit": 5000,
                "allow_joins": True,
                "allow_subqueries": False
            }
        }


# ============================================================================
# FUNÇÕES DE APLICAÇÃO DE SEGURANÇA
# ============================================================================

def get_default_security_config() -> SecurityConfig:
    """
    Retorna configuração de segurança padrão (restritiva).
    Usada quando o backend não envia security_config.
    """
    return SecurityConfig(
        blocked_sql_keywords=[
            "DROP", "ALTER", "INSERT", "UPDATE", "DELETE",
            "TRUNCATE", "CREATE", "GRANT", "REVOKE", "MERGE",
            "EXEC", "EXECUTE", "COMMIT", "ROLLBACK"
        ],
        global_blocked_columns=[
            "password", "senha", "pwd",
            "ssn", "cpf", "rg",
            "credit_score", "score_credito",
            "api_key", "secret", "token",
        ],
        max_rows_limit=5000,
        allow_joins=True,
        allow_subqueries=False,
    )


def filter_columns_by_security(
    columns: List[Any],
    table_name: str,
    security_config: SecurityConfig
) -> List[Any]:
    """
    Filtra colunas de uma tabela baseado nas regras de segurança.
    
    Args:
        columns: Lista de colunas (dict ou objeto com atributo 'name')
        table_name: Nome lógico da tabela
        security_config: Configuração de segurança
    
    Returns:
        Lista de colunas filtradas (sem as bloqueadas)
    """
    table_config = security_config.tables.get(table_name)
    
    # Colunas bloqueadas: global + específicas da tabela
    blocked = set(security_config.global_blocked_columns)
    if table_config and table_config.blocked_columns:
        blocked.update(table_config.blocked_columns)
    
    # Colunas permitidas (se definido, só essas passam)
    allowed = None
    if table_config and table_config.allowed_columns:
        allowed = set(table_config.allowed_columns)
    
    filtered = []
    for col in columns:
        # Extrair nome da coluna
        if isinstance(col, dict):
            col_name = col.get("name", col.get("column_name", ""))
        else:
            col_name = getattr(col, "name", getattr(col, "column_name", ""))
        
        # Se allowed_columns definido, verificar se está na lista
        if allowed and col_name not in allowed:
            continue
        
        # Se está na lista de bloqueados, não incluir
        if col_name.lower() in [b.lower() for b in blocked]:
            continue
        
        filtered.append(col)
    
    return filtered


def get_row_filter_for_table(
    table_name: str,
    security_config: SecurityConfig
) -> Optional[str]:
    """
    Retorna o row_filter (cláusula WHERE) para uma tabela.
    
    Args:
        table_name: Nome lógico da tabela
        security_config: Configuração de segurança
    
    Returns:
        String com a cláusula WHERE ou None
    """
    table_config = security_config.tables.get(table_name)
    if table_config and table_config.row_filter:
        return table_config.row_filter
    return None


def inject_row_filters_in_sql(
    sql: str,
    security_config: SecurityConfig,
    table_aliases: Optional[Dict[str, str]] = None
) -> str:
    """
    Injeta row_filters (RLS) no SQL gerado.
    
    Esta função adiciona cláusulas WHERE automaticamente para cada tabela
    que possui row_filter definido no security_config.
    
    Args:
        sql: SQL original gerado pelo Specialist
        security_config: Configuração de segurança
        table_aliases: Mapeamento de tabela -> alias (opcional)
    
    Returns:
        SQL com row_filters injetados
    
    Example:
        Input:  "SELECT * FROM invoices WHERE amount > 100"
        Config: {"invoices": {"row_filter": "region = 'UK'"}}
        Output: "SELECT * FROM invoices WHERE (region = 'UK') AND amount > 100"
    """
    if not security_config.tables:
        return sql
    
    table_aliases = table_aliases or {}
    filters_to_inject = []
    
    for table_name, config in security_config.tables.items():
        if not config.row_filter:
            continue
        
        # Verificar se a tabela está no SQL
        # Padrões: FROM table, JOIN table, FROM `table`, FROM "table"
        patterns = [
            rf"\bFROM\s+[`'\"]?{re.escape(table_name)}[`'\"]?\s*(?:AS\s+)?(\w+)?",
            rf"\bJOIN\s+[`'\"]?{re.escape(table_name)}[`'\"]?\s*(?:AS\s+)?(\w+)?",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, sql, re.IGNORECASE)
            if match:
                # Pegar alias se existir
                alias = match.group(1) if match.group(1) else table_name
                table_aliases[table_name] = alias
                
                # Preparar filtro com alias
                row_filter = config.row_filter
                # Se o filtro não tem prefixo de tabela, adicionar alias
                if "." not in row_filter:
                    # Extrair nome da coluna do filtro
                    col_match = re.match(r"(\w+)\s*[=<>!]", row_filter)
                    if col_match:
                        col_name = col_match.group(1)
                        row_filter = row_filter.replace(col_name, f"{alias}.{col_name}", 1)
                
                filters_to_inject.append(row_filter)
                break
    
    if not filters_to_inject:
        return sql
    
    # Combinar todos os filtros
    combined_filter = " AND ".join([f"({f})" for f in filters_to_inject])
    
    # Injetar no SQL
    sql_upper = sql.upper()
    
    if "WHERE" in sql_upper:
        # Adicionar ao WHERE existente
        # Encontrar posição do WHERE e inserir após
        where_match = re.search(r"\bWHERE\b", sql, re.IGNORECASE)
        if where_match:
            insert_pos = where_match.end()
            sql = sql[:insert_pos] + f" ({combined_filter}) AND" + sql[insert_pos:]
    else:
        # Adicionar novo WHERE antes de GROUP BY, ORDER BY, LIMIT ou fim
        insert_patterns = [
            (r"\bGROUP\s+BY\b", "GROUP BY"),
            (r"\bORDER\s+BY\b", "ORDER BY"),
            (r"\bLIMIT\b", "LIMIT"),
            (r"\bHAVING\b", "HAVING"),
        ]
        
        inserted = False
        for pattern, keyword in insert_patterns:
            match = re.search(pattern, sql, re.IGNORECASE)
            if match:
                insert_pos = match.start()
                sql = sql[:insert_pos] + f" WHERE {combined_filter} " + sql[insert_pos:]
                inserted = True
                break
        
        if not inserted:
            # Adicionar no final (antes do ; se existir)
            if sql.rstrip().endswith(";"):
                sql = sql.rstrip()[:-1] + f" WHERE {combined_filter};"
            else:
                sql = sql + f" WHERE {combined_filter}"
    
    return sql


def validate_sql_against_security(
    sql: str,
    security_config: SecurityConfig,
    allowed_tables: Optional[List[str]] = None
) -> tuple[bool, Optional[str]]:
    """
    Valida SQL contra as regras de segurança.
    
    Verifica:
    1. Keywords bloqueadas (DDL/DML)
    2. Colunas bloqueadas
    3. LIMIT respeitado
    4. Subqueries (se não permitidas)
    5. Row filters aplicados
    
    Args:
        sql: SQL a ser validado
        security_config: Configuração de segurança
        allowed_tables: Lista de tabelas permitidas (opcional)
    
    Returns:
        (is_valid, error_message)
    """
    sql_upper = sql.upper()
    sql_clean = re.sub(r"'[^']*'", "", sql)  # Remove strings para evitar falsos positivos
    sql_clean_upper = sql_clean.upper()
    
    # 1. Verificar keywords bloqueadas
    for keyword in security_config.blocked_sql_keywords:
        pattern = rf"\b{re.escape(keyword)}\b"
        if re.search(pattern, sql_clean_upper):
            return False, f"SQL keyword '{keyword}' is not allowed"
    
    # 2. Verificar colunas bloqueadas globais
    for col in security_config.global_blocked_columns:
        # Verificar no SELECT, WHERE, etc (fora de strings)
        pattern = rf"\b{re.escape(col)}\b"
        if re.search(pattern, sql_clean, re.IGNORECASE):
            return False, f"Column '{col}' is blocked and cannot be accessed"
    
    # 3. Verificar colunas bloqueadas por tabela
    for table_name, config in security_config.tables.items():
        if not config.blocked_columns:
            continue
        
        # Tentar detectar presença da tabela de forma robusta e exata
        # Padrão: borda de palavra, opcionalmente aspas/backticks, nome exato, opcionalmente aspas/backticks, borda de palavra
        # \b[`'"]?table_name[`'"]?\b
        table_pattern = rf"\b[`'\" ]?{re.escape(table_name)}[`'\" ]?\b"
        if re.search(table_pattern, sql, re.IGNORECASE):
            for col in config.blocked_columns:
                col_pattern = rf"\b[`'\" ]?{re.escape(col)}[`'\" ]?\b"
                if re.search(col_pattern, sql_clean, re.IGNORECASE):
                    return False, f"Column '{col}' from table '{table_name}' is blocked"
    
    # 4. Verificar LIMIT
    limit_match = re.search(r"\bLIMIT\s+(\d+)", sql_upper)
    if limit_match:
        limit_value = int(limit_match.group(1))
        if limit_value > security_config.max_rows_limit:
            return False, f"LIMIT {limit_value} exceeds maximum allowed ({security_config.max_rows_limit})"
    else:
        # Se não tem LIMIT, é um problema (já tratado em outro lugar, mas validamos aqui também)
        pass
    
    # 5. Verificar subqueries (se não permitidas)
    if not security_config.allow_subqueries:
        # Contar parênteses com SELECT dentro
        if re.search(r"\(\s*SELECT\b", sql_upper):
            return False, "Subqueries are not allowed"
    
    # 6. Verificar se row_filters foram aplicados (para tabelas que requerem)
    for table_name, config in security_config.tables.items():
        if not config.row_filter:
            continue
        
        # Se a tabela está no SQL, verificar se o filtro está presente
        if re.search(rf"\b{re.escape(table_name)}\b", sql, re.IGNORECASE):
            # Extrair a "essência" do filtro (coluna = valor)
            filter_col_match = re.match(r"(\w+)\s*[=<>!]", config.row_filter)
            if filter_col_match:
                filter_col = filter_col_match.group(1)
                # Verificar se a coluna do filtro aparece no WHERE
                if not re.search(rf"\bWHERE\b.*\b{re.escape(filter_col)}\b", sql, re.IGNORECASE):
                    return False, f"Required row filter for table '{table_name}' is missing"
    
    return True, None


def build_security_prompt_instructions(security_config: SecurityConfig) -> str:
    """
    Gera instruções de segurança para incluir no prompt do LLM.
    
    Estas instruções reforçam as regras de segurança no nível do prompt,
    como camada adicional de proteção (além da validação pós-geração).
    
    Args:
        security_config: Configuração de segurança
    
    Returns:
        String com instruções para o prompt
    """
    lines = [
        "\n🔒 SECURITY RULES (MANDATORY - DO NOT VIOLATE):\n"
    ]
    
    # Keywords bloqueadas
    if security_config.blocked_sql_keywords:
        keywords = ", ".join(security_config.blocked_sql_keywords)
        lines.append(f"1. NEVER use these SQL keywords: {keywords}")
    
    # Colunas bloqueadas globais
    if security_config.global_blocked_columns:
        cols = ", ".join(security_config.global_blocked_columns)
        lines.append(f"2. NEVER access these columns (blocked globally): {cols}")
    
    # Row filters por tabela
    rls_rules = []
    for table_name, config in security_config.tables.items():
        if config.row_filter:
            rls_rules.append(f"   - {table_name}: MUST include WHERE {config.row_filter}")
        if config.blocked_columns:
            cols = ", ".join(config.blocked_columns)
            rls_rules.append(f"   - {table_name}: NEVER access columns: {cols}")
        if config.allowed_columns:
            cols = ", ".join(config.allowed_columns)
            rls_rules.append(f"   - {table_name}: ONLY access columns: {cols}")
    
    if rls_rules:
        lines.append("3. TABLE-SPECIFIC RULES:")
        lines.extend(rls_rules)
    
    # Limite de linhas
    lines.append(f"4. ALWAYS include LIMIT (maximum: {security_config.max_rows_limit})")
    
    # Subqueries
    if not security_config.allow_subqueries:
        lines.append("5. NEVER use subqueries (SELECT inside SELECT)")
    
    lines.append("\n⚠️ Violation of these rules will result in query rejection.\n")
    
    return "\n".join(lines)

