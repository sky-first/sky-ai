import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.sql.validator_advanced import AdvancedSQLValidator


def debug_validator():
    validator = AdvancedSQLValidator(
        allowed_tables=["project.dataset.table", "orders", "revenue"]
    )

    # Guessing the query that failed
    print("--- Test 1: DATE_SUB in WHERE ---")
    sql1 = (
        "SELECT * FROM orders WHERE date > DATE_SUB(CURRENT_DATE(), INTERVAL 1 MONTH)"
    )
    tables1 = validator._extract_tables(
        sql1
    )  # Note: _extract_tables takes Statement, but in code it calls str(statement).
    # Wait, the method signature is `_extract_tables(self, statement: Statement)`.
    # But inside it does `sql = str(statement)`.
    # So I can pass a string mock if I'm careful or I should parse it first.

    import sqlparse

    try:
        parsed1 = sqlparse.parse(sql1)[0]
        tables1 = validator._extract_tables(parsed1)
    except:
        # Fallback if _extract_tables expects something else or fails
        tables1 = "Error"

    print(f"SQL: {sql1}")
    print(f"Tables Extracted: {tables1}")

    print("\n--- Test 2: DATE_SUB in SELECT ---")
    sql2 = "SELECT DATE_SUB(NOW(), INTERVAL 1 DAY) as yesterday"
    parsed2 = sqlparse.parse(sql2)[0]
    tables2 = validator._extract_tables(parsed2)
    print(f"SQL: {sql2}")
    print(f"Tables Extracted: {tables2}")

    print(
        "\n--- Test 3: JOIN with DATE_SUB (Unlikely valid SQL but maybe generated) ---"
    )
    sql3 = "SELECT * FROM orders JOIN DATE_SUB(now())"
    parsed3 = sqlparse.parse(sql3)[0]
    tables3 = validator._extract_tables(parsed3)
    print(f"SQL: {sql3}")
    print(f"Tables Extracted: {tables3}")

    # Maybe the regex matches something else?
    print("\n--- Regex Check ---")
    import re

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
    print("Matching SQL1 against regex:")
    for m in pattern.finditer(sql1):
        print(f"Match: {m.group('ident')}")


if __name__ == "__main__":
    debug_validator()
