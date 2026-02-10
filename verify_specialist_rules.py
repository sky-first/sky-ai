
import sys
import os

# Function to mock the environment for testing
def test_specialist_rules():
    print("Testing Specialist Rules...")
    
    # Import the function that builds the prompt
    from core.llm.specialist import _build_secure_system_prompt
    
    # Generate prompt with defaults
    prompt = _build_secure_system_prompt(["my_table"])
    content = prompt["content"]
    
    # Check for the presence of the new relaxed rule
    expected_rule = "You MAY use DATE_SUB, INTERVAL, or specific date filters"
    
    if expected_rule in content:
        print("✅ SUCCESS: Found relaxed temporal filtering rule in prompt.")
    else:
        print("❌ FAILURE: Relaxed rule NOT found in prompt.")
        print("Snippet of content:")
        print(content[:500] + "...")

    # Check that the critical prohibition is GONE
    forbidden_rule = "NEVER use WHERE with DATE_SUB"
    if forbidden_rule not in content:
        print("✅ SUCCESS: Strict prohibition on DATE_SUB is gone.")
    else:
        print("❌ FAILURE: Strict prohibition still present!")

if __name__ == "__main__":
    test_specialist_rules()
