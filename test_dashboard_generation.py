#!/usr/bin/env python3
"""
Test script for dashboard generation validation.
Tests all 15 business questions and validates the fixes.
"""
import requests
import json
import time
from typing import Dict, List, Any

# Configuration
BASE_URL = "http://localhost:8000"
CONNECTION_ID = "8bb5db88-93cf-4982-97c0-d979c157c52d"
SPACE_ID = "bbd2cef9-8d77-427f-a351-0b32a5c20abe"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZTFhODY0MC1mODY4LTRkMmEtOWRlYS05YWE0ZTIxYjVkZmMiLCJlbWFpbCI6InRlc3RAZXhhbXBsZS5jb20iLCJyb2xlIjoiYWRtaW4iLCJleHAiOjE3Njg0Nzk3NzcsInR5cGUiOiJhY2Nlc3MifQ.nQcdpbieKLSO99oduZkYesXw8jO97bWHbAXas4mIcMc"

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

# Test questions
TEST_QUESTIONS = [
    # Revenue (4)
    "What is the monthly revenue performance?",
    "Which customers generate the most revenue?",
    "How is revenue distributed by value category?",
    "How does revenue evolve over time?",
    
    # Invoices (1)
    "What is the invoice status analysis?",
    
    # Payments (5)
    "What is the monthly payment performance?",
    "Which payment method is most commonly used?",
    "On which days of the week are payments most frequent?",
    "What is the payment status analysis?",
    "Which customers make the most payments?",
    
    # Refunds (2)
    "What is the monthly refund performance?",
    "What are the main reasons for refunds?",
    
    # Credits (3)
    "What is the monthly credit performance?",
    "What are the main reasons for credits?",
    "What is the consolidated impact of refunds and credits?",
]

def ask_question(question: str) -> Dict[str, Any]:
    """Ask a question and get AI response."""
    print(f"\n📝 Asking: {question}")
    
    response = requests.post(
        f"{BASE_URL}/connections/{CONNECTION_ID}/query",
        headers=HEADERS,
        json={
            "question": question,
            "space_id": SPACE_ID,
            "language": "en"
        }
    )
    
    if response.status_code != 200:
        print(f"❌ Error: {response.status_code}")
        return None
    
    data = response.json()
    print(f"✅ Response received")
    return data

def create_dashboard(question: str, initial_response: str) -> Dict[str, Any]:
    """Create dashboard from question."""
    print(f"🎨 Creating dashboard...")
    
    response = requests.post(
        f"{BASE_URL}/connections/{CONNECTION_ID}/dashboards/plan",
        headers=HEADERS,
        json={
            "goal": f"Dashboard for: {question}",
            "max_widgets": 8,
            "language": "en",
            "original_question": question,
            "initial_ai_response": initial_response,
            "space_id": SPACE_ID
        }
    )
    
    if response.status_code != 200:
        print(f"❌ Error: {response.status_code}")
        return None
    
    data = response.json()
    print(f"✅ Dashboard created: {data.get('dashboard_name')}")
    return data

def validate_dashboard(question: str, dashboard: Dict[str, Any]) -> Dict[str, Any]:
    """Validate dashboard against criteria."""
    widgets = dashboard.get("widgets", [])
    
    # Extract key terms from question
    question_lower = question.lower()
    key_terms = []
    if "revenue" in question_lower:
        key_terms = ["revenue", "sales", "income"]
    elif "payment" in question_lower:
        key_terms = ["payment", "paid"]
    elif "refund" in question_lower:
        key_terms = ["refund"]
    elif "credit" in question_lower:
        key_terms = ["credit", "memo"]
    elif "invoice" in question_lower:
        key_terms = ["invoice"]
    elif "customer" in question_lower:
        key_terms = ["customer"]
    
    # Validation checks
    technical_questions = []
    wrong_viz_types = []
    empty_widgets = []
    unrelated_widgets = []
    
    for widget in widgets:
        widget_question = widget.get("question", "").lower()
        widget_title = widget.get("title", "").lower()
        
        # Check for technical questions
        if any(phrase in widget_question or phrase in widget_title for phrase in [
            "total rows in",
            "how many rows are in",
            "count of records",
            "rows in the table"
        ]):
            technical_questions.append({
                "title": widget.get("title"),
                "question": widget.get("question")
            })
        
        # Check viz types
        viz = widget.get("viz", {})
        viz_type = viz.get("type")
        
        # Check if scatter is used for categorical data
        if viz_type == "scatter":
            mapping = viz.get("mapping", {})
            x_col = mapping.get("x", "").lower()
            # Common categorical column patterns
            if any(term in x_col for term in ["reason", "status", "method", "category", "type", "day"]):
                wrong_viz_types.append({
                    "title": widget.get("title"),
                    "viz_type": viz_type,
                    "x_column": x_col
                })
        
        # Check relevance to question
        if key_terms:
            is_related = any(term in widget_question or term in widget_title for term in key_terms)
            if not is_related and widget.get("type") != "text":
                unrelated_widgets.append({
                    "title": widget.get("title"),
                    "question": widget.get("question")
                })
    
    # Calculate metrics
    total_widgets = len(widgets)
    related_widgets = total_widgets - len(unrelated_widgets)
    relevance_pct = (related_widgets / total_widgets * 100) if total_widgets > 0 else 0
    
    return {
        "question": question,
        "dashboard_name": dashboard.get("dashboard_name"),
        "total_widgets": total_widgets,
        "related_widgets": related_widgets,
        "relevance_pct": relevance_pct,
        "technical_questions": technical_questions,
        "wrong_viz_types": wrong_viz_types,
        "unrelated_widgets": unrelated_widgets,
        "passed": (
            len(technical_questions) == 0 and
            len(wrong_viz_types) == 0 and
            relevance_pct >= 75
        )
    }

def run_tests():
    """Run all tests."""
    print("=" * 80)
    print("🧪 DASHBOARD GENERATION TEST SUITE")
    print("=" * 80)
    print(f"\nTesting {len(TEST_QUESTIONS)} questions...")
    
    results = []
    
    for i, question in enumerate(TEST_QUESTIONS, 1):
        print(f"\n{'=' * 80}")
        print(f"Test {i}/{len(TEST_QUESTIONS)}")
        print(f"{'=' * 80}")
        
        # Step 1: Ask question
        response = ask_question(question)
        if not response:
            continue
        
        time.sleep(1)  # Rate limiting
        
        # Step 2: Create dashboard
        dashboard = create_dashboard(question, response.get("answer", ""))
        if not dashboard:
            continue
        
        time.sleep(1)  # Rate limiting
        
        # Step 3: Validate
        validation = validate_dashboard(question, dashboard)
        results.append(validation)
        
        # Print summary
        print(f"\n📊 Validation Results:")
        print(f"  Dashboard: {validation['dashboard_name']}")
        print(f"  Widgets: {validation['total_widgets']}")
        print(f"  Related: {validation['related_widgets']} ({validation['relevance_pct']:.1f}%)")
        print(f"  Technical Questions: {len(validation['technical_questions'])}")
        print(f"  Wrong Viz Types: {len(validation['wrong_viz_types'])}")
        print(f"  Unrelated Widgets: {len(validation['unrelated_widgets'])}")
        print(f"  Status: {'✅ PASSED' if validation['passed'] else '❌ FAILED'}")
    
    # Generate report
    print(f"\n{'=' * 80}")
    print("📊 FINAL REPORT")
    print(f"{'=' * 80}")
    
    passed = sum(1 for r in results if r['passed'])
    failed = len(results) - passed
    
    print(f"\nTotal Tests: {len(results)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Success Rate: {passed/len(results)*100:.1f}%")
    
    # Detailed issues
    print(f"\n{'=' * 80}")
    print("🔍 ISSUES FOUND")
    print(f"{'=' * 80}")
    
    total_technical = sum(len(r['technical_questions']) for r in results)
    total_wrong_viz = sum(len(r['wrong_viz_types']) for r in results)
    total_unrelated = sum(len(r['unrelated_widgets']) for r in results)
    
    print(f"\nTechnical Questions: {total_technical}")
    print(f"Wrong Viz Types: {total_wrong_viz}")
    print(f"Unrelated Widgets: {total_unrelated}")
    
    if total_technical > 0:
        print(f"\n❌ Technical Questions Found:")
        for r in results:
            for tq in r['technical_questions']:
                print(f"  - {tq['title']}: {tq['question']}")
    
    if total_wrong_viz > 0:
        print(f"\n❌ Wrong Viz Types Found:")
        for r in results:
            for wv in r['wrong_viz_types']:
                print(f"  - {wv['title']}: {wv['viz_type']} for {wv['x_column']}")
    
    # Save detailed report
    with open("/tmp/dashboard_test_report.json", "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\n📄 Detailed report saved to: /tmp/dashboard_test_report.json")
    
    return results

if __name__ == "__main__":
    run_tests()
