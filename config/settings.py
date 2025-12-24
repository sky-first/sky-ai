"""Application settings and configuration."""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Database
    # Local dev default (override via DATABASE_URL in .env)
    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/ai_saas_db"
    
    # OpenAI
    openai_api_key: str
    
    # OpenAI Model Configurations
    # LLM Models
    llm_model_orchestrator: str = "gpt-4o-mini"
    llm_model_specialist: str = "gpt-4o"
    llm_model_formatter: str = "gpt-4o-mini"
    llm_model_default: str = "gpt-4o"
    llm_temperature: float = 0.0
    
    # Embedding Models
    embedding_model: str = "text-embedding-3-large"
    
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
        # Allow running from both repo root and ia-do-projeto/ without duplicating secrets.
        env_file = (".env", "../.env")
        case_sensitive = False


settings = Settings()

