from __future__ import annotations

import os
import sys

from core.data_sources.bigquery_source import BigQueryDataSource

# Add root to path
sys.path.append(os.getcwd())


def verify():
    print("--- Verifying Answer Accuracy ---")

    # 1. Setup DataSource
    # We need the project_id. Usually in settings or env.
    project_id = "data-mesh-gcp"
    dataset = "billing_silver"
    # Use the local file we just created
    creds_path = (
        "/Users/thedatafirst/skyfirst/repositories/sky-poc-ai/gcp_service_account.json"
    )
    print(f"DEBUG: Using creds_path: '{creds_path}'")

    bq = BigQueryDataSource(
        project_id=project_id, dataset=dataset, credentials_path=creds_path
    )

    # 2. Run Query
    # The AI answer implies grouping by invoice and summing amount.
    # Claims:
    # Max: 84,962.88 (INV_000742)
    # Min (of sample): 53,026.86 (INV_000407)

    sql = """
    SELECT
        invoice_id,
        SUM(total_amount) as total_value
    FROM `data-mesh-gcp.billing_silver.silver_invoices_enriquecido`
    GROUP BY invoice_id
    ORDER BY total_value DESC
    LIMIT 15
    """

    print(f"Executing SQL:\n{sql}\n")

    try:
        results = bq.run_query(sql)

        print("\n--- Top Results from Database ---")
        for i, row in enumerate(results):
            print(f"{i + 1}. {row['invoice_id']}: ${row['total_value']:,.2f}")

        # Check specific hallucinated ID
        print("\n--- Checking specific ID claim: INV_000742 ---")
        sql_check = "SELECT invoice_id, total_amount FROM `data-mesh-gcp.billing_silver.silver_invoices_enriquecido` WHERE invoice_id = 'INV_000742'"
        check_res = bq.run_query(sql_check)
        if check_res:
            print(f"Found INV_000742: {check_res}")
        else:
            print("❌ INV_000742 NOT FOUND in database. (Hallucination confirmed)")

        # Verify specific claims
        found_max = False
        found_min = False

        for row in results:
            val = float(row["total_value"])
            inv = row["invoice_id"]

            if inv == "INV_000742" and abs(val - 84962.88) < 0.1:
                found_max = True
            if inv == "INV_000407" and abs(val - 53026.86) < 0.1:
                found_min = True

        print("\n--- Verification ---")
        if found_max:
            print("✅ Max value matches: INV_000742 = $84,962.88")
        else:
            print("❌ Max value MISMATCH or not in top 15.")

        if found_min:
            print("✅ Min value matches (in sample): INV_000407 = $53,026.86")
        else:
            print("❌ Min value MISMATCH or not in top 15.")

    except Exception as e:
        print(f"Error executing query: {e}")


if __name__ == "__main__":
    verify()
