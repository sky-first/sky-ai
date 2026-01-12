
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
import sys
from uuid import uuid4

# Mock modules
from pydantic import BaseModel
class MockSecurityConfig(BaseModel):
    pass
sys.modules["core.security.security_config"] = MagicMock()
sys.modules["core.security.security_config"].SecurityConfig = MockSecurityConfig

from api.routes.connection_query import validate_sql
from api.schemas import ValidateSQLRequest

# Patch ValidateSQLRequest to avoid Pydantic errors with mocks during import
# Actually, since we import schemas after mocking, the field might already be broken.
# Let's try to just NOT pass security_config in the request since it's optional.

async def test_explanation():
    print("--- Testing SQL Explanation in validate_sql ---")
    
    # Mock DB Session
    mock_db = MagicMock()
    # Mock DB execute result for finding connection
    mock_result_conn = MagicMock()
    mock_result_conn.first.return_value = ["conn-1", "Test Connection", "bigquery", "{}"]
    mock_db.execute = AsyncMock(return_value=mock_result_conn)
    
    # Mock Rate Limiter
    with patch("api.routes.connection_query._rate_limiter") as mock_limiter:
        mock_limiter.check_rate_limit.return_value = (True, None)

        # Mock Validator (pass regex)
        with patch("core.sql.validator.validate_sql_strict", return_value=(True, None)):
            
            # Mock Permissions (pass)
            with patch("api.routes.connection_query.resolve_crew_ids_for_context", return_value=["crew-1"]):
                with patch("api.routes.connection_query._get_allowed_tables_for_validation", return_value=["schema.table"]):
                    
                    # Mock AST Validator (pass)
                    with patch("api.routes.connection_query.AdvancedSQLValidator") as mock_validator_cls:
                        mock_validator_cls.return_value.validate.return_value = (True, None)
                        
                        # Mock DataSource Factory & Execution
                        with patch("api.routes.connection_query.DataSourceFactory") as mock_ds_factory:
                            mock_ds = MagicMock()
                            # Return some dummy data
                            mock_ds.run_query.return_value = [{"col1": "val1", "col2": 10}, {"col1": "val2", "col2": 20}]
                            mock_ds_factory.build_from_dataconnection.return_value = mock_ds
                            
                            # Mock LLM Formatter
                            with patch("api.routes.connection_query.create_llm_formatter") as mock_create_llm:
                                mock_llm = MagicMock()
                                mock_response = MagicMock()
                                mock_response.content = "Success! The data shows positive trends."
                                mock_llm.invoke.return_value = mock_response
                                mock_create_llm.return_value = mock_llm
                                
                                # EXECUTE
                                req = ValidateSQLRequest(
                                    user_id="user-1",
                                    space_id="space-1",
                                    sql="SELECT * FROM table",
                                    question="How is it going?",
                                    include_explanation=True
                                )
                                
                                response = await validate_sql("conn-1", req, db=mock_db)
                                
                                # VERIFY
                                if response.explanation == "Success! The data shows positive trends.":
                                    print("✅ Explanation returned correctly.")
                                else:
                                    print(f"❌ Explanation missing or wrong: {response.explanation}")

if __name__ == "__main__":
    asyncio.run(test_explanation())
