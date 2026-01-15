
import os
import sys
from google.cloud import bigquery
from datetime import datetime

# Setup credentials explicitly if needed, or rely on environment
# Usually user has GOOGLE_APPLICATION_CREDENTIALS set or is logged in via gcloud

def check_data_freshness():
    try:
        client = bigquery.Client()
        
        queries = {
            "invoices": "SELECT MIN(invoice_date) as min_date, MAX(invoice_date) as max_date, COUNT(*) as count FROM `data-mesh-gcp.billing_silver.silver_invoices_enriquecido`",
            "payments": "SELECT MIN(payment_date) as min_date, MAX(payment_date) as max_date, COUNT(*) as count FROM `data-mesh-gcp.billing_silver.silver_payments_enriquecido`"
        }
        
        print(f"--- Data Freshness Check (Current System Date: {datetime.now().date()}) ---")
        
        for table, query in queries.items():
            print(f"\nChecking table: {table}...")
            try:
                query_job = client.query(query)
                results = list(query_job.result())
                if results:
                    row = results[0]
                    print(f"  Row Count: {row.count}")
                    print(f"  Oldest Date: {row.min_date}")
                    print(f"  Newest Date: {row.max_date}")
                    
                    # Check gap
                    if row.max_date:
                        days_diff = (datetime.now().date() - row.max_date).days
                        print(f"  Gap from today: {days_diff} days")
                        if days_diff > 30:
                            print("  ⚠️ ALERT: Data is older than 30 days! 'Last 30 days' queries will be EMPTY.")
                else:
                    print("  No data returned.")
            except Exception as e:
                print(f"  Error querying {table}: {e}")
                
    except Exception as e:
        print(f"Failed to initialize BigQuery client: {e}")

if __name__ == "__main__":
    check_data_freshness()
