
import os
from google.cloud import bigquery

def debug_query_logic():
    client = bigquery.Client()
    
    # Check 1: Do we have ANY 'High' value invoices?
    query_high = """
    SELECT COUNT(*) as count 
    FROM `data-mesh-gcp.billing_silver.silver_invoices_enriquecido`
    WHERE invoice_value_category = 'High'
    """
    
    # Check 2: Do we have MATCHING customer_ids?
    query_join = """
    SELECT COUNT(*) as count
    FROM `data-mesh-gcp.billing_silver.silver_invoices_enriquecido` i
    JOIN `data-mesh-gcp.billing_silver.silver_customers_enriquecido` c
    ON i.customer_id = c.customer_id
    """

    print("--- Debugging Empty Result ---")
    
    try:
        rows = list(client.query(query_high).result())
        print(f"1. Invoices with category='High': {rows[0].count}")
        
        rows = list(client.query(query_join).result())
        print(f"2. Successful JOINs between Invoices/Customers: {rows[0].count}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    debug_query_logic()
