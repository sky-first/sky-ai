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
    
    
    # ===== OLLAMA CONFIGURATION (ACTIVE) =====
    # All AI models use local Ollama inference
    # Endpoint: https://ollama.skyfirstlabs.com
    use_local_models: bool = True  # ✅ OLLAMA ENABLED
    ollama_base_url: str = Field( 
        validation_alias=AliasChoices("OLLAMA_BASE_URL", "ollama_base_url")
    )
    
    # Ollama Models (RunPod — RTX A6000 48GB)
    # Swapped from phi3:medium to qwen2.5-coder:32b (2026-04-16):
    # phi3 topped out at 4K context and was weak on SQL join reasoning;
    # Qwen 2.5 Coder 32B is code/SQL-specialized, supports 128K native
    # context, and fits comfortably in A6000 at Q4 quant.
    # Embedding kept as nomic-embed-text (768 dims) to preserve compatibility
    # with the existing pgvector schema — switch to bge-m3 requires a
    # dimension migration + full re-embed.
    llm_model_orchestrator_local: str = "qwen2.5-coder:32b"
    llm_model_specialist_local: str = "qwen2.5-coder:32b"
    llm_model_formatter_local: str = "qwen2.5-coder:32b"
    llm_model_embedding_local: str = "nomic-embed-text"

    # Ollama Context Windows (num_ctx) — bumped to leverage Qwen's 128K ceiling
    # while keeping VRAM usage predictable. A6000 48GB handles 32K specialist
    # comfortably; higher values risk OOM when the formatter runs concurrently.
    ollama_num_ctx_orchestrator: int = 8192
    ollama_num_ctx_specialist: int = 32768
    ollama_num_ctx_formatter: int = 8192
    
    # LLM General Settings
    llm_temperature: float = 0.0
    
    
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
    
    # ===== AI PROVIDER SWITCH =====
    # "ollama" (default — RunPod-hosted Qwen 2.5 Coder 32B, pay-per-hour)
    # "openai" (fallback — gpt-4o, pay-per-token, only for premium tier)
    # Flipped from "openai" to "ollama" on 2026-04-16 after confirming the
    # old Ollama endpoint in the .env was dead (404) and OpenAI was silently
    # burning through ~$10/day of credits in dev.
    ai_provider: str = Field(
        default="ollama",
        validation_alias=AliasChoices("AI_PROVIDER", "ai_provider")
    )

    # ===== OPENAI CONFIGURATION (ACTIVE IF AI_PROVIDER="openai") =====
    # OpenAI API Key
    openai_api_key: Optional[str] = Field(default=None, validation_alias=AliasChoices("OPENAI_API_KEY", "openai_api_key"))

    # OpenAI Models
    llm_model_orchestrator: str = "gpt-4o-mini"
    llm_model_specialist: str = "gpt-4o"
    llm_model_formatter: str = "gpt-4o-mini"
    llm_model_default: str = "gpt-4o"
    
    # Embedding Model (OpenAI)
    embedding_model: str = "text-embedding-3-large"
    
    # JWT Secret (shared with backend for service-to-service auth)
    jwt_secret_key: str = Field(
        default="",
        validation_alias=AliasChoices("JWT_SECRET_KEY", "jwt_secret_key"),
        description="JWT secret for generating service tokens to call backend API.",
    )

    # Backend API (sky-poc-backend) — for strategy, signals, relationships
    backend_url: str = Field(
        default="http://localhost:8000/api/v1",
        validation_alias=AliasChoices("BACKEND_URL", "backend_url"),
        description="URL of the sky-poc-backend API. Used by multi-agent specialists for strategy/signals/context data.",
    )

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
    
    # Inference Cache (CPU optimization)
    enable_inference_cache: bool = True  # Enable LLM response caching
    inference_cache_max_size: int = 1000  # Maximum cached responses
    inference_cache_ttl_seconds: int = 1800  # 30 minutes TTL
    
    # Context Bundle
    use_context_bundle: bool = True  # Enable new context architecture
    
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

        # AI Provider Logic
        # Controls use_local_models based on AI_PROVIDER env var
        if self.ai_provider.lower() == "openai":
            self.use_local_models = False
        elif self.ai_provider.lower() == "ollama":
            self.use_local_models = True
        
        return self


settings = Settings()

