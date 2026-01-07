# core/sql/validator_advanced.py
"""
Validador SQL avançado com AST e permissões.
Otimizado para performance: regex primeiro, AST só se necessário.
"""
import sqlparse
from sqlparse.sql import Statement, IdentifierList, Identifier
from sqlparse.tokens import Keyword, DML
from typing import List, Set, Dict, Optional, Tuple
import re

# Reusar validação regex existente (rápida)
from core.sql.validator import validate_sql_strict

class AdvancedSQLValidator:
    """
    Validador que combina regex (rápido) + AST (robusto).
    """
    
    def __init__(
        self,
        allowed_tables: List[str],
        allowed_columns: Optional[Dict[str, List[str]]] = None,
        max_limit: int = 100,
        max_columns: int = 10,
        max_group_by: int = 3,
    ):
        # Normalizar e EXPANDIR tabelas permitidas para múltiplas formas
        # Ex: project.dataset.table / dataset.table / table
        self.allowed_tables = self._expand_allowed_tables(allowed_tables)
        self.allowed_columns = {
            k.lower().strip(): [c.lower().strip() for c in v] 
            for k, v in (allowed_columns or {}).items()
        }
        self.max_limit = max_limit
        self.max_columns = max_columns
        self.max_group_by = max_group_by
    
    def validate(
        self, 
        sql: str,
        connection_type: str = "bigquery"
    ) -> Tuple[bool, Optional[str]]:
        """
        Valida SQL em 2 etapas:
        1. Regex (rápido, < 1ms)
        2. AST (se passar regex, ~5-20ms)
        """
        # ETAPA 1: Validação regex (rápida)
        is_valid, error = validate_sql_strict(sql)
        if not is_valid:
            return False, error

        sql_lower = (sql or "").lower()

        # Bloquear schemas/tabelas de sistema / metadata
        system_markers = [
            "information_schema",
            "pg_catalog",
            "pg_class",
            "pg_namespace",
            "sqlite_master",
            "__tables__",
            "sys.",
        ]
        for m in system_markers:
            if m in sql_lower:
                return False, "Access to system/metadata tables is not allowed"

        # Bloquear SELECT * e table.*
        if self._has_select_star(sql):
            return False, "SELECT * is not allowed"
        
        # ETAPA 2: Validação AST (só se passar regex)
        try:
            parsed = sqlparse.parse(sql)
            if not parsed or len(parsed) == 0:
                return False, "Invalid SQL: could not parse"
            
            statement = parsed[0]
        except Exception as e:
            # Se AST falhar, rejeitar (melhor seguro)
            return False, f"Error parsing SQL: {str(e)[:200]}"
        
        # Verificar se é SELECT
        if not self._is_select_statement(statement):
            return False, "Only SELECT statements are allowed"
        
        # Extrair e validar tabelas
        tables = self._extract_tables(statement)
        if not tables:
            return False, "No tables found in query"
        
        for raw_table in tables:
            variants = self._table_variants(raw_table)
            if not (variants & self.allowed_tables):
                return False, f"Table '{raw_table}' is not allowed"
        
        # Validar colunas (se allowed_columns fornecido)
        if self.allowed_columns:
            columns_used = self._extract_columns(statement, connection_type)
            for col_ref in columns_used:
                table_name, col_name = self._split_column_reference(col_ref, connection_type)
                if table_name and col_name:
                    # Normalizar nome da tabela para buscar em allowed_columns
                    table_key = table_name.lower().strip()
                    # Tentar variantes da tabela
                    table_variants = self._table_variants(table_name)
                    found_table = False
                    allowed_cols_for_table = []
                    
                    for variant in table_variants:
                        variant_key = variant.lower().strip()
                        if variant_key in self.allowed_columns:
                            allowed_cols_for_table = self.allowed_columns[variant_key]
                            found_table = True
                            break
                    
                    if found_table and col_name.lower() not in allowed_cols_for_table:
                        return False, f"Column '{col_name}' is not allowed for table '{table_name}'"
                elif col_name and not table_name:
                    # Coluna sem prefixo de tabela - verificar em todas as tabelas usadas
                    # Por segurança, se allowed_columns está definido, exigir prefixo de tabela
                    # para evitar ambiguidade
                    if len(tables) > 1:
                        return False, f"Column '{col_name}' must be qualified with table name (ambiguous in multi-table query)"
                    # Se só uma tabela, verificar nela
                    if tables:
                        table_key = list(tables)[0].lower().strip()
                        table_variants = self._table_variants(list(tables)[0])
                        found_table = False
                        allowed_cols_for_table = []
                        
                        for variant in table_variants:
                            variant_key = variant.lower().strip()
                            if variant_key in self.allowed_columns:
                                allowed_cols_for_table = self.allowed_columns[variant_key]
                                found_table = True
                                break
                        
                        if found_table and col_name.lower() not in allowed_cols_for_table:
                            return False, f"Column '{col_name}' is not allowed"
        
        # Validar LIMIT (obrigatório)
        limit_value = self._extract_limit(statement)
        if limit_value is None:
            return False, f"LIMIT is required (maximum {self.max_limit} rows)"
        if limit_value > self.max_limit:
            return False, f"LIMIT exceeds maximum of {self.max_limit} rows"

        # Validar quantidade de colunas (limite duro)
        num_select_items = self._count_select_items(sql)
        if num_select_items is not None and num_select_items > self.max_columns:
            return False, f"Too many selected columns/expressions (max {self.max_columns})"

        # Validar GROUP BY (limite duro)
        group_by_items = self._count_group_by_items(sql)
        if group_by_items is not None and group_by_items > self.max_group_by:
            return False, f"Too many GROUP BY fields (max {self.max_group_by})"
        
        # Verificar operações perigosas
        if self._has_dangerous_operations(statement):
            return False, "SQL contains dangerous operations"
        
        return True, None
    
    def _is_select_statement(self, statement: Statement) -> bool:
        """Verifica se é SELECT (rápido)"""
        for token in statement.tokens:
            if token.ttype is DML and token.value.upper() == 'SELECT':
                return True
        return False
    
    def _extract_tables(self, statement: Statement) -> Set[str]:
        """
        Extrai referências a tabelas a partir de FROM/JOIN.
        Retorna o identificador "cru" (pode ser project.dataset.table ou dataset.table ou table).
        """
        sql = str(statement)
        tables: Set[str] = set()

        # Captura o identificador logo após FROM/JOIN, incluindo:
        # - `project.dataset.table`
        # - project.dataset.table
        # - dataset.table
        # - table
        # Aceita '-' no project e '_' em nomes.
        #
        # Observação: ignoramos casos de FROM (subquery) porque começam com '('.
        pattern = re.compile(
            r"""
            \b(?:FROM|JOIN)\s+
            (?P<ident>
                `[^`]+`                           # `...`
                |
                [A-Za-z0-9_\-]+(?:\.[A-Za-z0-9_]+){0,2}  # a.b.c (até 3 partes)
            )
            """,
            re.IGNORECASE | re.VERBOSE,
        )

        for m in pattern.finditer(sql):
            ident = m.group("ident").strip()
            if ident.startswith("("):
                continue
            ident = ident.strip("`").strip()
            if not ident:
                continue
            # cortar alias se por acaso veio grudado (defensivo)
            ident = ident.split()[0]
            tables.add(ident)

        return tables

    def _expand_allowed_tables(self, allowed_tables: List[str]) -> Set[str]:
        """
        Expande a lista de tabelas permitidas para múltiplas representações equivalentes:
        - project.dataset.table
        - dataset.table
        - table
        """
        expanded: Set[str] = set()
        for t in allowed_tables or []:
            if not t:
                continue
            for v in self._table_variants(t):
                expanded.add(v)
        return expanded

    def _table_variants(self, table_ref: str) -> Set[str]:
        """
        Gera variantes normalizadas de um identificador de tabela.
        Ex:
          `proj.ds.tbl` -> {proj.ds.tbl, ds.tbl, tbl}
          ds.tbl        -> {ds.tbl, tbl}
          tbl           -> {tbl}
        """
        out: Set[str] = set()
        if not table_ref:
            return out

        cleaned = table_ref.strip().strip("`").strip().lower()
        if not cleaned:
            return out

        # Remove caracteres finais comuns (ex: vírgula)
        cleaned = cleaned.rstrip(",")
        out.add(cleaned)

        parts = [p for p in cleaned.split(".") if p]
        if len(parts) >= 1:
            out.add(parts[-1])
        if len(parts) >= 2:
            out.add(".".join(parts[-2:]))
        if len(parts) >= 3:
            out.add(".".join(parts[-3:]))

        return out
    
    def _extract_limit(self, statement: Statement) -> Optional[int]:
        """
        Extrai valor do LIMIT.
        Abordagem robusta: busca LIMIT no SQL normalizado.
        """
        # Método 1: Usar regex no SQL completo (mais robusto para whitespace/newlines)
        sql_normalized = str(statement).strip()
        limit_match = re.search(r'\bLIMIT\s+(\d+)', sql_normalized, re.IGNORECASE | re.MULTILINE)
        if limit_match:
            try:
                return int(limit_match.group(1))
            except:
                pass
        
        # Método 2: Fallback para parsing de tokens (caso regex falhe)
        limit_seen = False
        for token in statement.flatten():  # flatten() pega todos os tokens recursivamente
            token_value = str(token.value).strip() if hasattr(token, 'value') else ''
            
            if limit_seen and token_value.isdigit():
                try:
                    return int(token_value)
                except:
                    pass
            
            if token.ttype is Keyword and token_value.upper() == 'LIMIT':
                limit_seen = True
        
        return None

    def _has_select_star(self, sql: str) -> bool:
        """
        Detecta uso de SELECT * / table.* no SELECT list.
        Permite COUNT(*) (caso clássico).
        """
        s = (sql or "")
        # Remover strings para evitar falsos positivos simples
        s_wo_strings = re.sub(r"('([^']|\\')*')", "''", s)

        # Capturar SELECT ... FROM
        m = re.search(r"\bselect\b(.*?)\bfrom\b", s_wo_strings, re.IGNORECASE | re.DOTALL)
        if not m:
            return False
        select_clause = m.group(1)

        # Remover COUNT(*) / SUM(*) etc para não bloquear agregações comuns
        select_clause = re.sub(r"\b(count|sum|avg|min|max)\s*\(\s*\*\s*\)", r"\1()", select_clause, flags=re.IGNORECASE)

        # Agora checar wildcard
        if re.search(r"(^|[,\s])\*\s*(,|$)", select_clause):
            return True
        if re.search(r"[A-Za-z0-9_`.\-]+\s*\.\s*\*\s*(,|$)", select_clause):
            return True
        return False

    def _count_select_items(self, sql: str) -> Optional[int]:
        """
        Conta itens no SELECT list (top-level, separado por vírgulas fora de parênteses).
        """
        s = (sql or "")
        m = re.search(r"\bselect\b(.*?)\bfrom\b", s, re.IGNORECASE | re.DOTALL)
        if not m:
            return None
        clause = m.group(1).strip()
        if not clause:
            return 0

        # Remover DISTINCT do início (não muda contagem)
        clause = re.sub(r"^\s*distinct\s+", "", clause, flags=re.IGNORECASE)
        return self._split_top_level_commas_count(clause)

    def _count_group_by_items(self, sql: str) -> Optional[int]:
        """
        Conta itens no GROUP BY (top-level).
        """
        s = (sql or "")
        m = re.search(r"\bgroup\s+by\b(.*?)(\border\s+by\b|\blimit\b|$)", s, re.IGNORECASE | re.DOTALL)
        if not m:
            return 0
        clause = m.group(1).strip()
        if not clause:
            return 0
        return self._split_top_level_commas_count(clause)

    def _split_top_level_commas_count(self, clause: str) -> int:
        depth = 0
        count = 1
        for ch in clause:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            elif ch == "," and depth == 0:
                count += 1
        return count
    
    def _has_dangerous_operations(self, statement: Statement) -> bool:
        """Verifica operações perigosas"""
        dangerous = {'INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 
                     'ALTER', 'TRUNCATE', 'EXEC', 'EXECUTE', 'CALL'}
        
        for token in statement.tokens:
            if token.ttype is Keyword and token.value.upper() in dangerous:
                return True
        
        return False
    
    def _extract_columns(self, statement: Statement, connection_type: str) -> Set[str]:
        """
        Extrai colunas usadas no SELECT.
        Retorna referências como 'table.column' ou apenas 'column'.
        """
        sql = str(statement)
        columns: Set[str] = set()
        
        # Extrair SELECT clause
        select_match = re.search(r'\bSELECT\s+(.*?)\s+FROM', sql, re.IGNORECASE | re.DOTALL)
        if not select_match:
            return columns
        
        select_clause = select_match.group(1)
        
        # Padrão para colunas:
        # - table.column
        # - `table`.`column`
        # - column
        # - `column`
        # - COUNT(*), SUM(column), etc (ignorar funções agregadas por enquanto)
        
        # Primeiro, remover funções agregadas e subconsultas
        # Simplificado: pegar identificadores que parecem colunas
        pattern = re.compile(
            r"""
            (?:
                `?([A-Za-z0-9_\-]+)`?\s*\.\s*`?([A-Za-z0-9_\-]+)`?  # table.column
                |
                `?([A-Za-z0-9_\-]+)`?                                # column (sem prefixo)
            )
            """,
            re.IGNORECASE | re.VERBOSE,
        )
        
        # Encontrar todas as colunas (ignorar dentro de funções por enquanto)
        for match in pattern.finditer(select_clause):
            if match.group(1) and match.group(2):
                # table.column
                columns.add(f"{match.group(1)}.{match.group(2)}")
            elif match.group(3):
                # column sem prefixo
                col_name = match.group(3)
                # Ignorar palavras-chave SQL comuns
                if col_name.upper() not in {'SELECT', 'FROM', 'WHERE', 'GROUP', 'ORDER', 'HAVING', 'LIMIT', 'AS'}:
                    columns.add(col_name)
        
        return columns
    
    def _split_column_reference(self, col_ref: str, connection_type: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Separa 'table.column' em (table, column).
        Se não tiver prefixo, retorna (None, column).
        """
        if '.' in col_ref:
            parts = col_ref.split('.')
            if len(parts) == 2:
                return parts[0].strip().strip('`'), parts[1].strip().strip('`')
            elif len(parts) == 3:
                # project.dataset.table.column -> (project.dataset.table, column)
                return '.'.join(parts[:-1]).strip().strip('`'), parts[-1].strip().strip('`')
            else:
                # Mais de 3 partes - retornar tudo exceto último como tabela
                return '.'.join(parts[:-1]).strip().strip('`'), parts[-1].strip().strip('`')
        return None, col_ref.strip().strip('`')

