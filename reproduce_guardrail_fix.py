
import re

def check_guardrail_regex(sql, allowed_physical_names, all_physical_names):
    sql_check = sql.lower()
    allowed_lower = set(p.lower() for p in allowed_physical_names)
    
    # Identify forbidden tables
    forbidden_tables = [p for p in all_physical_names if p.lower() not in allowed_lower]
    
    print(f"Allowed: {allowed_lower}")
    print(f"Forbidden: {forbidden_tables}")
    print(f"SQL: {sql_check}")
    
    for bad_table in forbidden_tables:
        bad_table_lower = bad_table.lower()
        
        # PROPOSED FIX: Regex with boundary check
        # We want to ensure bad_table is matched as a whole word/identifier
        # Allowed chars in identifiers: a-z, 0-9, _, $
        # So boundary is anything NOT in that set.
        
        # Escape bad_table (it might have dots)
        escaped_bad = re.escape(bad_table_lower)
        
        # Pattern: (Start or non-id-char) + bad_table + (non-id-char or End)
        pattern = r"(?:^|[^a-z0-9_$])" + escaped_bad + r"(?:[^a-z0-9_$]|$)"
        
        if re.search(pattern, sql_check):
             print(f"🚨 BLOCKED! Found forbidden table '{bad_table}' in SQL using regex.")
             return False, f"Unauthorized table detected: {bad_table}"
             
    print("✅ PASSED guardrail.")
    return True, None

# Scenario 1: Overlapping table names (should PASS now)
print("--- Senario 1: Overlapping names (Regex Fix) ---")
allowed = ["project.dataset.users_enriched"]
all_tables = ["project.dataset.users", "project.dataset.users_enriched"]
sql = "SELECT * FROM `project.dataset.users_enriched` LIMIT 10"

check_guardrail_regex(sql, allowed, all_tables)

# Scenario 2: Partial overlap (should PASS now)
print("\n--- Scenario 2: Partial overlap (Regex Fix) ---")
allowed = ["orders_final"]
all_tables = ["orders", "orders_final"]
sql = "SELECT * FROM orders_final"

check_guardrail_regex(sql, allowed, all_tables)

# Scenario 3: Real forbidden table (should BLOCK)
print("\n--- Scenario 3: Real forbidden match (Should BLOCK) ---")
allowed = ["orders_final"]
all_tables = ["orders", "orders_final"]
sql = "SELECT * FROM orders"

check_guardrail_regex(sql, allowed, all_tables)

# Scenario 4: Forbidden matches inside string literal? (Corner case)
# Ideally SQL parsing handles this, but regex is naive.
# If I select 'orders' as a string, it might block. But that's acceptable for a guardrail.
print("\n--- Scenario 4: String literal (Accepted False Positive) ---")
allowed = ["orders_final"]
all_tables = ["orders", "orders_final"]
sql = "SELECT 'orders' as table_name FROM orders_final"
check_guardrail_regex(sql, allowed, all_tables)

