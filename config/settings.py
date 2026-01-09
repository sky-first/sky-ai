"""Application settings and configuration.

DEVOPS: Este módulo deve aceitar as MESMAS variáveis do `.env` do sky-poc-infra.
Objetivo: padronizar apontamentos/ports/URLs e evitar divergências por repo.
"""

from typing import Optional

from pydantic import Field, AliasChoices, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables.
    
    DEVOPS: Em produção, todas as configurações devem vir do .env do sky-poc-infra.
    Os defaults abaixo são APENAS para desenvolvimento local.
    """
    
    # Database
    # DEVOPS: Preferimos DATABASE_URL do sky-poc-infra. Se não existir, construímos a partir de POSTGRES_*.
    database_url: str = Field(
        default="",
        validation_alias=AliasChoices("DATABASE_URL", "database_url"),
        description="Database connection URL (DATABASE_URL). Em produção, vem do .env do sky-poc-infra.",
    )
    postgres_user: str = Field(default="postgres", validation_alias=AliasChoices("POSTGRES_USER", "postgres_user"))
    postgres_password: str = Field(default="", validation_alias=AliasChoices("POSTGRES_PASSWORD", "postgres_password"))
    postgres_host: str = Field(default="localhost", validation_alias=AliasChoices("POSTGRES_HOST", "postgres_host"))
    postgres_port: int = Field(default=5432, validation_alias=AliasChoices("POSTGRES_PORT", "postgres_port"))
    postgres_db: str = Field(default="ai_saas_db", validation_alias=AliasChoices("POSTGRES_DB", "postgres_db"))
    
    # OpenAI
    # DEVOPS: variável padrão é OPENAI_API_KEY no .env do sky-poc-infra.
    openai_api_key: str = Field(default="", validation_alias=AliasChoices("OPENAI_API_KEY", "openai_api_key"))
    
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
    # DEVOPS: Em produção, estas URLs são construídas automaticamente a partir de REDIS_PASSWORD
    # do .env do sky-poc-infra. Os defaults abaixo são APENAS para desenvolvimento local.
    # DEVOPS: alinhar com sky-poc-infra (CELERY_BROKER_URL / CELERY_RESULT_BACKEND)
    celery_broker_url: str = Field(
        default="",
        validation_alias=AliasChoices("CELERY_BROKER_URL", "celery_broker_url"),
        description="Celery broker URL (CELERY_BROKER_URL). Em produção, vem do .env do sky-poc-infra.",
    )
    celery_result_backend: str = Field(
        default="",
        validation_alias=AliasChoices("CELERY_RESULT_BACKEND", "celery_result_backend"),
        description="Celery result backend URL (CELERY_RESULT_BACKEND). Em produção, vem do .env do sky-poc-infra.",
    )
    redis_password: str = Field(default="", validation_alias=AliasChoices("REDIS_PASSWORD", "redis_password"))
    
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
    
    # Bootstrap suggestions
    bootstrap_variation_window_seconds: int = 300  # Frequência de variação das sugestões (5 minutos)
    
    class Config:
        # Allow running from both repo root and ia-do-projeto/ without duplicating secrets.
        # DEVOPS: também carrega o `.env` do sky-poc-infra quando rodando no monorepo.
        env_file = (".env", "../.env", "../sky-poc-infra/.env")
        case_sensitive = False

    @model_validator(mode="after")
    def devops_build_defaults(self):
        """
        DEVOPS: Se variáveis não forem fornecidas explicitamente, construir defaults compatíveis
        com o contrato do sky-poc-infra (sem quebrar dev local).
        """
        from urllib.parse import quote_plus

        # Database URL: preferir DATABASE_URL; senão construir de POSTGRES_*
        if not self.database_url:
            if self.postgres_password:
                pw = quote_plus(self.postgres_password)
            else:
                pw = ""
            self.database_url = (
                f"postgresql+psycopg2://{self.postgres_user}:{pw}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
            )

        # Celery URLs: se vazio mas temos REDIS_PASSWORD, construir iguais ao infra (mesma família de URLs)
        if (not self.celery_broker_url or not self.celery_result_backend) and self.redis_password:
            # NOTE: redis password pode ter chars especiais; encode mínimo
            rp = quote_plus(self.redis_password)
            # Usar redis host/port padrão do compose (redis:6379) quando rodando em containers
            # Em local, o usuário pode setar CELERY_* explicitamente.
            self.celery_broker_url = self.celery_broker_url or f"redis://:{rp}@redis:6379/1"
            self.celery_result_backend = self.celery_result_backend or f"redis://:{rp}@redis:6379/2"

        return self


settings = Settings()

