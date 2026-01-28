"""SQL dialect-specific utilities."""
from typing import Dict, Any
from enum import Enum


class SQLDialect(str, Enum):
    """Supported SQL dialects."""
    BIGQUERY = "bigquery"
    POSTGRES = "postgres"
    MYSQL = "mysql"
    SQLSERVER = "sqlserver"
    DATABRICKS = "databricks"
    REDSHIFT = "redshift"


def get_dialect_specifics(dialect: SQLDialect) -> Dict[str, Any]:
    """
    Get dialect-specific SQL characteristics.
    
    Args:
        dialect: SQL dialect
    
    Returns:
        Dictionary with dialect-specific information
    """
    specifics = {
        SQLDialect.BIGQUERY: {
            "identifier_quote": "`",
            "string_quote": "'",
            "supports_schemas": True,
            "array_syntax": "ARRAY[...]",
            "date_functions": {
                "current_date": "CURRENT_DATE()",
                "current_timestamp": "CURRENT_TIMESTAMP()"
            }
        },
        SQLDialect.POSTGRES: {
            "identifier_quote": '"',
            "string_quote": "'",
            "supports_schemas": True,
            "array_syntax": "ARRAY[...]",
            "date_functions": {
                "current_date": "CURRENT_DATE",
                "current_timestamp": "NOW()"
            }
        },
        SQLDialect.MYSQL: {
            "identifier_quote": "`",
            "string_quote": "'",
            "supports_schemas": True,
            "array_syntax": "JSON_ARRAY(...)",
            "date_functions": {
                "current_date": "CURDATE()",
                "current_timestamp": "NOW()"
            }
        },
        SQLDialect.SQLSERVER: {
            "identifier_quote": "[",
            "string_quote": "'",
            "supports_schemas": True,
            "array_syntax": "JSON_ARRAY(...)",
            "date_functions": {
                "current_date": "GETDATE()",
                "current_timestamp": "GETDATE()"
            }
        },
        SQLDialect.DATABRICKS: {
            "identifier_quote": "`",
            "string_quote": "'",
            "supports_schemas": True,
            "array_syntax": "ARRAY(...)",
            "date_functions": {
                "current_date": "CURRENT_DATE()",
                "current_timestamp": "CURRENT_TIMESTAMP()"
            }
        },
        SQLDialect.REDSHIFT: {
            "identifier_quote": '"',
            "string_quote": "'",
            "supports_schemas": True,
            "array_syntax": "ARRAY[...]",
            "date_functions": {
                "current_date": "CURRENT_DATE",
                "current_timestamp": "GETDATE()"
            }
        }
    }
    
    return specifics.get(dialect, {})


def quote_identifier(identifier: str, dialect: SQLDialect) -> str:
    """
    Quote an identifier according to dialect rules.
    
    Args:
        identifier: Identifier to quote
        dialect: SQL dialect
    
    Returns:
        Quoted identifier
    """
    specifics = get_dialect_specifics(dialect)
    quote_char = specifics.get("identifier_quote", '"')
    
    if quote_char == "[":
        return f"[{identifier}]"
    else:
        return f"{quote_char}{identifier}{quote_char}"

