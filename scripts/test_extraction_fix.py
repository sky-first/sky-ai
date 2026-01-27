
from typing import List
from dataclasses import dataclass
import sys
import os

import re
from typing import List
from dataclasses import dataclass

@dataclass
class TableSchema:
    logical_name: str
    physical_name: str = ""

# COPY OF THE FUNCTION TO TEST LOGIC ISOLATION
def _extract_multiple_table_choices(raw_llm_response, tables: List[TableSchema]) -> List[str]:
    """
    Extrai múltiplos logical_names retornados pelo LLM.
    Suporta formatos como: "table1, table2" ou "table1 and table2" ou lista separada por vírgulas.
    """
    text = ""
    if isinstance(raw_llm_response, str):
        text = raw_llm_response
    else:
        text = getattr(raw_llm_response, "content", "") or ""

    text = text.strip().lower()
    text = re.sub(r"[\"'`]", "", text)

    logical_names = [t.logical_name.lower() for t in tables]
    found_tables = []

    # Tentar separar por vírgula, "and", ou nova linha
    parts = re.split(r'[,;\n]|\sand\s', text)
    
    for part in parts:
        part = part.strip()
        if not part:
            continue
        
        # Match exato
        for name in logical_names:
            if part == name:
                table_name = next(t.logical_name for t in tables if t.logical_name.lower() == name)
                if table_name not in found_tables:
                    found_tables.append(table_name)
                break
        
        # Match parcial
        for name in logical_names:
            if name in part and name not in [t.lower() for t in found_tables]:
                table_name = next(t.logical_name for t in tables if t.logical_name.lower() == name)
                if table_name not in found_tables:
                    found_tables.append(table_name)
                break

    return found_tables

def test_extraction():
    tables = [
        TableSchema(logical_name="Invoices"),
        TableSchema(logical_name="Payments"),
        TableSchema(logical_name="Customers"),
        TableSchema(logical_name="Items"),
    ]

    # Test case 1: Comma separated
    response1 = "Invoices, Payments"
    extracted1 = _extract_multiple_table_choices(response1, tables)
    print(f"Input: '{response1}' -> Extracted: {extracted1}")
    assert "Invoices" in extracted1
    assert "Payments" in extracted1
    
    # Test case 2: 'and' separator
    response2 = "I need data from Customers and Items"
    extracted2 = _extract_multiple_table_choices(response2, tables)
    print(f"Input: '{response2}' -> Extracted: {extracted2}")
    assert "Customers" in extracted2
    assert "Items" in extracted2

    # Test case 3: Newlines
    response3 = "Invoices\nPayments"
    extracted3 = _extract_multiple_table_choices(response3, tables)
    print(f"Input: '{response3}' -> Extracted: {extracted3}")
    assert "Invoices" in extracted3
    assert "Payments" in extracted3

    print("\nALL TESTS PASSED")

if __name__ == "__main__":
    test_extraction()
