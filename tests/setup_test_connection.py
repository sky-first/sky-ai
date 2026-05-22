#!/usr/bin/env python3
"""
Test Environment Setup Script
------------------------------
Creates:
  1. Business data tables (customers, products, orders, sales) with realistic fake data
  2. A DataConnection record pointing to the same PostgreSQL (ai_saas_db)
  3. SpaceConnection linking to the existing Default space
  4. TableMetadata entries for RAG table discovery

Usage:
    python tests/setup_test_connection.py

Prints the CONNECTION_ID, SPACE_ID, USER_ID to use in test_100_cases.py.
"""

import asyncio
import json
import random
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# Add repo root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_saas_db"
DB_DSN = "postgresql+psycopg2://postgres:postgres@localhost:5432/ai_saas_db"

# Fixed test IDs (deterministic so re-runs don't duplicate)
TEST_CONNECTION_ID = uuid.UUID("aaaa0001-0000-4000-a000-000000000001")
TEST_SPACE_ID = uuid.UUID(
    "d21795e0-430c-4f72-99ae-4c61512e17d1"
)  # existing Default space

random.seed(42)

# ─── Fake Data Generators ────────────────────────────────────────────────────

REGIONS = ["North", "South", "East", "West", "Central"]
STATUSES = ["completed", "pending", "cancelled", "refunded"]
CHANNELS = ["online", "in-store", "mobile", "phone"]
SEGMENTS = ["enterprise", "smb", "startup", "consumer"]
COUNTRIES = ["US", "BR", "UK", "DE", "FR", "CA", "AU", "MX"]
CATEGORIES = [
    "Electronics",
    "Clothing",
    "Food",
    "Books",
    "Sports",
    "Home",
    "Beauty",
    "Toys",
]
PAYMENT_METHODS = ["credit_card", "debit_card", "paypal", "bank_transfer", "pix"]

PRODUCT_NAMES = [
    "Laptop Pro 15",
    "Wireless Headphones",
    "Running Shoes",
    "Cotton T-Shirt",
    "Python Cookbook",
    "Coffee Maker",
    "Yoga Mat",
    "Smart Watch",
    "Desk Lamp",
    "Bluetooth Speaker",
    "Gaming Mouse",
    "Office Chair",
    "Water Bottle",
    "Protein Powder",
    "Sunglasses",
    "Backpack",
    "Mechanical Keyboard",
    "Monitor 27in",
    "Standing Desk",
    "USB Hub",
]

CUSTOMER_NAMES = [
    "Alice Johnson",
    "Bob Smith",
    "Carol White",
    "David Brown",
    "Eva Martinez",
    "Frank Lee",
    "Grace Kim",
    "Henry Wilson",
    "Iris Chen",
    "Jack Davis",
    "Kate Thompson",
    "Liam Garcia",
    "Mia Anderson",
    "Noah Taylor",
    "Olivia Moore",
    "Paul Jackson",
    "Quinn Harris",
    "Rachel Clark",
    "Sam Lewis",
    "Tina Robinson",
    "Uma Scott",
    "Victor Hall",
    "Wendy Allen",
    "Xavier Young",
    "Yara King",
    "Zach Wright",
    "Ana Perez",
    "Ben Turner",
    "Chloe Nguyen",
    "Dan Hill",
]

SALES_REP_NAMES = [
    "Alex Rivera",
    "Barbara Stone",
    "Carlos Mendes",
    "Diana Prince",
    "Ethan Hunt",
]


def rand_date(start_days_ago=730, end_days_ago=0):
    offset = random.randint(end_days_ago, start_days_ago)
    return datetime.now() - timedelta(days=offset)


def rand_amount(min_v=5.0, max_v=5000.0):
    return round(random.uniform(min_v, max_v), 2)


# ─── DDL ──────────────────────────────────────────────────────────────────────

DDL_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS sky_test_customers (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name            VARCHAR(200)    NOT NULL,
        email           VARCHAR(200)    NOT NULL UNIQUE,
        country         VARCHAR(50),
        segment         VARCHAR(50),
        is_active       BOOLEAN         DEFAULT TRUE,
        created_at      TIMESTAMP       DEFAULT NOW(),
        last_order_at   TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS sky_test_products (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name            VARCHAR(200)    NOT NULL,
        category        VARCHAR(100),
        price           NUMERIC(12,2)   NOT NULL,
        cost            NUMERIC(12,2),
        stock           INTEGER         DEFAULT 0,
        is_active       BOOLEAN         DEFAULT TRUE,
        rating          NUMERIC(3,2),
        created_at      TIMESTAMP       DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS sky_test_sales_reps (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name            VARCHAR(200)    NOT NULL,
        region          VARCHAR(50),
        hire_date       TIMESTAMP       DEFAULT NOW(),
        is_active       BOOLEAN         DEFAULT TRUE
    )""",
    """CREATE TABLE IF NOT EXISTS sky_test_orders (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        customer_id     UUID            REFERENCES sky_test_customers(id),
        sales_rep_id    UUID            REFERENCES sky_test_sales_reps(id),
        status          VARCHAR(50)     DEFAULT 'pending',
        channel         VARCHAR(50),
        total_amount    NUMERIC(12,2)   NOT NULL,
        discount_amount NUMERIC(12,2)   DEFAULT 0,
        payment_method  VARCHAR(50),
        region          VARCHAR(50),
        created_at      TIMESTAMP       DEFAULT NOW(),
        updated_at      TIMESTAMP       DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS sky_test_order_items (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        order_id        UUID            REFERENCES sky_test_orders(id),
        product_id      UUID            REFERENCES sky_test_products(id),
        quantity        INTEGER         NOT NULL DEFAULT 1,
        unit_price      NUMERIC(12,2)   NOT NULL,
        subtotal        NUMERIC(12,2)   NOT NULL,
        created_at      TIMESTAMP       DEFAULT NOW()
    )""",
]

TRUNCATE_STATEMENTS = [
    "TRUNCATE sky_test_order_items CASCADE",
    "TRUNCATE sky_test_orders CASCADE",
    "TRUNCATE sky_test_customers CASCADE",
    "TRUNCATE sky_test_products CASCADE",
    "TRUNCATE sky_test_sales_reps CASCADE",
]


# ─── Data Seed ────────────────────────────────────────────────────────────────


async def seed_data(conn):
    # Customers
    customer_ids = []
    for i, name in enumerate(CUSTOMER_NAMES):
        cid = str(uuid.uuid4())
        customer_ids.append(cid)
        email = name.lower().replace(" ", ".") + f"{i}@example.com"
        created = rand_date(730, 10)
        last_order = rand_date(10, 0) if random.random() > 0.2 else None
        await conn.execute(
            text("""
            INSERT INTO sky_test_customers (id, name, email, country, segment, is_active, created_at, last_order_at)
            VALUES (:id, :name, :email, :country, :segment, :active, :created_at, :last_order_at)
        """),
            {
                "id": cid,
                "name": name,
                "email": email,
                "country": random.choice(COUNTRIES),
                "segment": random.choice(SEGMENTS),
                "active": random.random() > 0.1,
                "created_at": created,
                "last_order_at": last_order,
            },
        )

    # Products
    product_ids = []
    for name in PRODUCT_NAMES:
        pid = str(uuid.uuid4())
        product_ids.append(pid)
        price = rand_amount(10, 2000)
        cost = round(price * random.uniform(0.3, 0.7), 2)
        await conn.execute(
            text("""
            INSERT INTO sky_test_products (id, name, category, price, cost, stock, is_active, rating, created_at)
            VALUES (:id, :name, :category, :price, :cost, :stock, :active, :rating, :created_at)
        """),
            {
                "id": pid,
                "name": name,
                "category": random.choice(CATEGORIES),
                "price": price,
                "cost": cost,
                "stock": random.randint(0, 500),
                "active": random.random() > 0.05,
                "rating": round(random.uniform(2.5, 5.0), 2),
                "created_at": rand_date(730, 0),
            },
        )

    # Sales reps
    rep_ids = []
    for name in SALES_REP_NAMES:
        rid = str(uuid.uuid4())
        rep_ids.append(rid)
        await conn.execute(
            text("""
            INSERT INTO sky_test_sales_reps (id, name, region, hire_date, is_active)
            VALUES (:id, :name, :region, :hire_date, true)
        """),
            {
                "id": rid,
                "name": name,
                "region": random.choice(REGIONS),
                "hire_date": rand_date(1000, 60),
            },
        )

    # Orders (500 orders across 2 years)
    order_ids = []
    for _ in range(500):
        oid = str(uuid.uuid4())
        order_ids.append(oid)
        cid = random.choice(customer_ids)
        rid = random.choice(rep_ids)
        status = random.choices(STATUSES, weights=[70, 15, 10, 5])[0]
        total = rand_amount(20, 3000)
        discount = (
            round(total * random.uniform(0, 0.25), 2) if random.random() > 0.6 else 0.0
        )
        created = rand_date(730, 0)
        await conn.execute(
            text("""
            INSERT INTO sky_test_orders (id, customer_id, sales_rep_id, status, channel,
                total_amount, discount_amount, payment_method, region, created_at, updated_at)
            VALUES (:id, :cid, :rid, :status, :channel,
                :total, :discount, :payment, :region, :created, :updated)
        """),
            {
                "id": oid,
                "cid": cid,
                "rid": rid,
                "status": status,
                "channel": random.choice(CHANNELS),
                "total": total,
                "discount": discount,
                "payment": random.choice(PAYMENT_METHODS),
                "region": random.choice(REGIONS),
                "created": created,
                "updated": created,
            },
        )

        # Order items (1-4 items per order)
        n_items = random.randint(1, 4)
        for _ in range(n_items):
            pid = random.choice(product_ids)
            qty = random.randint(1, 5)
            unit_price = rand_amount(5, 500)
            await conn.execute(
                text("""
                INSERT INTO sky_test_order_items (id, order_id, product_id, quantity, unit_price, subtotal, created_at)
                VALUES (:id, :oid, :pid, :qty, :unit_price, :subtotal, :created)
            """),
                {
                    "id": str(uuid.uuid4()),
                    "oid": oid,
                    "pid": pid,
                    "qty": qty,
                    "unit_price": unit_price,
                    "subtotal": round(unit_price * qty, 2),
                    "created": created,
                },
            )

    print(
        f"  ✅ Seeded: {len(customer_ids)} customers, {len(product_ids)} products, "
        f"{len(rep_ids)} reps, 500 orders"
    )


# ─── Connection & Metadata Registration ───────────────────────────────────────

TABLE_DESCRIPTIONS = {
    "sky_test_customers": "Contains customer records with demographics, segment, country and activity status",
    "sky_test_products": "Product catalog with pricing, cost, category, stock level and ratings",
    "sky_test_orders": "Sales orders with status, channel, amount, discount, payment method and region",
    "sky_test_order_items": "Line items within each order — product, quantity and pricing details",
    "sky_test_sales_reps": "Sales representatives with name, region and hire date",
}

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

COLUMN_DESCRIPTIONS = {
    "sky_test_customers": {
        "id": "Unique customer identifier",
        "name": "Customer full name",
        "email": "Customer email address",
        "country": "Country code (US, BR, UK, etc.)",
        "segment": "Customer segment: enterprise, smb, startup, consumer",
        "is_active": "Whether the customer is currently active",
        "created_at": "When the customer registered",
        "last_order_at": "Date of the customer's most recent order",
    },
    "sky_test_products": {
        "id": "Unique product identifier",
        "name": "Product name",
        "category": "Product category (Electronics, Clothing, etc.)",
        "price": "Selling price in USD",
        "cost": "Cost of goods (COGS) in USD",
        "stock": "Current inventory stock count",
        "is_active": "Whether the product is available for sale",
        "rating": "Average customer rating (1-5)",
        "created_at": "When the product was added to the catalog",
    },
    "sky_test_orders": {
        "id": "Unique order identifier",
        "customer_id": "FK to sky_test_customers.id",
        "sales_rep_id": "FK to sky_test_sales_reps.id",
        "status": "Order status: completed, pending, cancelled, refunded",
        "channel": "Sales channel: online, in-store, mobile, phone",
        "total_amount": "Total order value in USD before discount",
        "discount_amount": "Discount applied to the order in USD",
        "payment_method": "Payment method used",
        "region": "Geographic region: North, South, East, West, Central",
        "created_at": "When the order was placed",
        "updated_at": "When the order was last updated",
    },
    "sky_test_order_items": {
        "id": "Unique line item identifier",
        "order_id": "FK to sky_test_orders.id",
        "product_id": "FK to sky_test_products.id",
        "quantity": "Number of units ordered",
        "unit_price": "Price per unit at time of sale",
        "subtotal": "quantity * unit_price",
        "created_at": "When the item was added",
    },
    "sky_test_sales_reps": {
        "id": "Unique sales rep identifier",
        "name": "Sales representative full name",
        "region": "Geographic region the rep covers",
        "hire_date": "Date the rep was hired",
        "is_active": "Whether the rep is currently active",
    },
}


async def register_connection(conn):
    conn_id = str(TEST_CONNECTION_ID)
    space_id = str(TEST_SPACE_ID)

    # Get the kaique user id (admin)
    admin_user_id = "32a2a83c-5dc9-4a82-b228-6fa976c173b1"

    # Upsert DataConnection (include all NOT NULL backend columns)
    await conn.execute(
        text("""
        INSERT INTO data_connections (id, name, connector_id, config, status, created_by, created_at, updated_at)
        VALUES (:id, :name, :connector_id, :config, 'active', :created_by, NOW(), NOW())
        ON CONFLICT (id) DO UPDATE
          SET name=EXCLUDED.name, config=EXCLUDED.config, status='active', updated_at=NOW()
    """),
        {
            "id": conn_id,
            "name": "Test PostgreSQL (sky_test_*)",
            "connector_id": "postgres",
            "config": json.dumps({"dsn": DB_DSN}),
            "created_by": admin_user_id,
        },
    )
    print(f"  ✅ DataConnection registered: {conn_id}")

    # Check if SpaceConnection table exists and link it
    result = await conn.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name='space_connections' ORDER BY ordinal_position LIMIT 5
    """))
    sc_cols = [r[0] for r in result]
    print(f"  space_connections columns: {sc_cols}")

    if "connection_id" in sc_cols and "space_id" in sc_cols:
        await conn.execute(
            text("""
            INSERT INTO space_connections (space_id, connection_id)
            VALUES (:space_id, :conn_id)
            ON CONFLICT DO NOTHING
        """),
            {"space_id": space_id, "conn_id": conn_id},
        )
        print(f"  ✅ SpaceConnection linked to space {space_id}")

    # Clear old metadata for this connection
    await conn.execute(
        text("DELETE FROM table_metadata WHERE data_connection_id = :cid"),
        {"cid": conn_id},
    )

    # Insert TableMetadata (one row per column)
    for table_name, columns in TABLE_COLUMNS.items():
        desc = TABLE_DESCRIPTIONS.get(table_name, "")
        col_descs = COLUMN_DESCRIPTIONS.get(table_name, {})
        for col_name, data_type in columns:
            col_desc = col_descs.get(col_name, "")
            await conn.execute(
                text("""
                INSERT INTO table_metadata
                    (id, data_connection_id, space_id, crew_id,
                     table_name, column_name, data_type, is_nullable,
                     description, extra, created_at)
                VALUES
                    (gen_random_uuid(), :conn_id, :space_id, NULL,
                     :table_name, :col_name, :data_type, TRUE,
                     :description, :extra, NOW())
            """),
                {
                    "conn_id": conn_id,
                    "space_id": space_id,
                    "table_name": table_name,
                    "col_name": col_name,
                    "data_type": data_type,
                    "description": f"{table_name}: {desc} | Column '{col_name}': {col_desc}",
                    "extra": json.dumps({"table_description": desc}),
                },
            )

    table_count = len(TABLE_COLUMNS)
    col_count = sum(len(cols) for cols in TABLE_COLUMNS.values())
    print(f"  ✅ TableMetadata: {table_count} tables, {col_count} columns registered")


# ─── Main ─────────────────────────────────────────────────────────────────────


async def main():
    print("=" * 60)
    print("  TEST ENVIRONMENT SETUP")
    print("=" * 60)

    engine = create_async_engine(DB_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        print("\n[1/3] Creating business tables...")
        for stmt in DDL_STATEMENTS:
            await conn.execute(text(stmt))
        print("  ✅ Tables created (sky_test_*)")

        print("\n[2/3] Truncating and seeding data...")
        for stmt in TRUNCATE_STATEMENTS:
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass  # Table may not have data yet
        await seed_data(conn)

        print("\n[3/3] Registering DataConnection + TableMetadata...")
        await register_connection(conn)

    await engine.dispose()

    print("\n" + "=" * 60)
    print("  SETUP COMPLETE — update test_100_cases.py with:")
    print("=" * 60)
    print(f'  CONNECTION_ID = "{TEST_CONNECTION_ID}"')
    print(f'  SPACE_ID      = "{TEST_SPACE_ID}"')
    print(
        f'  USER_ID       = "32a2a83c-5dc9-4a82-b228-6fa976c173b1"  # kaique.mendonca@'
    )
    print(f"  CREW_IDS      = []")
    print("=" * 60)
    print()


if __name__ == "__main__":
    asyncio.run(main())
