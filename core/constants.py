"""Application constants and limits."""
from typing import Dict, Any

# Query limits
MAX_QUERY_RESULTS = 1000
MAX_SQL_LENGTH = 10000
QUERY_TIMEOUT_SECONDS = 300

# SQL validation
ALLOWED_SQL_KEYWORDS = {
    "SELECT", "FROM", "WHERE", "GROUP BY", "ORDER BY", "HAVING",
    "LIMIT", "OFFSET", "JOIN", "INNER JOIN", "LEFT JOIN", "RIGHT JOIN",
    "UNION", "UNION ALL", "AS", "DISTINCT", "COUNT", "SUM", "AVG", "MAX", "MIN"
}

FORBIDDEN_SQL_KEYWORDS = {
    "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE", "TRUNCATE",
    "EXEC", "EXECUTE", "GRANT", "REVOKE"
}

# Data source types
DATA_SOURCE_TYPES = {
    "bigquery": "BigQuery",
    "postgres": "PostgreSQL",
    "mysql": "MySQL",
    "sqlserver": "SQL Server",
    "databricks": "Databricks",
    "redshift": "Redshift",
    "api": "REST/GraphQL API"
}

# Agent limits
MAX_AGENT_CONTEXT_TOKENS = 8000
MAX_RETRIEVAL_DOCUMENTS = 10

# Permissions
PERMISSION_READ = "read"
PERMISSION_WRITE = "write"
PERMISSION_ADMIN = "admin"

