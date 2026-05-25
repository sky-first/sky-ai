import re


def _extract_table_choice(raw_llm_response, logical_names):
    text = raw_llm_response.strip().lower()
    text = re.sub(r"[\"'`]", "", text)

    for name in logical_names:
        lname = name.lower()
        if text and (text in lname or lname in text):
            return name
    return ""


logical_names = ["Invoices", "Products", "Users"]
response = "I think you should use the Invoices table."
choice = _extract_table_choice(response, logical_names)
print(f"Response: '{response}'")
print(f"Choice: '{choice}'")

response_only = "Invoices"
choice_only = _extract_table_choice(response_only, logical_names)
print(f"Response: '{response_only}'")
print(f"Choice: '{choice_only}'")
