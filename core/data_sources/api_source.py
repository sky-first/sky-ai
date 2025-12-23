"""REST/GraphQL API data source implementation."""
from typing import List, Dict, Any, Optional
import httpx
from core.data_sources.base import BaseDataSource, DataSourceConfig


class APISource(BaseDataSource):
    """REST/GraphQL API data source implementation."""
    
    def __init__(self, config: DataSourceConfig):
        super().__init__(config)
        self.base_url = self.config.config.get("base_url")
        self.api_key = self.config.config.get("api_key")
        self.headers = self.config.config.get("headers", {})
        
        if self.api_key:
            self.headers["Authorization"] = f"Bearer {self.api_key}"
    
    def execute_query(self, query: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Execute a query against a REST/GraphQL API.
        
        For REST APIs, query might be a URL path or JSON body.
        For GraphQL, query is the GraphQL query string.
        """
        api_type = self.config.config.get("api_type", "rest")
        
        if api_type == "graphql":
            return self._execute_graphql_query(query, limit)
        else:
            return self._execute_rest_query(query, limit)
    
    def _execute_rest_query(self, query: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Execute REST API query."""
        url = f"{self.base_url}/{query}"
        
        with httpx.Client() as client:
            response = client.get(url, headers=self.headers)
            response.raise_for_status()
            data = response.json()
            
            if isinstance(data, list):
                return data[:limit] if limit else data
            elif isinstance(data, dict):
                # Try to find a list in the response
                for key in ["data", "results", "items"]:
                    if key in data and isinstance(data[key], list):
                        return data[key][:limit] if limit else data[key]
                return [data]
            return []
    
    def _execute_graphql_query(self, query: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Execute GraphQL query."""
        with httpx.Client() as client:
            response = client.post(
                self.base_url,
                json={"query": query},
                headers=self.headers
            )
            response.raise_for_status()
            data = response.json()
            
            if "data" in data:
                # Extract data from GraphQL response
                return [data["data"]]
            return []
    
    def get_table_schema(self, schema_name: Optional[str], table_name: str) -> Dict[str, Any]:
        """Get API endpoint schema (metadata)."""
        # For APIs, this might fetch OpenAPI/Swagger schema
        schema_endpoint = self.config.config.get("schema_endpoint", "/schema")
        url = f"{self.base_url}{schema_endpoint}/{table_name}"
        
        with httpx.Client() as client:
            response = client.get(url, headers=self.headers)
            if response.status_code == 200:
                return response.json()
        
        # Return basic structure if schema endpoint not available
        return {
            "table_name": table_name,
            "schema_name": schema_name,
            "columns": [],
            "type": "api_endpoint"
        }
    
    def list_tables(self, schema_name: Optional[str] = None) -> List[str]:
        """List available API endpoints."""
        # Try to get list of endpoints from schema
        schema_endpoint = self.config.config.get("schema_endpoint", "/schema")
        url = f"{self.base_url}{schema_endpoint}"
        
        with httpx.Client() as client:
            response = client.get(url, headers=self.headers)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict) and "endpoints" in data:
                    return data["endpoints"]
        
        return []
    
    def test_connection(self) -> bool:
        """Test API connection."""
        try:
            health_endpoint = self.config.config.get("health_endpoint", "/health")
            url = f"{self.base_url}{health_endpoint}"
            
            with httpx.Client() as client:
                response = client.get(url, headers=self.headers, timeout=5.0)
                return response.status_code == 200
        except Exception:
            return False

