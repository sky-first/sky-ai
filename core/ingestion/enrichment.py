# core/ingestion/enrichment.py
from __future__ import annotations

import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from db.models import DataConnection, TableMetadata
from core.logging_utils import log_event
from core.ingestion.db_metadata import _create_bq_client, _executor

async def enrich_table_date_ranges(
    db: AsyncSession,
    connection_id: str,
) -> int:
    """
    Identifies date/time columns for a connection and runs MIN/MAX queries
    to find the data range, updating TableMetadata.extra.
    """
    # 1. Fetch connection and its metadata
    result = await db.execute(
        select(DataConnection).where(DataConnection.id == connection_id)
    )
    dc = result.scalar_one_or_none()
    if not dc:
        return 0

    # We only support BigQuery for now
    if (dc.connector_id or "").lower() != "bigquery":
        return 0

    # 2. Find date/time columns
    result = await db.execute(
        select(TableMetadata).where(
            TableMetadata.data_connection_id == connection_id,
            TableMetadata.data_type.ilike("%DATE%"),
        )
    )
    date_cols = result.scalars().all()
    
    # Fallback to check TIMESTAMP as well
    result = await db.execute(
        select(TableMetadata).where(
            TableMetadata.data_connection_id == connection_id,
            TableMetadata.data_type.ilike("%TIMESTAMP%"),
        )
    )
    date_cols.extend(result.scalars().all())

    if not date_cols:
        return 0

    log_event("enrich_date_ranges_start", {"connection_id": connection_id, "num_cols": len(date_cols)})

    # 3. Create BQ Client
    try:
        client = _create_bq_client(dc.config or {})
    except Exception as e:
        log_event("enrich_date_ranges_auth_error", {"connection_id": connection_id, "error": str(e)})
        return 0

    enriched_count = 0
    
    # Group by table to avoid redundant queries if multiple date cols exist (though we usually pick one)
    table_to_cols: Dict[str, List[TableMetadata]] = {}
    for col in date_cols:
        if col.table_name not in table_to_cols:
            table_to_cols[col.table_name] = []
        table_to_cols[col.table_name].append(col)

    loop = asyncio.get_event_loop()

    for table_name, cols in table_to_cols.items():
        # Heuristic: only enrich up to 3 date columns per table to save costs
        for col in cols[:3]:
            try:
                # Use original_name if available in extra
                extra = col.extra or {}
                physical_table = extra.get("original_name") or table_name
                
                # Check if it's already qualified
                if "." not in physical_table:
                    # Try to infer dataset (similar to db_metadata)
                    from core.ingestion.db_metadata import _infer_dataset_from_config
                    dataset = _infer_dataset_from_config(dc.config or {})
                    project_id = client.project
                    full_table = f"`{project_id}.{dataset}.{physical_table}`"
                else:
                    full_table = f"`{physical_table}`"

                query = f"SELECT MIN({col.column_name}) as min_v, MAX({col.column_name}) as max_v FROM {full_table}"
                
                # Run query in executor
                def _run_range_query(c, q):
                    res = list(c.query(q).result())
                    if res:
                        return res[0].min_v, res[0].max_v
                    return None, None

                min_v, max_v = await loop.run_in_executor(_executor, _run_range_query, client, query)

                if min_v is not None or max_v is not None:
                    # Update metadata
                    current_extra = col.extra or {}
                    current_extra["min_date"] = str(min_v)
                    current_extra["max_date"] = str(max_v)
                    
                    # Also update the TableMetadata row
                    await db.execute(
                        update(TableMetadata)
                        .where(TableMetadata.id == col.id)
                        .values(extra=current_extra)
                    )
                    enriched_count += 1
            except Exception as e:
                log_event("enrich_date_range_col_error", {
                    "table": table_name, 
                    "col": col.column_name, 
                    "error": str(e)[:200]
                })

    await db.commit()
    log_event("enrich_date_ranges_done", {"connection_id": connection_id, "enriched_count": enriched_count})
    return enriched_count
