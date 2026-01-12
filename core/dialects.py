"""Supported dialects (SQL & NoSQL) and their specific properties."""
from typing import Dict, Any
from enum import Enum


class Dialect(str, Enum):
    """Supported Data Dialects (SQL and NoSQL)."""
    # SQL
    BIGQUERY = "bigquery"
    POSTGRES = "postgres"
    MYSQL = "mysql"
    SQLSERVER = "sqlserver"
    SQLITE = "sqlite"
    ORACLE = "oracle"
    SNOWFLAKE = "snowflake"
    DATABRICKS = "databricks"
    REDSHIFT = "redshift"
    
    # NoSQL
    MONGODB = "mongodb"
    DYNAMODB = "dynamodb"
    ELASTICSEARCH = "elasticsearch"
    REDIS = "redis"
    CASSANDRA = "cassandra"


def get_dialect_specifics(dialect: Dialect) -> Dict[str, Any]:
    """
    Get dialect-specific characteristics/rules for prompting.
    """
    specifics = {
        # === SQL ===
        Dialect.BIGQUERY: {
            "type": "sql",
            "details": {
                "identifier_quote": "`",
                "string_quote": "'",
                "date_func": "CURRENT_DATE()",
            }
        },
        Dialect.POSTGRES: {
            "type": "sql",
            "details": {
                "identifier_quote": '"',
                "string_quote": "'",
                "date_func": "CURRENT_DATE",
            }
        },
        Dialect.MYSQL: {
            "type": "sql",
            "details": {
                "identifier_quote": "`",
                "string_quote": "'",
                "date_func": "CURDATE()",
            }
        },
        Dialect.SQLSERVER: {
            "type": "sql",
            "details": {
                "identifier_quote": "[",
                "string_quote": "'",
                "date_func": "GETDATE()",
            }
        },
        Dialect.SQLITE: {
            "type": "sql",
            "details": {
                "identifier_quote": '"',
                "string_quote": "'",
                "date_func": "DATE('now')",
            }
        },
        Dialect.ORACLE: {
            "type": "sql",
            "details": {
                "identifier_quote": '"',
                "string_quote": "'",
                "date_func": "SYSDATE",
            }
        },
        Dialect.SNOWFLAKE: {
            "type": "sql",
            "details": {
                "identifier_quote": '"',
                "string_quote": "'",
                "date_func": "CURRENT_DATE()",
            }
        },
        Dialect.DATABRICKS: {
            "type": "sql",
            "details": {
                "identifier_quote": "`",
                "string_quote": "'",
                "date_func": "CURRENT_DATE()",
            }
        },
        Dialect.REDSHIFT: {
            "type": "sql",
            "details": {
                "identifier_quote": '"',
                "string_quote": "'",
                "date_func": "CURRENT_DATE",
            }
        },

        # === NoSQL ===
        Dialect.MONGODB: {
            "type": "nosql",
            "details": {
                "query_language": "MongoDB Aggregation Pipeline",
                "output_format": "JSON array (strict)",
                "example": '[{"$match": {"status": "active"}}, {"$group": {"_id": "$year", "total": {"$sum": "$amount"}}}]',
            }
        },
        Dialect.DYNAMODB: {
            "type": "nosql",
            "details": {
                "query_language": "PartiQL (AWS DynamoDB)",
                "example": "SELECT * FROM Orders WHERE OrderID = 123",
            }
        },
        Dialect.ELASTICSEARCH: {
            "type": "nosql",
            "details": {
                "query_language": "Elasticsearch DSL (JSON)",
                "example": '{"query": {"match": {"content": "search term"}}}',
            }
        },
        Dialect.REDIS: {
            "type": "nosql",
            "details": {
                "query_language": "Redis Commands",
                "example": "HMGET user:1000 username email",
            }
        },
        Dialect.CASSANDRA: {
            "type": "nosql",
            "details": {
                "query_language": "CQL (Cassandra Query Language)",
                "example": "SELECT * FROM users WHERE id = 123",
            }
        },
    }
    
    return specifics.get(dialect, {})
