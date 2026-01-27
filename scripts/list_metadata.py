#!/usr/bin/env python3
"""Script para listar metadados disponíveis"""

import os
import sys
from dotenv import load_dotenv
load_dotenv()

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from db.base import SyncSessionLocal
from db.models import TableMetadata
from sqlalchemy import func

def list_metadata():
    db = SyncSessionLocal()
    try:
        results = db.query(
            TableMetadata.space_id,
            TableMetadata.data_connection_id,
            func.count(TableMetadata.id)
        ).group_by(TableMetadata.space_id, TableMetadata.data_connection_id).all()
        
        print(f"Encontrados {len(results)} grupos de metadados:")
        for r in results:
            print(f"Space: {r[0]} | Connection: {r[1]} | Count: {r[2]}")
            
    finally:
        db.close()

if __name__ == "__main__":
    list_metadata()
