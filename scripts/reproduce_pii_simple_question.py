
import sys
import os
import re

# Add project root to path
sys.path.append(os.getcwd())

from core.security.pii_scanner import (
    scan_text_for_pii,
    scan_data_for_pii,
    should_allow_pii_in_aggregate_context,
    PIIDetectionResult,
    PIIType,
    PIISeverity
)

def test_scenario(name, question, sql, data):
    print(f"\n{'='*20} SCENARIO: {name} {'='*20}")
    print(f"Question: {question}")
    
    # 1. Scan Text
    text_result = scan_text_for_pii(question)
    print(f"Text Scan: Detected={text_result.detected}, Types={text_result.pii_types}, Block={text_result.should_block}")

    # 2. Scan Data
    data_result = None
    if data:
        data_result = scan_data_for_pii(data)
        print(f"Data Scan: Detected={data_result.detected}, Types={data_result.pii_types}, Block={data_result.should_block} (Types: {data_result.pii_types})")

    # 3. Check Context Logic
    allow_text = False
    allow_data = False
    
    # Use the new unified function
    try:
        from core.security.pii_scanner import should_allow_pii_exception
        check_func = should_allow_pii_exception
        func_name = "should_allow_pii_exception"
    except ImportError:
        from core.security.pii_scanner import should_allow_pii_in_aggregate_context
        check_func = should_allow_pii_in_aggregate_context
        func_name = "should_allow_pii_in_aggregate_context"
    
    if text_result.should_block:
        allow_text = check_func(
            question=question,
            sql=sql,
            data=data,
            pii_detection_result=text_result
        )
        print(f"Allow Text ({func_name})? {allow_text}")

    if data_result and data_result.should_block:
        allow_data = check_func(
            question=question,
            sql=sql,
            data=data,
            pii_detection_result=data_result
        )
        print(f"Allow Data ({func_name})? {allow_data}")
        
    final_blocked = (text_result.should_block and not allow_text) or \
                    (data_result and data_result.should_block and not allow_data)
                    
    print(f"FINAL DECISION: {'BLOCKED' if final_blocked else 'ALLOWED'}")

# --- Scenarios ---

# 1. Simple Lookup (What user complains about)
test_scenario(
    "Simple Email Lookup",
    "What is the email of John Doe?",
    "SELECT email FROM users WHERE name = 'John Doe' LIMIT 1",
    [{"email": "john.doe@example.com", "name": "John Doe"}]
)

# 2. Simple Phone Lookup
test_scenario(
    "Simple Phone Lookup",
    "Qual o telefone da Maria?",
    "SELECT phone FROM contacts WHERE name = 'Maria' LIMIT 1",
    [{"phone": "(11) 98765-4321", "name": "Maria"}]
)

# 3. Bulk Dump (Should block)
test_scenario(
    "Bulk Email Dump",
    "List all emails",
    "SELECT email FROM users",
    [
        {"email": "a@example.com"}, 
        {"email": "b@example.com"},
        {"email": "c@example.com"},
        {"email": "d@example.com"},
        {"email": "e@example.com"},
        {"email": "f@example.com"}
    ]
)

# 4. Aggregate with Name (Allowed currently?)
test_scenario(
    "Top Users by Name",
    "Who are the top 5 users?",
    "SELECT name, spend FROM users ORDER BY spend DESC LIMIT 5",
    [
        {"name": "Alice", "spend": 1000},
        {"name": "Bob", "spend": 900}
    ]
)
