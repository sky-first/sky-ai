from core.security.pii_scanner import scan_text_for_pii

questions = [
    "What was the total sales last month?",
    "What are the top 10 best-selling products?",
    "Show me the revenue by region.",
    "Which products have low stock?",
    "Who are the most profitable customers?",
    "What is the average ticket size?",
    "What is the sales forecast for next month?",
    "What are the sales of the customer 'Sky'?",
    "Performance of the region 'North' last year.",
]

for q in questions:
    result = scan_text_for_pii(q)
    print(f"Q: {q}")
    print(f"  Detected: {result.detected}")
    if result.detected:
        print(f"  Types: {result.pii_types}")
        print(f"  Should Block: {result.should_block}")
        print(f"  Patterns: {result.patterns_matched}")
    print("-" * 20)
