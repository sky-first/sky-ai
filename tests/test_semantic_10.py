#!/usr/bin/env python3
"""
Semantic Metadata — 10 Targeted Tests
---------------------------------------
Tests 10 questions that previously returned "No SQL generated" due to the
Orchestrator failing to map business terms (revenue, profit, margin, etc.)
to actual column names.

Run AFTER update_semantic_metadata.py:
    python tests/update_semantic_metadata.py
    python tests/test_semantic_10.py

Each test compares BEFORE (generic metadata) vs AFTER (semantic metadata) by
checking whether the pipeline now generates SQL and returns a data answer.
"""

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

# ─── Config ──────────────────────────────────────────────────────────────────

BASE_URL = "http://localhost:8001"
CONNECTION_ID = "aaaa0001-0000-4000-a000-000000000001"
SPACE_ID = "d21795e0-430c-4f72-99ae-4c61512e17d1"
USER_ID = "32a2a83c-5dc9-4a82-b228-6fa976c173b1"
CREW_IDS: List[str] = []
TIMEOUT = 120.0

# ─── Test Cases ───────────────────────────────────────────────────────────────
# These 10 were chosen because they all failed with "No SQL generated" in the
# 100-case run despite being valid questions about data that exists in the DB.
# They cover the most common semantic gaps: revenue, profit, margin, avg order value.

TEST_CASES = [
    {
        "id": "SEM-001",
        "category": "Revenue — Basic",
        "question": "What is the total revenue?",
        "expected_sql_keywords": ["total_amount", "SUM"],
        "notes": "BAS-004 in the 100-case run. 'revenue' must map to total_amount.",
    },
    {
        "id": "SEM-002",
        "category": "Revenue — Basic",
        "question": "What is the total sales amount?",
        "expected_sql_keywords": ["total_amount", "SUM"],
        "notes": "BAS-008. 'sales amount' must map to total_amount.",
    },
    {
        "id": "SEM-003",
        "category": "Aggregation",
        "question": "What is the average order value?",
        "expected_sql_keywords": ["total_amount", "AVG"],
        "notes": "AGG-001. AOV = AVG(total_amount).",
    },
    {
        "id": "SEM-004",
        "category": "Aggregation",
        "question": "What is the average revenue per customer?",
        "expected_sql_keywords": ["total_amount"],
        "notes": "AGG-002. Requires join orders + group by customer.",
    },
    {
        "id": "SEM-005",
        "category": "Rankings",
        "question": "Who are the top 5 customers by total revenue?",
        "expected_sql_keywords": ["total_amount", "customer"],
        "notes": "RNK-002. Join orders → customers, rank by SUM(total_amount).",
    },
    {
        "id": "SEM-006",
        "category": "Rankings",
        "question": "Who are the top 5 sales representatives by revenue?",
        "expected_sql_keywords": ["total_amount", "sales_rep"],
        "notes": "RNK-006. Join orders → sales_reps, rank by SUM(total_amount).",
    },
    {
        "id": "SEM-007",
        "category": "Financial",
        "question": "What is the profit margin per product?",
        "expected_sql_keywords": ["price", "cost"],
        "notes": "PRD-002 / FIN. profit_margin = (price - cost) / price.",
    },
    {
        "id": "SEM-008",
        "category": "Financial",
        "question": "What is the net revenue after discounts?",
        "expected_sql_keywords": ["total_amount", "discount_amount"],
        "notes": "FIN-002. net = SUM(total_amount - discount_amount).",
    },
    {
        "id": "SEM-009",
        "category": "Segmentation",
        "question": "What is the total revenue grouped by product category?",
        "expected_sql_keywords": ["category", "subtotal"],
        "notes": "AGG-008 / SEG-004. Join order_items → products, GROUP BY category.",
    },
    {
        "id": "SEM-010",
        "category": "Financial",
        "question": "What is the total discount amount given across all orders?",
        "expected_sql_keywords": ["discount_amount", "SUM"],
        "notes": "FIN-005. SUM(discount_amount) — discount must map to discount_amount.",
    },
]

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _check_sql_keywords(sql: str, keywords: List[str]) -> Dict[str, bool]:
    """Check which expected keywords appear in the generated SQL (case-insensitive)."""
    sql_upper = sql.upper()
    return {kw: kw.upper() in sql_upper for kw in keywords}


def _evaluate(tc: Dict, resp_data: Dict, elapsed: float) -> Dict[str, Any]:
    """Return a result record for a single test case."""
    meta = resp_data.get("meta", {}) or {}

    # Determine outcome
    error = meta.get("error") or resp_data.get("error", "")
    sql = meta.get("sql") or resp_data.get("sql", "")
    answer = resp_data.get("answer", "")
    data_rows = meta.get("data") or resp_data.get("data", [])
    result_type = meta.get("result_type", "")

    # Fail conditions
    has_sql = bool(sql and sql.strip())
    has_answer = bool(answer and answer.strip())
    has_data = len(data_rows) > 0 if isinstance(data_rows, list) else False
    is_error = bool(error)
    is_no_data = result_type in {"no_data", "no_tables", "technical_error"}

    kw_check: Dict[str, bool] = {}
    if has_sql and tc.get("expected_sql_keywords"):
        kw_check = _check_sql_keywords(sql, tc["expected_sql_keywords"])

    if not has_sql and not is_no_data:
        status = "FAIL"
        reason = "No SQL generated — Orchestrator did not select a table"
    elif is_error:
        status = "FAIL"
        reason = f"Pipeline error: {error[:150]}"
    elif not has_answer:
        status = "FAIL"
        reason = "No answer text returned"
    elif kw_check and not all(kw_check.values()):
        missing = [k for k, v in kw_check.items() if not v]
        status = "WARN"
        reason = f"SQL generated but missing expected keywords: {missing}"
    else:
        status = "PASS"
        reason = "OK"

    return {
        "id": tc["id"],
        "category": tc["category"],
        "question": tc["question"],
        "status": status,
        "reason": reason,
        "elapsed": round(elapsed, 2),
        "sql": sql[:300] if sql else "",
        "answer": answer[:200] if answer else "",
        "kw_check": kw_check,
        "notes": tc.get("notes", ""),
    }


async def run_query(client: httpx.AsyncClient, tc: Dict) -> Dict[str, Any]:
    thread_id = f"sem-{tc['id'].lower()}-{uuid.uuid4().hex[:6]}"
    payload = {
        "question": tc["question"],
        "space_id": SPACE_ID,
        "user_id": USER_ID,
        "crew_ids": CREW_IDS,
        "thread_id": thread_id,
    }
    start = time.monotonic()
    try:
        resp = await client.post(
            f"{BASE_URL}/connections/{CONNECTION_ID}/query",
            json=payload,
            timeout=TIMEOUT,
        )
        elapsed = time.monotonic() - start
        if resp.status_code != 200:
            return {
                "id": tc["id"],
                "category": tc["category"],
                "question": tc["question"],
                "status": "FAIL",
                "reason": f"HTTP {resp.status_code}: {resp.text[:200]}",
                "elapsed": round(elapsed, 2),
                "sql": "",
                "answer": "",
                "kw_check": {},
                "notes": tc.get("notes", ""),
            }
        return _evaluate(tc, resp.json(), elapsed)
    except httpx.TimeoutException:
        elapsed = time.monotonic() - start
        return {
            "id": tc["id"],
            "category": tc["category"],
            "question": tc["question"],
            "status": "FAIL",
            "reason": f"Timeout after {elapsed:.0f}s",
            "elapsed": round(elapsed, 2),
            "sql": "",
            "answer": "",
            "kw_check": {},
            "notes": tc.get("notes", ""),
        }
    except Exception as exc:
        elapsed = time.monotonic() - start
        return {
            "id": tc["id"],
            "category": tc["category"],
            "question": tc["question"],
            "status": "FAIL",
            "reason": f"Exception: {str(exc)[:200]}",
            "elapsed": round(elapsed, 2),
            "sql": "",
            "answer": "",
            "kw_check": {},
            "notes": tc.get("notes", ""),
        }


# ─── Report ───────────────────────────────────────────────────────────────────

STATUS_ICON = {"PASS": "✅", "WARN": "⚠️ ", "FAIL": "❌"}


def _print_live(result: Dict):
    icon = STATUS_ICON.get(result["status"], "?")
    kw = result.get("kw_check", {})
    kw_str = " | ".join(f"{k}={'✓' if v else '✗'}" for k, v in kw.items())
    print(
        f"  {icon} [{result['id']}] {result['status']:4s}  {result['elapsed']:5.1f}s  "
        f"{result['question'][:55]:<55}"
        + (f"\n         KW check: {kw_str}" if kw_str else "")
        + (
            f"\n         Reason:   {result['reason']}"
            if result["status"] != "PASS"
            else ""
        )
    )
    if result["sql"]:
        print(f"         SQL:      {result['sql'][:120]}")


def _write_report(results: List[Dict], total_elapsed: float):
    passed = [r for r in results if r["status"] == "PASS"]
    warned = [r for r in results if r["status"] == "WARN"]
    failed = [r for r in results if r["status"] == "FAIL"]
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "# Semantic Metadata — 10 Targeted Tests",
        "",
        f"> Generated: {now_str}",
        f"> Connection: `{CONNECTION_ID}`",
        "",
        "## Goal",
        "Validate whether **semantic column descriptions** in `TableMetadata` allow",
        "the Orchestrator to correctly resolve business terms (revenue, profit, margin,",
        "discount, AOV) to actual database column names — without changing the LLM prompts.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total Cases | {len(results)} |",
        f"| ✅ Passed | {len(passed)} ({100*len(passed)//len(results)}%) |",
        f"| ⚠️  Warnings | {len(warned)} |",
        f"| ❌ Failed | {len(failed)} |",
        f"| Total Time | {total_elapsed:.1f}s |",
        f"| Avg Time / Case | {total_elapsed/len(results):.1f}s |",
        "",
        "## Results",
        "",
        "| ID | Category | Status | Time | Question | SQL Keywords Found | Reason |",
        "|----|----------|--------|------|----------|--------------------|--------|",
    ]
    for r in results:
        kw_str = (
            ", ".join(
                f"{'✓' if v else '✗'}{k}" for k, v in r.get("kw_check", {}).items()
            )
            or "—"
        )
        lines.append(
            f"| {r['id']} | {r['category']} | "
            f"{STATUS_ICON.get(r['status'], r['status'])} {r['status']} | "
            f"{r['elapsed']}s | {r['question'][:50]}... | {kw_str} | {r['reason'][:80]} |"
        )

    # ── Passed detail
    if passed:
        lines += ["", "## ✅ Passed", ""]
        for r in passed:
            lines += [
                f"### {r['id']} — {r['question']}",
                (
                    f"- **SQL**: `{r['sql'][:200]}`"
                    if r["sql"]
                    else "- _No SQL (soft pass)_"
                ),
                f"- **Answer**: {r['answer'][:150]}",
                "",
            ]

    # ── Failed detail
    if failed:
        lines += ["", "## ❌ Failed", ""]
        for r in failed:
            lines += [
                f"### {r['id']} — {r['question']}",
                f"- **Reason**: {r['reason']}",
                f"- **Notes**: {r['notes']}",
                f"- **SQL**: `{r['sql']}`" if r["sql"] else "- _No SQL generated_",
                "",
            ]

    # ── Warning detail
    if warned:
        lines += ["", "## ⚠️  Warnings", ""]
        for r in warned:
            kw_detail = " | ".join(
                f"{k}={'✓' if v else '✗'}" for k, v in r.get("kw_check", {}).items()
            )
            lines += [
                f"### {r['id']} — {r['question']}",
                f"- **Reason**: {r['reason']}",
                f"- **KW Check**: {kw_detail}",
                f"- **SQL**: `{r['sql'][:200]}`",
                f"- **Answer**: {r['answer'][:150]}",
                "",
            ]

    # ── Diagnosis
    lines += [
        "## Diagnosis",
        "",
        "### If tests still fail after semantic metadata update:",
        "",
        "| Failure Pattern | Root Cause | Fix |",
        "|-----------------|------------|-----|",
        "| No SQL generated (same as before) | RAG not returning the right table — embeddings may not be recomputed | Trigger `/connections/{id}/refresh` to re-embed the new descriptions |",
        "| SQL generated but wrong column | Orchestrator ignores metadata, uses own knowledge | Enrich Orchestrator system prompt with explicit synonym mapping |",
        "| SQL generated but query fails | Specialist generates correct logic but wrong syntax | Check dialect-specific date/aggregation functions |",
        "| SQL uses wrong table | Semantic similarity too generic | Add more specific synonyms to the failing table description |",
        "",
        "### Next steps based on results:",
        "- If **≥ 8 pass**: semantic metadata alone fixes the problem → enrich all production connections",
        "- If **4–7 pass**: partial fix → also update Orchestrator prompt with synonym examples",
        "- If **< 4 pass**: metadata not reaching the LLM → investigate RAG retrieval (`/catalog` endpoint or vector_store.py)",
        "",
        "---",
        f"_Generated by `tests/test_semantic_10.py` on {now_str}_",
    ]

    md_path = Path(__file__).parent / "test_semantic_report.md"
    json_path = Path(__file__).parent / "test_semantic_report.json"

    md_path.write_text("\n".join(lines), encoding="utf-8")
    json_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\n📄  Report saved to: {md_path}")
    print(f"📊  Raw JSON saved to: {json_path}")


# ─── Main ─────────────────────────────────────────────────────────────────────


async def main():
    print("=" * 70)
    print("  SEMANTIC METADATA — 10 TARGETED TESTS")
    print("=" * 70)
    print(f"  Connection : {CONNECTION_ID}")
    print(f"  API        : {BASE_URL}")
    print(f"  Cases      : {len(TEST_CASES)}")
    print("=" * 70)
    print()

    results: List[Dict] = []
    total_start = time.monotonic()

    async with httpx.AsyncClient() as client:
        # Health check
        try:
            hc = await client.get(f"{BASE_URL}/health", timeout=5.0)
            print(f"  Health: {hc.status_code} {hc.text[:80]}\n")
        except Exception as e:
            print(f"  ⚠️  Could not reach {BASE_URL}/health: {e}")
            print("  Make sure the AI service is running: python run_api.py\n")

        for tc in TEST_CASES:
            print(f"\n[{tc['id']}] {tc['question']}")
            print(f"  Category : {tc['category']}")
            print(f"  Notes    : {tc['notes']}")
            result = await run_query(client, tc)
            results.append(result)
            _print_live(result)

    total_elapsed = time.monotonic() - total_start

    # ── Summary
    passed = sum(1 for r in results if r["status"] == "PASS")
    warned = sum(1 for r in results if r["status"] == "WARN")
    failed = sum(1 for r in results if r["status"] == "FAIL")

    print("\n" + "=" * 70)
    print(
        f"  RESULTS: {passed}/{len(results)} passed  |  {warned} warnings  |  {failed} failed"
    )
    print(
        f"  Time   : {total_elapsed:.1f}s total  ({total_elapsed/len(results):.1f}s avg)"
    )
    print("=" * 70)

    if passed == len(results):
        print("\n  🎉 All tests passed — semantic metadata is working correctly!")
    elif passed >= 8:
        print(f"\n  ✅ {passed}/10 passed — semantic metadata is mostly working.")
        print("     Investigate the remaining failures for edge cases.")
    elif passed >= 5:
        print(f"\n  ⚠️  {passed}/10 passed — partial improvement.")
        print(
            "     Consider also updating the Orchestrator system prompt with synonyms."
        )
    else:
        print(
            f"\n  ❌ Only {passed}/10 passed — semantic metadata alone is not enough."
        )
        print("     Check if embeddings were re-computed after metadata update.")
        print("     Run: POST /connections/{id}/refresh to trigger re-embedding.")

    _write_report(results, total_elapsed)


if __name__ == "__main__":
    asyncio.run(main())
