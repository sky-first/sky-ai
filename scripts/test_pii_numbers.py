
from core.security.pii_scanner import scan_text_for_pii

text = "Calculate the total for orders 1234567890 and 0987654321."
result = scan_text_for_pii(text)
print(f"Text: {text}")
print(f"  Detected: {result.detected}")
if result.detected:
    print(f"  Types: {result.pii_types}")
    print(f"  Should Block: {result.should_block}")
    print(f"  Patterns: {result.patterns_matched}")
