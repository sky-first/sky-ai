
from core.security.pii_scanner import scan_text_for_pii

text = "Show me the names of the top 10 products."
result = scan_text_for_pii(text)
print(f"Text: {text}")
print(f"  Detected: {result.detected}")
if result.detected:
    print(f"  Types: {result.pii_types}")
    print(f"  Should Block: {result.should_block}")
    print(f"  Patterns: {result.patterns_matched}")
