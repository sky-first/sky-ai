
import sys
import os
import re

# Add project root to path
sys.path.append(os.getcwd())

from core.security.pii_scanner import (
    scan_text_for_pii,
    scan_data_for_pii,
    should_allow_pii_exception,
    PIIDetectionResult,
    PIIType
)

def simulate_connection_query_logic(name, question, sql, data):
    print(f"\n{'='*20} SCENARIO: {name} {'='*20}")
    print(f"SQL: {sql}")
    
    # 1. Scan Data
    data_scan = scan_data_for_pii(data)
    print(f"Data Scan: Detected={data_scan.detected}, Types={data_scan.pii_types}, Block={data_scan.should_block}")
    
    # 2. Check Exceptions (should_allow_pii_exception)
    allow_pii_in_data = should_allow_pii_exception(question, sql, data, data_scan)
    print(f"Exception Allowed? {allow_pii_in_data}")
    
    # 3. Connection Query Overlay Logic (Simulated)
    is_aggregated_query = False
    is_sample_query = False
    
    if sql:
        sql_upper = sql.upper()
        has_group_by = 'GROUP BY' in sql_upper
        has_aggregation = any(func in sql_upper for func in ['SUM(', 'AVG(', 'COUNT(', 'MAX(', 'MIN('])
        is_aggregated_query = has_group_by or has_aggregation
        
        match = re.search(r'LIMIT\s+(\d+)', sql_upper)
        if match:
            is_sample_query = int(match.group(1)) <= 150
            
    pii_blocked = False
    if data_scan.should_block and not allow_pii_in_data:
        if is_aggregated_query:
            print("LOGIC OVERRIDE: Allowed because is_aggregated_query")
            pii_blocked = False
        elif is_sample_query:
            print("LOGIC OVERRIDE: Allowed because is_sample_query")
            pii_blocked = False
        else:
            print("LOGIC: BLOCKED (No override)")
            pii_blocked = True
    else:
        print("LOGIC: ALLOWED (By default or Exception)")
        pii_blocked = False
        
    print(f"FINAL RESULT: {'BLOCKED' if pii_blocked else 'ALLOWED'}")

# --- Scenarios ---

# 1. Standard Aggregation (Should be Allowed)
simulate_connection_query_logic(
    "Standard Aggregation",
    "Monthly Revenue",
    "SELECT month, SUM(revenue) FROM sales GROUP BY month",
    [
        {"month": "January", "revenue": 10000},
        {"month": "February", "revenue": 15000},
        {"month": "March", "revenue": 12000},
        {"month": "April", "revenue": 11000},
        {"month": "May", "revenue": 14000},
        {"month": "June", "revenue": 16000} # > 5 rows
    ]
)

# 2. Pre-Aggregated View (No SUM/GROUP BY) -> The suspected failure case
simulate_connection_query_logic(
    "Pre-Aggregated View",
    "Monthly Revenue",
    "SELECT month, revenue FROM monthly_sales_view",
    [
        {"month": "North Region", "revenue": "$ 50000"}, # Mimic "Name + Money" contextual PII
        {"month": "South Region", "revenue": "$ 45000"},
        {"month": "East Region", "revenue": "$ 30000"},
        {"month": "West Region", "revenue": "$ 25000"},
        {"month": "Central Region", "revenue": "$ 40000"},
        {"month": "Overseas", "revenue": "$ 10000"}
    ]
)

# 3. Phone-like numbers (Integer confusion)
simulate_connection_query_logic(
    "Integer as Phone",
    "Total Sales IDs",
    "SELECT sale_id FROM sales", 
    [
        {"sale_id": 1234567890},
        {"sale_id": 9876543210},
        {"sale_id": 1122334455},
        {"sale_id": 5566778899},
        {"sale_id": 6677889900},
        {"sale_id": 7788990011}
    ]
)
