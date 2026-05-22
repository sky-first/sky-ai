# core/suggestions/seeds.py

"""
Static seeds for the Suggestion Engine.
These simulate "historical questions" that have been successful.
In the future, this will be replaced/augmented by real data from query_audit_log.
"""

from typing import Dict, List

# Format: Table -> Role -> List of Questions
# If role is generic, use "default"
SUGGESTION_SEEDS: Dict[str, Dict[str, List[str]]] = {
    "invoices": {
        "admin": [
            "Show total revenue by month",
            "Top 10 customers by revenue",
            "List overdue invoices > $1000",
            "Revenue growth vs last month",
        ],
        "commander": [
            "Team sales performance this quarter",
            "Invoices pending approval",
            "Average payment time per customer",
        ],
        "navigator": [
            "List unpaid invoices",
            "Find invoice by number",
            "Show invoices created today",
            "Check payment status",
        ],
        "default": [
            "Count total invoices",
            "Show recent invoices",
            "Summarize invoice status",
        ],
    },
    "payments": {
        "admin": [
            "Total cash collected this month",
            "Payment method distribution",
            "Cash flow trend last 6 months",
        ],
        "navigator": [
            "Check if payment was received",
            "List failed payments",
            "Show recent payments",
        ],
        "default": ["Show recent payments", "Total payments by status"],
    },
    "customers": {
        "admin": [
            "Customer churn rate",
            "Top spending customers",
            "New customers per month",
        ],
        "default": [
            "Find customer by email",
            "List active customers",
            "Count total customers",
        ],
    },
    "orders": {
        "admin": [
            "Total bookings vs revenue",
            "Order volume trend",
            "Average order value",
        ],
        "navigator": ["List open orders", "Check order status", "Find recent orders"],
        "default": ["Show recent orders", "Count orders by status"],
    },
}

# Fallback generic templates if table is not in seeds
GENERIC_TEMPLATES = [
    "Show recent records in {table}",
    "Count {table} by status",
    "Show top 5 {table}",
    "Summarize {table} data",
]
