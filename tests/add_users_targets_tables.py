#!/usr/bin/env python3
"""
Adds two missing test tables needed for BAS-005 and FIN-009:
  - sky_test_users   → "How many active users do we have?"
  - sky_test_targets → "What is the revenue achieved vs target this month?"

Run from repo root:
    python tests/add_users_targets_tables.py
"""

import asyncio
import json
import random
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_saas_db"

CONNECTION_ID = "aaaa0001-0000-4000-a000-000000000001"
SPACE_ID      = "d21795e0-430c-4f72-99ae-4c61512e17d1"

random.seed(99)


# ── DDL ───────────────────────────────────────────────────────────────────────

DDL = [
    """CREATE TABLE IF NOT EXISTS sky_test_users (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name        VARCHAR(200)  NOT NULL,
        email       VARCHAR(200)  NOT NULL UNIQUE,
        is_active   BOOLEAN       DEFAULT TRUE,
        role        VARCHAR(50)   DEFAULT 'user',
        created_at  TIMESTAMP     DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS sky_test_targets (
        id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        year           INTEGER      NOT NULL,
        month          INTEGER      NOT NULL,
        target_revenue NUMERIC(14,2) NOT NULL,
        created_at     TIMESTAMP    DEFAULT NOW(),
        UNIQUE (year, month)
    )""",
]

TRUNCATE = [
    "TRUNCATE sky_test_users CASCADE",
    "TRUNCATE sky_test_targets CASCADE",
]

USER_NAMES = [
    "Alice Johnson", "Bob Smith", "Carol White", "David Brown",
    "Eva Martinez", "Frank Lee", "Grace Kim", "Henry Wilson",
    "Iris Chen", "Jack Davis", "Kate Thompson", "Liam Garcia",
    "Mia Anderson", "Noah Taylor", "Olivia Moore", "Paul Jackson",
    "Quinn Harris", "Rachel Clark", "Sam Lewis", "Tina Robinson",
    "Uma Scott", "Victor Hall", "Wendy Allen", "Xavier Young",
    "Yara King", "Zach Wright", "Ana Perez", "Ben Turner",
    "Chloe Nguyen", "Dan Hill",
]


async def seed_data(conn):
    # Users — ~80% active
    for i, name in enumerate(USER_NAMES):
        email = name.lower().replace(" ", ".") + f"{i}@skytest.com"
        is_active = random.random() > 0.2
        role = random.choice(["admin", "manager", "user", "user", "user"])
        created = datetime.now() - timedelta(days=random.randint(10, 500))
        await conn.execute(text("""
            INSERT INTO sky_test_users (id, name, email, is_active, role, created_at)
            VALUES (:id, :name, :email, :active, :role, :created)
            ON CONFLICT (email) DO NOTHING
        """), {
            "id": str(uuid.uuid4()), "name": name, "email": email,
            "active": is_active, "role": role, "created": created,
        })
    active_count = sum(1 for _ in USER_NAMES if random.random() > 0.2)
    print(f"  ✅ Seeded {len(USER_NAMES)} users")

    # Monthly revenue targets for the last 12 months + current month
    now = datetime.now()
    base_target = 50_000.0
    for month_offset in range(-12, 2):  # -12 months ago → +1 next month
        dt = now - timedelta(days=month_offset * 30)
        year, month = dt.year, dt.month
        # Targets grow ~5% month-over-month with some variance
        target = round(base_target * (1 + 0.05 * month_offset) * random.uniform(0.95, 1.05), 2)
        target = max(target, 10_000.0)
        await conn.execute(text("""
            INSERT INTO sky_test_targets (id, year, month, target_revenue)
            VALUES (:id, :year, :month, :target)
            ON CONFLICT (year, month) DO UPDATE SET target_revenue = EXCLUDED.target_revenue
        """), {
            "id": str(uuid.uuid4()), "year": year, "month": month, "target": target,
        })
    print(f"  ✅ Seeded monthly targets for 14 months (including current: {now.year}-{now.month:02d})")


async def register_metadata(conn):
    # Remove old entries for these two tables only
    for tname in ("sky_test_users", "sky_test_targets"):
        await conn.execute(text("""
            DELETE FROM table_metadata
            WHERE data_connection_id = :cid AND table_name = :tname
        """), {"cid": CONNECTION_ID, "tname": tname})

    tables = {
        "sky_test_users": {
            "description": (
                "Platform users table. Use this table to answer questions about: "
                "active users, total users, user count, how many users, number of users, "
                "user activity, user roles, admin users, manager users, "
                "new user registrations, user growth, user signups. "
                "Key columns: is_active = TRUE means active user, FALSE means inactive; "
                "role = admin/manager/user; created_at = signup date."
            ),
            "columns": [
                ("id",         "uuid",      "Unique user identifier (primary key)"),
                ("name",       "varchar",   "User full name"),
                ("email",      "varchar",   "User email address"),
                ("is_active",  "boolean",   "TRUE = active user. FALSE = deactivated. Filter WHERE is_active = TRUE for active user count."),
                ("role",       "varchar",   "User role: admin, manager, user. GROUP BY role for role distribution."),
                ("created_at", "timestamp", "Date the user registered / was created. Use for user growth analysis."),
            ],
        },
        "sky_test_targets": {
            "description": (
                "Monthly revenue targets table. Use this table to answer questions about: "
                "revenue target, revenue goal, sales target, target this month, "
                "revenue achieved vs target, performance vs target, target attainment, "
                "how much revenue was targeted, target for this month/quarter/year. "
                "Key columns: year = calendar year; month = 1-12; "
                "target_revenue = planned/budgeted revenue for that month. "
                "To compare actual vs target: JOIN with sky_test_orders on year/month extracted from created_at."
            ),
            "columns": [
                ("id",             "uuid",    "Unique record identifier (primary key)"),
                ("year",           "integer", "Calendar year (e.g. 2026). Use with month for a specific period."),
                ("month",          "integer", "Calendar month number 1-12. Use EXTRACT(MONTH FROM NOW()) for current month."),
                ("target_revenue", "numeric", "Budgeted/planned revenue for this month in USD. Compare with SUM(total_amount) from sky_test_orders for actual vs target."),
                ("created_at",     "timestamp", "When this target was set."),
            ],
        },
    }

    total_cols = 0
    for table_name, meta in tables.items():
        table_desc = meta["description"]
        for col_name, data_type, col_desc in meta["columns"]:
            full_description = (
                f"TABLE: {table_name}\n"
                f"PURPOSE: {table_desc}\n"
                f"COLUMN: {col_name} ({data_type})\n"
                f"COLUMN MEANING: {col_desc}"
            )
            await conn.execute(text("""
                INSERT INTO table_metadata
                    (id, data_connection_id, space_id, crew_id,
                     table_name, column_name, data_type, is_nullable,
                     description, extra, created_at)
                VALUES
                    (gen_random_uuid(), :conn_id, :space_id, NULL,
                     :table_name, :col_name, :data_type, TRUE,
                     :description, :extra, NOW())
            """), {
                "conn_id":     CONNECTION_ID,
                "space_id":    SPACE_ID,
                "table_name":  table_name,
                "col_name":    col_name,
                "data_type":   data_type,
                "description": full_description,
                "extra":       json.dumps({
                    "table_description": table_desc,
                    "column_description": col_desc,
                }),
            })
            total_cols += 1

    print(f"  ✅ TableMetadata registered: 2 tables, {total_cols} columns")


async def main():
    print("=" * 60)
    print("  ADD USERS + TARGETS TABLES")
    print("=" * 60)

    engine = create_async_engine(DB_URL, echo=False)

    async with engine.begin() as conn:
        print("\n[1/3] Creating tables...")
        for stmt in DDL:
            await conn.execute(text(stmt))
        print("  ✅ sky_test_users, sky_test_targets created")

        print("\n[2/3] Seeding data...")
        for stmt in TRUNCATE:
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass
        await seed_data(conn)

        print("\n[3/3] Registering metadata...")
        await register_metadata(conn)

    await engine.dispose()
    print("\n✅ Done. Now restart the AI service and run embeddings refresh.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
