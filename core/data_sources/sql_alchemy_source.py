"""Generic SQLAlchemy data source implementation."""
from typing import List, Dict, Any, Optional
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from core.data_sources.base import BaseDataSource, DataSourceConfig


class SQLAlchemySource(BaseDataSource):
    """Generic SQLAlchemy-based data source (Postgres, MySQL, SQL Server, etc.)."""
    
    def __init__(self, config: DataSourceConfig):
        super().__init__(config)
        connection_string = self.config.config.get("connection_string")
        if not connection_string:
            raise ValueError("connection_string is required in config")
        
        self.engine = create_engine(connection_string, pool_pre_ping=True)
    
    def execute_query(self, query: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Execute a SQL query using SQLAlchemy."""
        if limit:
            # Try to add LIMIT clause if not present
            query_upper = query.upper().strip()
            if "LIMIT" not in query_upper:
                query = f"{query} LIMIT {limit}"
        
        with self.engine.connect() as conn:
            result = conn.execute(text(query))
            rows = result.fetchall()
            
            # Convert to list of dicts
            columns = result.keys()
            return [dict(zip(columns, row)) for row in rows]
    
    def get_table_schema(self, schema_name: Optional[str], table_name: str) -> Dict[str, Any]:
        """Get table schema using SQLAlchemy inspector."""
        inspector = inspect(self.engine)
        
        columns = []
        for column in inspector.get_columns(table_name, schema=schema_name):
            columns.append({
                "name": column["name"],
                "type": str(column["type"]),
                "nullable": column["nullable"],
                "default": str(column.get("default", ""))
            })
        
        # Get primary keys
        primary_keys = inspector.get_primary_keys(table_name, schema=schema_name)
        
        # Get foreign keys
        foreign_keys = []
        for fk in inspector.get_foreign_keys(table_name, schema=schema_name):
            foreign_keys.append({
                "name": fk.get("name"),
                "constrained_columns": fk.get("constrained_columns"),
                "referred_table": fk.get("referred_table"),
                "referred_columns": fk.get("referred_columns")
            })
        
        return {
            "table_name": table_name,
            "schema_name": schema_name,
            "columns": columns,
            "primary_keys": primary_keys,
            "foreign_keys": foreign_keys
        }
    
    def list_tables(self, schema_name: Optional[str] = None) -> List[str]:
        """List tables using SQLAlchemy inspector."""
        inspector = inspect(self.engine)
        return inspector.get_table_names(schema=schema_name)
    
    def test_connection(self) -> bool:
        """Test database connection."""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

