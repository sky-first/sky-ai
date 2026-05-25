import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from core.security.pii_scanner import scan_text_for_pii, scan_data_for_pii, PIIType


def test_toxic_blocking(name, text, data):
    print(f"\n{'='*20} SCENARIO: {name} {'='*20}")

    # Text Scan
    if text:
        text_result = scan_text_for_pii(text)
        print(f"Text: Block={text_result.should_block}, Types={text_result.pii_types}")

    # Data Scan
    if data:
        data_result = scan_data_for_pii(data)
        print(f"Data: Block={data_result.should_block}, Types={data_result.pii_types}")


# 1. SSN (Should BLOCK)
test_toxic_blocking("SSN in Text", "My SSN is 123-45-6789", None)
test_toxic_blocking("SSN in Data", None, [{"ssn": "123-45-6789"}])

# 2. Credit Card (Should BLOCK)
test_toxic_blocking(
    "Credit Card", "Card: 1234-5678-9012-3456", [{"cc": "1234-5678-9012-3456"}]
)

# 3. Email (Should ALLOW - Warn only)
test_toxic_blocking("Email List", "List all emails", [{"email": "test@example.com"}])
