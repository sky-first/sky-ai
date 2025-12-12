"""Application settings and configuration."""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Database
    database_url: str = "postgresql://user:password@localhost:5432/ia_poc_db"
    
    # OpenAI
    openai_api_key: str
    
    # Celery
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/0"
    
    # GCP (optional)
    google_application_credentials: Optional[str] = None
    gcp_project_id: Optional[str] = None
    
    # Security
    secret_key: str = "your-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    # App settings
    debug: bool = False
    log_level: str = "INFO"
    
    # Limits
    max_query_results: int = 1000
    max_sql_length: int = 10000
    query_timeout_seconds: int = 300
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()

