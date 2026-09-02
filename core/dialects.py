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
    NOSQL = "nosql"  # Generic / API


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
                # Estavam cravados no `specialist.py`, num `if` só para o
                # BigQuery. Vieram para aqui quando o Postgres precisou dos
                # seus: as manias de cada base pertencem à descrição da base.
                "warnings": (
                    "BIGQUERY CRITICAL RULES:\n"
                    "- NEVER USE ILIKE. BigQuery does not support ILIKE.\n"
                    "- For case-insensitive search, use WHERE UPPER(col) LIKE '%VALUE%'\n"
                    "- ALWAYS use FULLY QUALIFIED table names (project.dataset.table).\n\n"
                ),
            },
        },
        Dialect.POSTGRES: {
            "type": "sql",
            "details": {
                "identifier_quote": '"',
                "string_quote": "'",
                "date_func": "CURRENT_DATE",
                # ── ROUND com casas decimais não existe para floats. ────
                #
                # No Postgres o `round(x, n)` só está definido para
                # `numeric`. Aplicado a um `double precision` — que é o que
                # sai de qualquer divisão ou `AVG()` — a base recusa:
                #
                #     function round(double precision, integer) does not exist
                #
                # Apanhado a 02/09/2026 pelo teste das 20 perguntas, na
                # pergunta sobre DAU/MAU. E não é um caso de bordo: um rácio
                # é uma divisão, e arredondá-lo é o gesto seguinte mais
                # natural do mundo.
                "warnings": (
                    "POSTGRES CRITICAL RULES:\n"
                    "- ROUND(x, n) only exists for NUMERIC. Any division or "
                    "AVG() yields DOUBLE PRECISION, and ROUND on it fails with "
                    "'function round(double precision, integer) does not exist'.\n"
                    "- ALWAYS cast first: ROUND(expr::numeric, 2)\n\n"
                ),
            },
        },
        Dialect.MYSQL: {
            "type": "sql",
            "details": {
                "identifier_quote": "`",
                "string_quote": "'",
                "date_func": "CURDATE()",
            },
        },
        Dialect.SQLSERVER: {
            "type": "sql",
            "details": {
                "identifier_quote": "[",
                "string_quote": "'",
                "date_func": "GETDATE()",
            },
        },
        Dialect.SQLITE: {
            "type": "sql",
            "details": {
                "identifier_quote": '"',
                "string_quote": "'",
                "date_func": "DATE('now')",
            },
        },
        Dialect.ORACLE: {
            "type": "sql",
            "details": {
                "identifier_quote": '"',
                "string_quote": "'",
                "date_func": "SYSDATE",
            },
        },
        Dialect.SNOWFLAKE: {
            "type": "sql",
            "details": {
                "identifier_quote": '"',
                "string_quote": "'",
                "date_func": "CURRENT_DATE()",
            },
        },
        Dialect.DATABRICKS: {
            "type": "sql",
            "details": {
                "identifier_quote": "`",
                "string_quote": "'",
                "date_func": "CURRENT_DATE()",
            },
        },
        Dialect.REDSHIFT: {
            "type": "sql",
            "details": {
                "identifier_quote": '"',
                "string_quote": "'",
                "date_func": "CURRENT_DATE",
            },
        },
        # === NoSQL ===
        Dialect.MONGODB: {
            "type": "nosql",
            "details": {
                "query_language": "MongoDB Aggregation Pipeline",
                "output_format": "JSON array (strict)",
                "example": '[{"$match": {"status": "active"}}, {"$group": {"_id": "$year", "total": {"$sum": "$amount"}}}]',
            },
        },
        Dialect.DYNAMODB: {
            "type": "nosql",
            "details": {
                "query_language": "PartiQL (AWS DynamoDB)",
                "example": "SELECT * FROM Orders WHERE OrderID = 123",
            },
        },
        Dialect.ELASTICSEARCH: {
            "type": "nosql",
            "details": {
                "query_language": "Elasticsearch DSL (JSON)",
                "example": '{"query": {"match": {"content": "search term"}}}',
            },
        },
        Dialect.REDIS: {
            "type": "nosql",
            "details": {
                "query_language": "Redis Commands",
                "example": "HMGET user:1000 username email",
            },
        },
        Dialect.CASSANDRA: {
            "type": "nosql",
            "details": {
                "query_language": "CQL (Cassandra Query Language)",
                "example": "SELECT * FROM users WHERE id = 123",
            },
        },
        Dialect.NOSQL: {
            "type": "nosql",
            "details": {
                "query_language": "JSON / API Payload",
                "output_format": "JSON",
                "example": '{"endpoint": "/users", "params": {"active": true}}',
            },
        },
    }

    return specifics.get(dialect, {})
