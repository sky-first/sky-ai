#!/usr/bin/env python3
"""
Semantic Metadata Enrichment Script
-------------------------------------
Updates TableMetadata descriptions with rich semantic mappings so the
Orchestrator can correctly resolve business terms (revenue, profit, sales,
margin, etc.) to the actual column names.

Run AFTER setup_test_connection.py:
    python tests/update_semantic_metadata.py

This does NOT recreate tables or reseed data — it only replaces the
table_metadata rows for the test connection.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_saas_db"

CONNECTION_ID = "aaaa0001-0000-4000-a000-000000000001"
SPACE_ID = "d21795e0-430c-4f72-99ae-4c61512e17d1"

# ─── Semantic Table Descriptions ─────────────────────────────────────────────
# These are intentionally verbose: they list ALL business synonyms so the RAG
# embedding search returns the right table regardless of how the user phrases
# the question.

SEMANTIC_TABLE_DESCRIPTIONS = {
    "sky_test_orders": (
        "Sales orders table. Use this table to answer questions about: "
        "revenue, total revenue, gross revenue, net revenue, sales, total sales, "
        "sales amount, income, earnings, turnover, order value, transaction value, "
        "average order value (AOV), discounts, discount amount, refunds, "
        "cancellations, order status, sales by channel, sales by region, "
        "sales by payment method, monthly sales, quarterly revenue, "
        "year-over-year revenue, revenue trend, financial performance, "
        "sales performance, sales growth. "
        "Key columns: total_amount = revenue per order (SUM = total revenue); "
        "discount_amount = discount given; status = completed/pending/cancelled/refunded; "
        "channel = online/in-store/mobile/phone; region = North/South/East/West/Central."
    ),
    "sky_test_order_items": (
        "Order line items table. Use this table to answer questions about: "
        "products sold, units sold, quantity sold, items per order, "
        "product revenue, revenue by product, revenue by category (join with sky_test_products), "
        "average items per order, order composition, product mix, "
        "best-selling products by quantity, product sales volume. "
        "Key columns: quantity = units sold; unit_price = price at time of sale; "
        "subtotal = quantity * unit_price (line-item revenue). "
        "JOIN with sky_test_products on product_id to get category and margin."
    ),
    "sky_test_products": (
        "Product catalog table. Use this table to answer questions about: "
        "profit margin, gross margin, profit per product, profitability, "
        "cost of goods sold (COGS), product cost, selling price, price list, "
        "stock level, inventory, out-of-stock products, low stock, "
        "product rating, customer rating, product reviews, best-rated products, "
        "product categories, category breakdown, active vs inactive products. "
        "Key columns: price = selling price; cost = COGS; "
        "profit_margin = (price - cost) / price; "
        "profit = price - cost (absolute gross profit per unit); "
        "stock = inventory count (0 means out of stock); rating = 1-5 stars."
    ),
    "sky_test_customers": (
        "Customers table. Use this table to answer questions about: "
        "customer count, number of customers, active customers, inactive customers, "
        "customer acquisition, new customers, customer growth, "
        "customer segments (enterprise, SMB, startup, consumer), "
        "customers by country, customer geography, customer distribution, "
        "customer lifetime value (CLV/LTV — join with sky_test_orders), "
        "top customers by revenue (join with sky_test_orders on customer_id), "
        "loyal customers, repeat customers, churned customers (no recent orders), "
        "customers who never ordered, customers with most orders. "
        "Key columns: segment = enterprise/smb/startup/consumer; "
        "is_active = whether customer is active; created_at = signup date; "
        "last_order_at = most recent order date (NULL = never ordered)."
    ),
    "sky_test_sales_reps": (
        "Sales representatives table. Use this table to answer questions about: "
        "sales rep performance, revenue by sales rep, top sales reps, "
        "best performing sales rep, sales team, salespeople, "
        "revenue per rep (join with sky_test_orders on sales_rep_id), "
        "orders per rep, sales rep region, regional sales performance. "
        "Key columns: region = geographic region the rep covers; "
        "is_active = whether rep is active; hire_date = when hired."
    ),
}

# ─── Semantic Column Descriptions ─────────────────────────────────────────────
# Include synonyms explicitly so embedding similarity search works.

SEMANTIC_COLUMN_DESCRIPTIONS = {
    "sky_test_orders": {
        "id": "Unique order identifier (primary key)",
        "customer_id": "Foreign key → sky_test_customers.id. Join to get customer name, segment, country.",
        "sales_rep_id": "Foreign key → sky_test_sales_reps.id. Join to get rep name and region.",
        "status": "Order lifecycle status: 'completed' (successful sale), 'pending' (not yet fulfilled), 'cancelled' (cancelled before completion), 'refunded' (returned after completion). Filter by status='completed' for confirmed revenue.",
        "channel": "Sales channel through which the order was placed: 'online', 'in-store', 'mobile', 'phone'.",
        "total_amount": "REVENUE per order — the gross sales value in USD. Use SUM(total_amount) for total revenue / total sales / total income. Use AVG(total_amount) for average order value (AOV). This is the PRIMARY metric for all revenue and sales questions.",
        "discount_amount": "Discount applied to this order in USD. Subtract from total_amount to get net revenue: total_amount - discount_amount. Use SUM(discount_amount) for total discounts given.",
        "payment_method": "Payment method: 'credit_card', 'debit_card', 'paypal', 'bank_transfer', 'pix'. Use for payment mix analysis.",
        "region": "Geographic region of the sale: 'North', 'South', 'East', 'West', 'Central'. Use for regional revenue breakdown.",
        "created_at": "Timestamp when the order was placed. Use for time-series analysis: monthly revenue, quarterly sales, year-over-year comparison, sales trends.",
        "updated_at": "Timestamp of last status change on the order.",
    },
    "sky_test_order_items": {
        "id": "Unique line item identifier (primary key)",
        "order_id": "Foreign key → sky_test_orders.id. Join to filter by order status or date range.",
        "product_id": "Foreign key → sky_test_products.id. Join to get product name, category, margin.",
        "quantity": "Number of units sold in this line item. Use SUM(quantity) for total units sold / total products sold.",
        "unit_price": "Price per unit at the time of sale in USD.",
        "subtotal": "Line item revenue = quantity * unit_price. Use SUM(subtotal) for product-level revenue or category revenue.",
        "created_at": "When the item was recorded.",
    },
    "sky_test_products": {
        "id": "Unique product identifier (primary key)",
        "name": "Product name (e.g. 'Laptop Pro 15', 'Running Shoes'). Use in GROUP BY for per-product analysis.",
        "category": "Product category: 'Electronics', 'Clothing', 'Food', 'Books', 'Sports', 'Home', 'Beauty', 'Toys'. Use GROUP BY category for category-level revenue or margin.",
        "price": "Current selling price in USD. Used to calculate revenue potential and profit margin.",
        "cost": "Cost of goods sold (COGS) per unit in USD. profit_per_unit = price - cost. profit_margin_pct = (price - cost) / price * 100.",
        "stock": "Current inventory count. stock = 0 means out of stock. Use WHERE stock = 0 for out-of-stock products. Use WHERE stock < 10 for low stock.",
        "is_active": "TRUE = product available for sale. FALSE = discontinued. Filter WHERE is_active = TRUE for active catalog.",
        "rating": "Average customer rating on a 1.0–5.0 scale. Use ORDER BY rating DESC for best-rated / top-reviewed products.",
        "created_at": "When the product was added to the catalog.",
    },
    "sky_test_customers": {
        "id": "Unique customer identifier (primary key)",
        "name": "Customer full name. Use in results to show customer names.",
        "email": "Customer email address.",
        "country": "Country code: 'US', 'BR', 'UK', 'DE', 'FR', 'CA', 'AU', 'MX'. Use GROUP BY country for geographic distribution.",
        "segment": "Business segment: 'enterprise' (large companies), 'smb' (small/medium businesses), 'startup' (early-stage), 'consumer' (individual). Use GROUP BY segment for segment analysis.",
        "is_active": "TRUE = active customer. FALSE = churned/inactive. Filter WHERE is_active = TRUE for active customer count.",
        "created_at": "Customer signup / registration date. Use for new customer acquisition analysis and cohort analysis.",
        "last_order_at": "Date of the customer's most recent order. NULL means customer has never ordered. Use WHERE last_order_at < NOW() - INTERVAL '90 days' for inactive / churned customers.",
    },
    "sky_test_sales_reps": {
        "id": "Unique sales rep identifier (primary key)",
        "name": "Sales representative full name.",
        "region": "Geographic region this rep is responsible for: 'North', 'South', 'East', 'West', 'Central'.",
        "hire_date": "Date the rep was hired. Use for tenure analysis.",
        "is_active": "TRUE = currently active rep. FALSE = left the company.",
    },
}

# Column types (unchanged from original)
TABLE_COLUMNS = {
    "sky_test_customers": [
        ("id", "uuid"),
        ("name", "varchar"),
        ("email", "varchar"),
        ("country", "varchar"),
        ("segment", "varchar"),
        ("is_active", "boolean"),
        ("created_at", "timestamp"),
        ("last_order_at", "timestamp"),
    ],
    "sky_test_products": [
        ("id", "uuid"),
        ("name", "varchar"),
        ("category", "varchar"),
        ("price", "numeric"),
        ("cost", "numeric"),
        ("stock", "integer"),
        ("is_active", "boolean"),
        ("rating", "numeric"),
        ("created_at", "timestamp"),
    ],
    "sky_test_sales_reps": [
        ("id", "uuid"),
        ("name", "varchar"),
        ("region", "varchar"),
        ("hire_date", "timestamp"),
        ("is_active", "boolean"),
    ],
    "sky_test_orders": [
        ("id", "uuid"),
        ("customer_id", "uuid"),
        ("sales_rep_id", "uuid"),
        ("status", "varchar"),
        ("channel", "varchar"),
        ("total_amount", "numeric"),
        ("discount_amount", "numeric"),
        ("payment_method", "varchar"),
        ("region", "varchar"),
        ("created_at", "timestamp"),
        ("updated_at", "timestamp"),
    ],
    "sky_test_order_items": [
        ("id", "uuid"),
        ("order_id", "uuid"),
        ("product_id", "uuid"),
        ("quantity", "integer"),
        ("unit_price", "numeric"),
        ("subtotal", "numeric"),
        ("created_at", "timestamp"),
    ],
}


async def update_metadata(conn):
    # Delete existing metadata for this connection
    await conn.execute(
        text("DELETE FROM table_metadata WHERE data_connection_id = :cid"),
        {"cid": CONNECTION_ID},
    )
    print(f"  🗑️  Cleared old metadata for connection {CONNECTION_ID}")

    total_cols = 0
    for table_name, columns in TABLE_COLUMNS.items():
        table_desc = SEMANTIC_TABLE_DESCRIPTIONS.get(table_name, "")
        col_descs = SEMANTIC_COLUMN_DESCRIPTIONS.get(table_name, {})

        for col_name, data_type in columns:
            col_desc = col_descs.get(col_name, "")
            # Combine table + column description for a rich embedding target
            full_description = (
                f"TABLE: {table_name}\n"
                f"PURPOSE: {table_desc}\n"
                f"COLUMN: {col_name} ({data_type})\n"
                f"COLUMN MEANING: {col_desc}"
            )
            await conn.execute(
                text(
                    """
                INSERT INTO table_metadata
                    (id, data_connection_id, space_id, crew_id,
                     table_name, column_name, data_type, is_nullable,
                     description, extra, created_at)
                VALUES
                    (gen_random_uuid(), :conn_id, :space_id, NULL,
                     :table_name, :col_name, :data_type, TRUE,
                     :description, :extra, NOW())
            """
                ),
                {
                    "conn_id": CONNECTION_ID,
                    "space_id": SPACE_ID,
                    "table_name": table_name,
                    "col_name": col_name,
                    "data_type": data_type,
                    "description": full_description,
                    "extra": json.dumps(
                        {
                            "table_description": table_desc,
                            "column_description": col_desc,
                            "semantic_tags": _extract_tags(table_name, col_name),
                        }
                    ),
                },
            )
            total_cols += 1

    table_count = len(TABLE_COLUMNS)
    print(
        f"  ✅ Semantic metadata inserted: {table_count} tables, {total_cols} columns"
    )


def _extract_tags(table_name: str, col_name: str) -> list:
    """Return business-term tags for easier filtering/debugging."""
    tags_map = {
        ("sky_test_orders", "total_amount"): [
            "revenue",
            "sales",
            "income",
            "earnings",
            "aov",
        ],
        ("sky_test_orders", "discount_amount"): [
            "discount",
            "net_revenue",
            "promotion",
        ],
        ("sky_test_orders", "status"): [
            "completed",
            "cancelled",
            "refunded",
            "pending",
        ],
        ("sky_test_orders", "region"): ["region", "geography", "location"],
        ("sky_test_orders", "channel"): ["channel", "online", "in-store"],
        ("sky_test_order_items", "subtotal"): [
            "product_revenue",
            "line_revenue",
            "category_revenue",
        ],
        ("sky_test_order_items", "quantity"): ["units_sold", "volume", "quantity"],
        ("sky_test_products", "price"): ["selling_price", "price", "revenue_potential"],
        ("sky_test_products", "cost"): ["cogs", "cost", "profit_margin"],
        ("sky_test_products", "stock"): ["inventory", "stock_level", "out_of_stock"],
        ("sky_test_products", "rating"): ["reviews", "rating", "customer_satisfaction"],
        ("sky_test_customers", "created_at"): [
            "acquisition",
            "new_customers",
            "signup",
        ],
        ("sky_test_customers", "last_order_at"): ["churn", "inactive", "retention"],
        ("sky_test_customers", "segment"): ["segment", "enterprise", "smb"],
        ("sky_test_sales_reps", "name"): [
            "sales_rep",
            "salesperson",
            "rep_performance",
        ],
    }
    return tags_map.get((table_name, col_name), [])


async def main():
    print("=" * 60)
    print("  SEMANTIC METADATA UPDATE")
    print("=" * 60)

    engine = create_async_engine(DB_URL, echo=False)

    async with engine.begin() as conn:
        await update_metadata(conn)

    await engine.dispose()
    print("\n✅ Done. Now run: python tests/test_semantic_10.py")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
