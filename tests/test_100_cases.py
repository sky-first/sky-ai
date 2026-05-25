#!/usr/bin/env python3
"""
100 Test Cases for Sky AI Chat Pipeline
Validates the full LLM pipeline: Orchestrator → Specialist → Formatter
Generates a markdown report: test_report.md

Usage:
    python tests/test_100_cases.py
    python tests/test_100_cases.py --parallel   # run concurrently (faster)
"""

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

# ─── Configuration ────────────────────────────────────────────────────────────
API_BASE_URL = "http://localhost:8001"
CONNECTION_ID = "aaaa0001-0000-4000-a000-000000000001"
SPACE_ID = "d21795e0-430c-4f72-99ae-4c61512e17d1"
USER_ID = "32a2a83c-5dc9-4a82-b228-6fa976c173b1"
CREW_IDS = []
HEADERS = {"Content-Type": "application/json"}
TIMEOUT = 120.0
SLOW_THRESHOLD = 30.0  # seconds — warning if above
ERROR_THRESHOLD = 60.0  # seconds — fail if above

REPORT_PATH = Path(__file__).parent / "test_report.md"

# ─── Test Case Definitions (100 cases, English) ───────────────────────────────
TEST_CASES: List[Dict[str, Any]] = [
    # ── Category 1: Basic Counts & Totals ─────────────────────────────────
    {
        "id": "BAS-001",
        "category": "Basic Counts",
        "question": "How many customers do we have in total?",
    },
    {
        "id": "BAS-002",
        "category": "Basic Counts",
        "question": "What is the total number of orders?",
    },
    {
        "id": "BAS-003",
        "category": "Basic Counts",
        "question": "How many products are in our catalog?",
    },
    {
        "id": "BAS-004",
        "category": "Basic Counts",
        "question": "What is the total revenue?",
    },
    {
        "id": "BAS-005",
        "category": "Basic Counts",
        "question": "How many active users do we have?",
    },
    {
        "id": "BAS-006",
        "category": "Basic Counts",
        "question": "What is the total number of transactions?",
    },
    {
        "id": "BAS-007",
        "category": "Basic Counts",
        "question": "How many employees are registered in the system?",
    },
    {
        "id": "BAS-008",
        "category": "Basic Counts",
        "question": "What is the total sales amount?",
    },
    {
        "id": "BAS-009",
        "category": "Basic Counts",
        "question": "How many pending orders do we have?",
    },
    {
        "id": "BAS-010",
        "category": "Basic Counts",
        "question": "What is the total number of completed orders?",
    },
    # ── Category 2: Temporal Queries ──────────────────────────────────────
    {
        "id": "TMP-001",
        "category": "Temporal",
        "question": "What was the total revenue last month?",
    },
    {
        "id": "TMP-002",
        "category": "Temporal",
        "question": "How many new customers signed up this year?",
    },
    {
        "id": "TMP-003",
        "category": "Temporal",
        "question": "What were the total sales in the last 7 days?",
    },
    {
        "id": "TMP-004",
        "category": "Temporal",
        "question": "What is the revenue for the current quarter?",
    },
    {
        "id": "TMP-005",
        "category": "Temporal",
        "question": "How many orders were placed last week?",
    },
    {
        "id": "TMP-006",
        "category": "Temporal",
        "question": "What was the revenue in January this year?",
    },
    {
        "id": "TMP-007",
        "category": "Temporal",
        "question": "How many customers joined in the last 30 days?",
    },
    {
        "id": "TMP-008",
        "category": "Temporal",
        "question": "What is the monthly revenue trend for this year?",
    },
    {
        "id": "TMP-009",
        "category": "Temporal",
        "question": "How many products were sold last quarter?",
    },
    {
        "id": "TMP-010",
        "category": "Temporal",
        "question": "What were the top selling days this month?",
    },
    # ── Category 3: Rankings & Top-N ──────────────────────────────────────
    {
        "id": "RNK-001",
        "category": "Rankings",
        "question": "What are the top 10 best-selling products?",
    },
    {
        "id": "RNK-002",
        "category": "Rankings",
        "question": "Who are the top 5 customers by total revenue?",
    },
    {
        "id": "RNK-003",
        "category": "Rankings",
        "question": "What are the 3 worst performing products by revenue?",
    },
    {
        "id": "RNK-004",
        "category": "Rankings",
        "question": "Which are the top 5 sales regions?",
    },
    {
        "id": "RNK-005",
        "category": "Rankings",
        "question": "What are the top 10 most profitable orders?",
    },
    {
        "id": "RNK-006",
        "category": "Rankings",
        "question": "Who are the top 5 sales representatives by revenue?",
    },
    {
        "id": "RNK-007",
        "category": "Rankings",
        "question": "What are the 5 most ordered product categories?",
    },
    {
        "id": "RNK-008",
        "category": "Rankings",
        "question": "Which customers have placed the most orders this year?",
    },
    {
        "id": "RNK-009",
        "category": "Rankings",
        "question": "What are the top 5 products by profit margin?",
    },
    {
        "id": "RNK-010",
        "category": "Rankings",
        "question": "Which are the lowest revenue regions?",
    },
    # ── Category 4: Averages & Aggregations ───────────────────────────────
    {
        "id": "AGG-001",
        "category": "Aggregations",
        "question": "What is the average order value?",
    },
    {
        "id": "AGG-002",
        "category": "Aggregations",
        "question": "What is the average revenue per customer?",
    },
    {
        "id": "AGG-003",
        "category": "Aggregations",
        "question": "What is the average number of items per order?",
    },
    {
        "id": "AGG-004",
        "category": "Aggregations",
        "question": "What is the average profit margin across all products?",
    },
    {
        "id": "AGG-005",
        "category": "Aggregations",
        "question": "What is the average customer lifetime value?",
    },
    {
        "id": "AGG-006",
        "category": "Aggregations",
        "question": "What is the average time between orders per customer?",
    },
    {
        "id": "AGG-007",
        "category": "Aggregations",
        "question": "What is the average revenue per transaction?",
    },
    {
        "id": "AGG-008",
        "category": "Aggregations",
        "question": "What is the total revenue grouped by product category?",
    },
    {
        "id": "AGG-009",
        "category": "Aggregations",
        "question": "What is the average discount applied per order?",
    },
    {
        "id": "AGG-010",
        "category": "Aggregations",
        "question": "What is the average number of products per order?",
    },
    # ── Category 5: Trends & Growth ───────────────────────────────────────
    {
        "id": "TRN-001",
        "category": "Trends",
        "question": "What is the monthly growth rate in revenue?",
    },
    {
        "id": "TRN-002",
        "category": "Trends",
        "question": "How has the number of customers grown over the past year?",
    },
    {
        "id": "TRN-003",
        "category": "Trends",
        "question": "What is the year-over-year revenue comparison?",
    },
    {
        "id": "TRN-004",
        "category": "Trends",
        "question": "Is revenue trending up or down this quarter?",
    },
    {
        "id": "TRN-005",
        "category": "Trends",
        "question": "What is the week-over-week growth in new orders?",
    },
    {
        "id": "TRN-006",
        "category": "Trends",
        "question": "How have sales evolved over the last 6 months?",
    },
    {
        "id": "TRN-007",
        "category": "Trends",
        "question": "What is the customer churn rate trend?",
    },
    {
        "id": "TRN-008",
        "category": "Trends",
        "question": "How has the average order value changed over time?",
    },
    {
        "id": "TRN-009",
        "category": "Trends",
        "question": "What is the revenue growth rate compared to last year?",
    },
    {
        "id": "TRN-010",
        "category": "Trends",
        "question": "Show me the sales trend for the last 12 months",
    },
    # ── Category 6: Segmentation & Breakdown ──────────────────────────────
    {
        "id": "SEG-001",
        "category": "Segmentation",
        "question": "What is the revenue breakdown by region?",
    },
    {
        "id": "SEG-002",
        "category": "Segmentation",
        "question": "How many customers are in each segment?",
    },
    {
        "id": "SEG-003",
        "category": "Segmentation",
        "question": "What is the order distribution by status?",
    },
    {
        "id": "SEG-004",
        "category": "Segmentation",
        "question": "How is revenue distributed across product categories?",
    },
    {
        "id": "SEG-005",
        "category": "Segmentation",
        "question": "What percentage of orders come from repeat customers?",
    },
    {
        "id": "SEG-006",
        "category": "Segmentation",
        "question": "How is sales volume distributed by day of the week?",
    },
    {
        "id": "SEG-007",
        "category": "Segmentation",
        "question": "What is the revenue split between new and existing customers?",
    },
    {
        "id": "SEG-008",
        "category": "Segmentation",
        "question": "How many orders are in each status category?",
    },
    {
        "id": "SEG-009",
        "category": "Segmentation",
        "question": "What is the customer distribution by country?",
    },
    {
        "id": "SEG-010",
        "category": "Segmentation",
        "question": "How is the product portfolio distributed by category?",
    },
    # ── Category 7: Customer Analysis ─────────────────────────────────────
    {
        "id": "CUS-001",
        "category": "Customer Analysis",
        "question": "Who are the most loyal customers by number of orders?",
    },
    {
        "id": "CUS-002",
        "category": "Customer Analysis",
        "question": "Which customers have not ordered in the last 90 days?",
    },
    {
        "id": "CUS-003",
        "category": "Customer Analysis",
        "question": "What is the customer retention rate?",
    },
    {
        "id": "CUS-004",
        "category": "Customer Analysis",
        "question": "Which customers have the highest average order value?",
    },
    {
        "id": "CUS-005",
        "category": "Customer Analysis",
        "question": "How many customers made only one purchase?",
    },
    {
        "id": "CUS-006",
        "category": "Customer Analysis",
        "question": "What is the average number of orders per customer?",
    },
    {
        "id": "CUS-007",
        "category": "Customer Analysis",
        "question": "Which customers generated the most revenue this year?",
    },
    {
        "id": "CUS-008",
        "category": "Customer Analysis",
        "question": "What is the new customer acquisition rate per month?",
    },
    {
        "id": "CUS-009",
        "category": "Customer Analysis",
        "question": "Which customers have the highest purchase frequency?",
    },
    {
        "id": "CUS-010",
        "category": "Customer Analysis",
        "question": "How many customers have placed more than 5 orders?",
    },
    # ── Category 8: Product & Inventory Analysis ──────────────────────────
    {
        "id": "PRD-001",
        "category": "Product Analysis",
        "question": "Which products have low stock levels?",
    },
    {
        "id": "PRD-002",
        "category": "Product Analysis",
        "question": "What is the profit margin per product?",
    },
    {
        "id": "PRD-003",
        "category": "Product Analysis",
        "question": "Which products have never been ordered?",
    },
    {
        "id": "PRD-004",
        "category": "Product Analysis",
        "question": "What is the revenue contribution of each product category?",
    },
    {
        "id": "PRD-005",
        "category": "Product Analysis",
        "question": "Which products have the highest cancellation rate?",
    },
    {
        "id": "PRD-006",
        "category": "Product Analysis",
        "question": "What is the average selling price per product?",
    },
    {
        "id": "PRD-007",
        "category": "Product Analysis",
        "question": "Which products are driving the most revenue growth?",
    },
    {
        "id": "PRD-008",
        "category": "Product Analysis",
        "question": "How many products are currently out of stock?",
    },
    {
        "id": "PRD-009",
        "category": "Product Analysis",
        "question": "What are the top selling products by quantity?",
    },
    {
        "id": "PRD-010",
        "category": "Product Analysis",
        "question": "Which products have the best reviews or ratings?",
    },
    # ── Category 9: Financial Metrics ─────────────────────────────────────
    {
        "id": "FIN-001",
        "category": "Financial",
        "question": "What is the gross profit for this month?",
    },
    {
        "id": "FIN-002",
        "category": "Financial",
        "question": "What is the net revenue after discounts?",
    },
    {
        "id": "FIN-003",
        "category": "Financial",
        "question": "What is the cost of goods sold this quarter?",
    },
    {
        "id": "FIN-004",
        "category": "Financial",
        "question": "What is the revenue per sales channel?",
    },
    {
        "id": "FIN-005",
        "category": "Financial",
        "question": "What is the total discount amount given this month?",
    },
    {
        "id": "FIN-006",
        "category": "Financial",
        "question": "What is the average transaction value by payment method?",
    },
    {
        "id": "FIN-007",
        "category": "Financial",
        "question": "What is the refund rate this quarter?",
    },
    {
        "id": "FIN-008",
        "category": "Financial",
        "question": "What are the total cancellations and their financial impact?",
    },
    {
        "id": "FIN-009",
        "category": "Financial",
        "question": "What is the revenue achieved vs target this month?",
    },
    {
        "id": "FIN-010",
        "category": "Financial",
        "question": "What is the sales commission total for this month?",
    },
    # ── Category 10: Edge Cases & Off-topic ───────────────────────────────
    # These should be handled gracefully (not crash), even if they return no data
    {
        "id": "EDG-001",
        "category": "Edge Cases",
        "question": "How are we doing overall?",
        "expect_graceful": True,
    },
    {
        "id": "EDG-002",
        "category": "Edge Cases",
        "question": "What happened yesterday?",
        "expect_graceful": True,
    },
    {
        "id": "EDG-003",
        "category": "Edge Cases",
        "question": "Compare this month to last month in revenue",
        "expect_graceful": True,
    },
    {
        "id": "EDG-004",
        "category": "Edge Cases",
        "question": "Is business growing?",
        "expect_graceful": True,
    },
    {
        "id": "EDG-005",
        "category": "Edge Cases",
        "question": "What should I focus on to improve sales?",
        "expect_graceful": True,
    },
    {
        "id": "EDG-006",
        "category": "Edge Cases",
        "question": "Give me a summary of the business performance",
        "expect_graceful": True,
    },
    {
        "id": "EDG-007",
        "category": "Edge Cases",
        "question": "What is the weather like today?",
        "expect_graceful": True,
        "expect_no_sql": True,
    },
    {
        "id": "EDG-008",
        "category": "Edge Cases",
        "question": "Tell me a joke",
        "expect_graceful": True,
        "expect_no_sql": True,
    },
    {
        "id": "EDG-009",
        "category": "Edge Cases",
        "question": "How do I reset my password?",
        "expect_graceful": True,
        "expect_no_sql": True,
    },
    {
        "id": "EDG-010",
        "category": "Edge Cases",
        "question": "What is 2 + 2?",
        "expect_graceful": True,
        "expect_no_sql": True,
    },
]

assert len(TEST_CASES) == 100, f"Expected 100 test cases, got {len(TEST_CASES)}"


# ─── Result Evaluation ────────────────────────────────────────────────────────
def evaluate_result(
    tc: Dict[str, Any],
    resp_data: Optional[Dict],
    elapsed: float,
    http_status: Optional[int],
    error: Optional[str],
) -> Dict[str, Any]:
    """Returns a result dict with status PASS / WARN / FAIL and reasons."""
    reasons: List[str] = []
    status = "PASS"

    if error:
        return {"status": "FAIL", "reasons": [f"Exception: {error[:200]}"]}

    if http_status != 200:
        return {"status": "FAIL", "reasons": [f"HTTP {http_status}"]}

    if not resp_data:
        return {"status": "FAIL", "reasons": ["Empty response body"]}

    answer = resp_data.get("answer") or ""
    meta = resp_data.get("meta") or {}
    # SQL is stored in meta.sql (not top-level)
    sql = meta.get("sql") or resp_data.get("sql") or ""
    data_sample = resp_data.get("data_sample") or []

    # 1. Answer must be present
    if not answer.strip():
        status = "FAIL"
        reasons.append("Answer is empty")

    # 2. Answer must not be a raw Python error / traceback
    # Note: "500" alone is not a reliable marker (can be a count like "500 orders")
    for bad in [
        "Traceback",
        "AttributeError",
        "KeyError",
        "NoneType",
        "Internal Server Error",
    ]:
        if bad in answer:
            status = "FAIL"
            reasons.append(f"Answer contains error marker: '{bad}'")

    # 3. For off-topic questions — must NOT crash (any answer is fine)
    if tc.get("expect_graceful") and not tc.get("expect_no_sql"):
        # Graceful questions: just need a non-empty answer
        pass

    # 4. Off-topic questions — ideally should NOT return SQL data
    if tc.get("expect_no_sql") and sql.strip():
        # Not a hard fail — just a warning, model might still respond with data
        if status == "PASS":
            status = "WARN"
        reasons.append("Off-topic question returned SQL (model did not deflect)")

    # 5. For data questions — SQL must be present (unless graceful)
    if not tc.get("expect_graceful") and not sql.strip():
        status = "FAIL"
        reasons.append("No SQL generated for a data question")

    # 6. Response time checks
    if elapsed > ERROR_THRESHOLD:
        status = "FAIL"
        reasons.append(f"Timeout: {elapsed:.1f}s > {ERROR_THRESHOLD}s limit")
    elif elapsed > SLOW_THRESHOLD:
        if status == "PASS":
            status = "WARN"
        reasons.append(f"Slow response: {elapsed:.1f}s > {SLOW_THRESHOLD}s")

    # 7. Error flag in meta (only hard errors, not "no_data" / graceful)
    meta_error = meta.get("error") if isinstance(meta, dict) else None
    soft_errors = {"no_data", "no_tables", "off_topic", "technical_error"}
    if meta_error and str(meta_error).lower() not in soft_errors:
        status = "FAIL"
        reasons.append(f"Pipeline error in meta: {str(meta_error)[:120]}")

    if not reasons:
        reasons.append("OK")

    return {
        "status": status,
        "reasons": reasons,
        "answer_preview": answer[:120].replace("\n", " ") if answer else "",
        "sql_preview": sql[:100].replace("\n", " ") if sql else "",
        "row_count": len(data_sample) if isinstance(data_sample, list) else 0,
    }


# ─── Single Test Runner ───────────────────────────────────────────────────────
async def run_one(client: httpx.AsyncClient, tc: Dict[str, Any]) -> Dict[str, Any]:
    start = time.time()
    try:
        resp = await client.post(
            f"{API_BASE_URL}/connections/{CONNECTION_ID}/query",
            json={
                "question": tc["question"],
                "user_id": USER_ID,
                "space_id": SPACE_ID,
                "crew_ids": CREW_IDS,
                "thread_id": f"test-{tc['id'].lower()}-{uuid.uuid4().hex[:6]}",
            },
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        elapsed = time.time() - start
        try:
            resp_data = resp.json()
        except Exception:
            resp_data = None

        evaluation = evaluate_result(tc, resp_data, elapsed, resp.status_code, None)
    except Exception as exc:
        elapsed = time.time() - start
        evaluation = evaluate_result(tc, None, elapsed, None, str(exc))

    return {
        **tc,
        "elapsed": round(elapsed, 2),
        **evaluation,
    }


# ─── Sequential Runner ────────────────────────────────────────────────────────
async def run_sequential(cases: List[Dict]) -> List[Dict]:
    results = []
    async with httpx.AsyncClient() as client:
        for i, tc in enumerate(cases):
            r = await run_one(client, tc)
            icon = {"PASS": "✅", "WARN": "⚠️ ", "FAIL": "❌"}.get(r["status"], "?")
            print(f"  {icon} [{r['id']}] {r['elapsed']:5.1f}s  {r['question'][:55]}...")
            results.append(r)
    return results


# ─── Parallel Runner ──────────────────────────────────────────────────────────
async def run_parallel(cases: List[Dict], concurrency: int = 5) -> List[Dict]:
    sem = asyncio.Semaphore(concurrency)
    results_map: Dict[str, Dict] = {}

    async def worker(client, tc):
        async with sem:
            r = await run_one(client, tc)
            icon = {"PASS": "✅", "WARN": "⚠️ ", "FAIL": "❌"}.get(r["status"], "?")
            print(f"  {icon} [{r['id']}] {r['elapsed']:5.1f}s  {r['question'][:55]}...")
            results_map[tc["id"]] = r

    async with httpx.AsyncClient() as client:
        await asyncio.gather(*[worker(client, tc) for tc in cases])

    # Preserve original order
    return [results_map[tc["id"]] for tc in cases]


# ─── Markdown Report Generator ────────────────────────────────────────────────
def build_report(results: List[Dict], total_elapsed: float, parallel: bool) -> str:
    passed = [r for r in results if r["status"] == "PASS"]
    warned = [r for r in results if r["status"] == "WARN"]
    failed = [r for r in results if r["status"] == "FAIL"]

    categories = {}
    for r in results:
        cat = r.get("category", "Unknown")
        categories.setdefault(cat, {"PASS": 0, "WARN": 0, "FAIL": 0})
        categories[cat][r["status"]] += 1

    times = [r["elapsed"] for r in results]
    avg_time = sum(times) / len(times) if times else 0
    pass_rate = len(passed) / len(results) * 100 if results else 0

    lines: List[str] = []

    # ── Header
    lines += [
        "# Sky AI Chat — Test Report",
        "",
        f"> Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"> Mode: {'Parallel (concurrency=5)' if parallel else 'Sequential'}  ",
        f"> Connection: `{CONNECTION_ID}`  ",
        f"> AI Provider: OpenAI (gpt-4o-mini / gpt-4o)  ",
        "",
    ]

    # ── Executive Summary
    lines += [
        "## Executive Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total Cases | {len(results)} |",
        f"| ✅ Passed | {len(passed)} ({pass_rate:.1f}%) |",
        f"| ⚠️  Warnings | {len(warned)} |",
        f"| ❌ Failed | {len(failed)} |",
        f"| Total Time | {total_elapsed:.1f}s |",
        f"| Avg Time / Case | {avg_time:.1f}s |",
        f"| Min Time | {min(times):.1f}s |",
        f"| Max Time | {max(times):.1f}s |",
        "",
    ]

    # ── Results by Category
    lines += [
        "## Results by Category",
        "",
        "| Category | Cases | ✅ Pass | ⚠️  Warn | ❌ Fail |",
        "|----------|-------|--------|---------|--------|",
    ]
    for cat, counts in sorted(categories.items()):
        total = counts["PASS"] + counts["WARN"] + counts["FAIL"]
        lines.append(
            f"| {cat} | {total} | {counts['PASS']} | {counts['WARN']} | {counts['FAIL']} |"
        )
    lines.append("")

    # ── All Results Table
    lines += [
        "## Detailed Results",
        "",
        "| ID | Category | Status | Time | Question | Reason |",
        "|----|----------|--------|------|----------|--------|",
    ]
    status_icons = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}
    for r in results:
        icon = status_icons.get(r["status"], "?")
        reason = "; ".join(r.get("reasons", []))
        q = r["question"][:50].replace("|", "\\|")
        lines.append(
            f"| {r['id']} | {r['category']} | {icon} {r['status']} "
            f"| {r['elapsed']}s | {q}... | {reason} |"
        )
    lines.append("")

    # ── Passed Tests
    if passed:
        lines += [
            "## ✅ Passed Tests",
            "",
            "| ID | Category | Time | Answer Preview |",
            "|----|----------|------|----------------|",
        ]
        for r in passed:
            preview = (r.get("answer_preview") or "")[:80].replace("|", "\\|")
            lines.append(
                f"| {r['id']} | {r['category']} | {r['elapsed']}s | {preview} |"
            )
        lines.append("")

    # ── Warning Tests
    if warned:
        lines += [
            "## ⚠️ Warning Tests",
            "",
            "| ID | Category | Time | Issue | Answer Preview |",
            "|----|----------|------|-------|----------------|",
        ]
        for r in warned:
            reason = "; ".join(r.get("reasons", []))
            preview = (r.get("answer_preview") or "")[:60].replace("|", "\\|")
            lines.append(
                f"| {r['id']} | {r['category']} | {r['elapsed']}s | {reason} | {preview} |"
            )
        lines.append("")

    # ── Failed Tests
    if failed:
        lines += [
            "## ❌ Failed Tests",
            "",
            "| ID | Category | Time | Failure Reason | Question |",
            "|----|----------|------|----------------|----------|",
        ]
        for r in failed:
            reason = "; ".join(r.get("reasons", []))
            q = r["question"][:60].replace("|", "\\|")
            lines.append(
                f"| {r['id']} | {r['category']} | {r['elapsed']}s | {reason} | {q} |"
            )
        lines.append("")

    # ── What Needs to Be Done
    lines += [
        "## Action Items",
        "",
        "### Critical Fixes (Failed Tests)",
    ]
    if not failed:
        lines.append(
            "_No critical failures. All data questions returned valid answers._"
        )
    else:
        # Group failures by reason type
        infra_failures = [
            r for r in failed if "Exception" in " ".join(r.get("reasons", []))
        ]
        sql_failures = [
            r for r in failed if "No SQL generated" in " ".join(r.get("reasons", []))
        ]
        empty_failures = [
            r for r in failed if "empty" in " ".join(r.get("reasons", [])).lower()
        ]
        timeout_failures = [
            r for r in failed if "Timeout" in " ".join(r.get("reasons", []))
        ]
        meta_failures = [
            r
            for r in failed
            if "Pipeline error in meta" in " ".join(r.get("reasons", []))
        ]
        other_failures = [
            r
            for r in failed
            if r
            not in infra_failures
            + sql_failures
            + empty_failures
            + timeout_failures
            + meta_failures
        ]

        if infra_failures:
            lines += [
                "",
                f"#### Infrastructure / Connection Issues ({len(infra_failures)} cases)",
                "- Service not reachable or connection_id invalid.",
                "- **Fix:** Ensure `./start.sh` is running and `CONNECTION_ID` is valid.",
                "- Affected: " + ", ".join(r["id"] for r in infra_failures),
            ]

        if sql_failures:
            lines += [
                "",
                f"#### No SQL Generated ({len(sql_failures)} cases)",
                "- Orchestrator failed to map the question to a table, or Specialist returned empty SQL.",
                "- **Fix:** Review Orchestrator prompts in `core/llm/prompts/orchestrator_prompts.py`.",
                "  Check that the relevant tables are registered in the connection's catalog.",
                "- Affected: " + ", ".join(r["id"] for r in sql_failures),
            ]

        if empty_failures:
            lines += [
                "",
                f"#### Empty Answer ({len(empty_failures)} cases)",
                "- LLM generated SQL and executed it, but the Formatter returned nothing.",
                "- **Fix:** Review `core/llm/formatter.py` and `core/llm/prompts/formatter_prompts.py`.",
                "  Check if the data_sample returned from the query was empty (zero rows).",
                "- Affected: " + ", ".join(r["id"] for r in empty_failures),
            ]

        if timeout_failures:
            lines += [
                "",
                f"#### Timeouts ({len(timeout_failures)} cases)",
                f"- Response time exceeded {ERROR_THRESHOLD}s threshold.",
                "- **Fix:** Profile the pipeline stages. Check if SQL execution is slow (missing indexes).",
                "  Consider enabling `ENABLE_INFERENCE_CACHE=true` for repeated queries.",
                "- Affected: " + ", ".join(r["id"] for r in timeout_failures),
            ]

        if meta_failures:
            lines += [
                "",
                f"#### Pipeline Errors in Meta ({len(meta_failures)} cases)",
                "- LangGraph pipeline returned an error in the `meta.error` field.",
                "- **Fix:** Check the AI service logs: `docker-compose logs -f ai`.",
                "- Affected: " + ", ".join(r["id"] for r in meta_failures),
            ]

        if other_failures:
            lines += [
                "",
                f"#### Other Failures ({len(other_failures)} cases)",
            ]
            for r in other_failures:
                reason = "; ".join(r.get("reasons", []))
                lines.append(f"- **{r['id']}** ({r['category']}): {reason}")

    lines += [
        "",
        "### Warnings to Review",
    ]
    if not warned:
        lines.append("_No warnings._")
    else:
        slow_warns = [
            r for r in warned if "Slow response" in " ".join(r.get("reasons", []))
        ]
        sql_warns = [r for r in warned if "Off-topic" in " ".join(r.get("reasons", []))]

        if slow_warns:
            lines += [
                "",
                f"#### Slow Responses ({len(slow_warns)} cases)",
                f"- Response time exceeded {SLOW_THRESHOLD}s but stayed below {ERROR_THRESHOLD}s.",
                "- **Recommendation:** Enable semantic cache, optimize indexes on data source,",
                "  or switch gpt-4o (Specialist) to gpt-4o-mini for faster iteration.",
                "- Affected: " + ", ".join(r["id"] for r in slow_warns),
            ]

        if sql_warns:
            lines += [
                "",
                f"#### Off-topic Questions Returned SQL ({len(sql_warns)} cases)",
                "- Questions unrelated to data (weather, jokes, etc.) triggered the pipeline.",
                "- **Recommendation:** Add a guardrail intent classifier before the Orchestrator",
                "  to reject non-data questions early and save LLM tokens.",
                "- Affected: " + ", ".join(r["id"] for r in sql_warns),
            ]

    # ── Recommendations
    lines += [
        "",
        "## General Recommendations",
        "",
        "| Priority | Area | Recommendation |",
        "|----------|------|----------------|",
        "| High | Table Coverage | Verify all 10 categories have matching tables in the connection catalog |",
        "| High | Temporal Queries | Ensure date columns are indexed and dialect handles `CURRENT_DATE` correctly |",
        "| Medium | Off-topic Deflection | Add intent guardrail to reject non-business questions before the pipeline |",
        "| Medium | Response Speed | Enable `ENABLE_INFERENCE_CACHE=true` to cache repeated semantically similar queries |",
        "| Medium | Edge Cases | Improve Orchestrator prompts for ambiguous questions (EDG-001 to EDG-006) |",
        "| Low | LLM Judge | Add semantic evaluation layer (GPT-4o-as-judge) to validate answer quality, not just presence |",
        "| Low | Persona Tests | Add 20 role-based tests (admin/cfo/viewer/guest) to validate RBAC on data access |",
        "",
        "---",
        f"_Report generated by `tests/test_100_cases.py` on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_",
    ]

    return "\n".join(lines)


# ─── Main ─────────────────────────────────────────────────────────────────────
async def main(parallel: bool = False):
    print("=" * 70)
    print("  SKY AI — 100 CHAT TEST CASES")
    print("=" * 70)
    print(f"  API:        {API_BASE_URL}")
    print(f"  Connection: {CONNECTION_ID}")
    print(f"  Mode:       {'Parallel (concurrency=5)' if parallel else 'Sequential'}")
    print(f"  Cases:      {len(TEST_CASES)}")
    print("=" * 70)

    # Health check
    async with httpx.AsyncClient() as client:
        try:
            health = await client.get(f"{API_BASE_URL}/health", timeout=5.0)
            if health.status_code != 200:
                print(
                    f"\n❌  Service unhealthy (HTTP {health.status_code}). Start with: cd deploy && ./start.sh\n"
                )
                sys.exit(1)
            print("\n✅  Service is running\n")
        except Exception as exc:
            print(f"\n❌  Cannot reach {API_BASE_URL}: {exc}")
            print("   Start with: cd deploy && ./start.sh\n")
            sys.exit(1)

    print("Running tests...\n")
    t0 = time.time()

    if parallel:
        results = await run_parallel(TEST_CASES)
    else:
        results = await run_sequential(TEST_CASES)

    total_elapsed = time.time() - t0

    # Console summary
    passed = [r for r in results if r["status"] == "PASS"]
    warned = [r for r in results if r["status"] == "WARN"]
    failed = [r for r in results if r["status"] == "FAIL"]
    pass_rate = len(passed) / len(results) * 100

    print()
    print("=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    print(f"  Total:    {len(results)}")
    print(f"  ✅ Pass:  {len(passed)} ({pass_rate:.1f}%)")
    print(f"  ⚠️  Warn:  {len(warned)}")
    print(f"  ❌ Fail:  {len(failed)}")
    print(f"  Time:     {total_elapsed:.1f}s")
    print("=" * 70)

    # Generate and save report
    report_md = build_report(results, total_elapsed, parallel)
    REPORT_PATH.write_text(report_md, encoding="utf-8")
    print(f"\n📄  Report saved to: {REPORT_PATH}\n")

    # Also save raw JSON for debugging
    json_path = REPORT_PATH.with_suffix(".json")
    json_path.write_text(
        json.dumps(results, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"📊  Raw JSON saved to: {json_path}\n")

    return 0 if not failed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sky AI 100 test cases")
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Run tests in parallel (concurrency=5, faster)",
    )
    args = parser.parse_args()

    exit_code = asyncio.run(main(parallel=args.parallel))
    sys.exit(exit_code)
