"""Application settings and configuration.

DEVOPS: Este módulo deve aceitar as MESMAS variáveis do `.env` do sky-poc-infra.
Objetivo: padronizar apontamentos/ports/URLs e evitar divergências por repo.
"""

from typing import List, Optional

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
    postgres_user: str = Field(
        default="postgres",
        validation_alias=AliasChoices("POSTGRES_USER", "postgres_user"),
    )
    postgres_password: str = Field(
        default="",
        validation_alias=AliasChoices("POSTGRES_PASSWORD", "postgres_password"),
    )
    postgres_host: str = Field(
        default="localhost",
        validation_alias=AliasChoices("POSTGRES_HOST", "postgres_host"),
    )
    postgres_port: int = Field(
        default=5432, validation_alias=AliasChoices("POSTGRES_PORT", "postgres_port")
    )
    postgres_db: str = Field(
        default="ai_saas_db",
        validation_alias=AliasChoices("POSTGRES_DB", "postgres_db"),
    )

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
    redis_password: str = Field(
        default="", validation_alias=AliasChoices("REDIS_PASSWORD", "redis_password")
    )

    # GCP (optional)
    google_application_credentials: Optional[str] = None
    gcp_project_id: Optional[str] = None

    # ===== AI PROVIDER SWITCH =====
    # "ollama"  — RunPod-hosted Qwen 2.5 Coder 32B (pay-per-hour, Azure path)
    # "openai"  — gpt-4o family (pay-per-token, fallback / premium tier)
    # "bedrock" — AWS Bedrock Claude (Sonnet 4.5 default, AWS path)
    # Flipped from "openai" to "ollama" on 2026-04-16 after confirming the
    # old Ollama endpoint in the .env was dead (404) and OpenAI was silently
    # burning through ~$10/day of credits in dev.
    ai_provider: str = Field(
        default="ollama", validation_alias=AliasChoices("AI_PROVIDER", "ai_provider")
    )
    # Derived flag set by the validator from `ai_provider`. Kept separate
    # from `use_local_models` so existing call sites that branch on the
    # OpenAI/Ollama dichotomy stay untouched.
    use_bedrock: bool = False

    # ===== OPENAI CONFIGURATION (ACTIVE IF AI_PROVIDER="openai") =====
    # OpenAI API Key
    openai_api_key: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("OPENAI_API_KEY", "openai_api_key")
    )

    # OpenAI Models
    llm_model_orchestrator: str = "gpt-4o-mini"
    llm_model_specialist: str = "gpt-4o"
    llm_model_formatter: str = "gpt-4o-mini"
    llm_model_default: str = "gpt-4o"

    # ===== BEDROCK CONFIGURATION (ACTIVE IF AI_PROVIDER="bedrock") =====
    # Credentials are picked up via IRSA when running on EKS — boto3
    # reads the OIDC token mounted at
    # /var/run/secrets/eks.amazonaws.com/serviceaccount/token. The role
    # `sky-eks-staging-bedrock` (terraform-managed, infra/aws/_eks_staging/
    # irsa.tf) grants bedrock:InvokeModel scoped to Anthropic Claude in
    # eu-west-1 only.
    bedrock_region: str = Field(
        default="eu-west-1",
        validation_alias=AliasChoices("BEDROCK_REGION", "bedrock_region"),
    )
    # Cross-region inference profile IDs (eu.* prefix). Bedrock rejects
    # the bare foundation-model ID for newer Claude releases in eu-west-1
    # with "on-demand throughput isn't supported"; the inference profile
    # routes to the underlying foundation model across EU regions.
    #
    # Cost tiering by role to avoid burning Anthropic credits ($10,100
    # ceiling until 2028-05). Haiku 4.5 runs the cheap paths (intent
    # routing, response formatting); Sonnet 4.5 runs the SQL specialist
    # where output quality directly affects answer correctness.
    # Approx Bedrock pricing per 1M tokens:
    #   - Haiku 4.5:  ~$1 in / ~$5 out
    #   - Sonnet 4.5: ~$3 in / ~$15 out
    # Override any of the three via env vars to flip everything to the
    # same model, or to bump to Sonnet 4.6 / Opus when those land in EU.
    llm_model_orchestrator_bedrock: str = Field(
        default="eu.anthropic.claude-haiku-4-5-20251001-v1:0",
        validation_alias=AliasChoices(
            "BEDROCK_MODEL_ORCHESTRATOR", "llm_model_orchestrator_bedrock"
        ),
    )
    llm_model_specialist_bedrock: str = Field(
        default="eu.anthropic.claude-sonnet-4-5-20250929-v1:0",
        validation_alias=AliasChoices(
            "BEDROCK_MODEL_SPECIALIST", "llm_model_specialist_bedrock"
        ),
    )
    llm_model_formatter_bedrock: str = Field(
        default="eu.anthropic.claude-haiku-4-5-20251001-v1:0",
        validation_alias=AliasChoices(
            "BEDROCK_MODEL_FORMATTER", "llm_model_formatter_bedrock"
        ),
    )

    # ===== EMBEDDING CONFIGURATION =====
    # Provider is independent of AI_PROVIDER — chat can stay on the
    # mantle proxy while embeddings go straight to Bedrock via boto3.
    # Resolution order:
    #   1. Explicit EMBEDDING_PROVIDER env var (ollama|openai|bedrock)
    #   2. Derived from AI_PROVIDER in the model_validator below
    embedding_provider: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("EMBEDDING_PROVIDER", "embedding_provider"),
    )
    # Bedrock Titan v2 default — 1024 dims, multilingual, accepts the
    # OpenAI-compatible "dimensions" parameter for truncation. Switch
    # to amazon.titan-embed-text-v1 (1536) or cohere.embed-multilingual-v3
    # (1024) via env if needed.
    embedding_model_bedrock: str = Field(
        default="amazon.titan-embed-text-v2:0",
        validation_alias=AliasChoices(
            "BEDROCK_EMBEDDING_MODEL", "embedding_model_bedrock"
        ),
    )
    # Pgvector column dimension. Must match the active embedding model:
    #   - Titan v2:    256 / 512 / 1024
    #   - Cohere v3:   1024 (fixed)
    #   - Ollama mxbai-embed-large: 1024
    #   - OpenAI text-embedding-3-large: any via dimensions param (we use 1024)
    embedding_dim: int = Field(
        default=1024,
        validation_alias=AliasChoices("EMBEDDING_DIM", "embedding_dim"),
    )
    # OpenAI embedding model. Override via EMBEDDING_MODEL env var.
    # Bedrock uses embedding_model_bedrock instead.
    embedding_model: str = Field(
        default="text-embedding-3-large",
        validation_alias=AliasChoices("EMBEDDING_MODEL", "embedding_model"),
    )

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

    # User identity for AI→BE service-to-service calls. The token used to
    # be hardcoded to a UUID that wasn't in the seed DB, so every call
    # 401'd silently and Knowledge specialists saw an empty catalog.
    # Configure via AI_SERVICE_USER_ID / AI_SERVICE_USER_EMAIL in .env.
    ai_service_user_id: str = Field(
        default="",
        validation_alias=AliasChoices("AI_SERVICE_USER_ID", "ai_service_user_id"),
        description="User UUID the AI service impersonates when calling backend.",
    )
    ai_service_user_email: str = Field(
        default="",
        validation_alias=AliasChoices("AI_SERVICE_USER_EMAIL", "ai_service_user_email"),
        description="Email claim that pairs with ai_service_user_id.",
    )

    # Self-URL for Celery-→-AI internal scan calls (item 23).
    ai_service_url: str = Field(
        default="http://localhost:8001",
        validation_alias=AliasChoices("AI_SERVICE_URL", "ai_service_url"),
        description="Base URL of this AI service (used by Celery scan tasks to call /query).",
    )

    # Minimum answer length (chars) for a scan insight to be considered non-silent (item 26).
    scan_min_insight_length: int = Field(
        default=120,
        validation_alias=AliasChoices(
            "SCAN_MIN_INSIGHT_LENGTH", "scan_min_insight_length"
        ),
        description="Answer shorter than this is treated as a silent run — not saved, not notified.",
    )

    # Demo connections — shared across all demo users (staging + prod).
    # Embeddings for these connections are stored with space_id=NULL so
    # every demo visitor can query them without a per-user seed.
    # Value: comma-separated UUIDs, same as DEMO_DATASET_CONNECTION_IDS
    # in sky-poc-backend's .env.
    demo_dataset_connection_ids: str = Field(
        default="",
        validation_alias=AliasChoices(
            "DEMO_DATASET_CONNECTION_IDS", "demo_dataset_connection_ids"
        ),
        description="Comma-separated UUIDs of demo connections whose embeddings are shared (space_id=NULL).",
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

    # Langfuse — LLM observability
    langfuse_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("LANGFUSE_ENABLED", "langfuse_enabled"),
    )
    langfuse_public_key: str = Field(
        default="",
        validation_alias=AliasChoices("LANGFUSE_PUBLIC_KEY", "langfuse_public_key"),
    )
    langfuse_secret_key: str = Field(
        default="",
        validation_alias=AliasChoices("LANGFUSE_SECRET_KEY", "langfuse_secret_key"),
    )
    langfuse_host: str = Field(
        default="http://localhost:3001",
        validation_alias=AliasChoices("LANGFUSE_HOST", "langfuse_host"),
    )

    # Bootstrap suggestions
    bootstrap_variation_window_seconds: int = (
        300  # Frequência de variação das sugestões (5 minutos)
    )

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
        extra = "ignore"

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
            self.database_url = f"postgresql+psycopg2://{self.postgres_user}:{pw}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

        # Celery URLs: se vazio mas temos REDIS_PASSWORD, construir iguais ao infra (mesma família de URLs)
        if (
            not self.celery_broker_url or not self.celery_result_backend
        ) and self.redis_password:
            # NOTE: redis password pode ter chars especiais; encode mínimo
            rp = quote_plus(self.redis_password)
            # Usar redis host/port padrão do compose (redis:6379) quando rodando em containers
            # Em local, o usuário pode setar CELERY_* explicitamente.
            self.celery_broker_url = (
                self.celery_broker_url or f"redis://:{rp}@redis:6379/1"
            )
            self.celery_result_backend = (
                self.celery_result_backend or f"redis://:{rp}@redis:6379/2"
            )

        # AI Provider Logic
        # Sets the (use_local_models, use_bedrock) tuple from AI_PROVIDER
        # and derives the embedding provider if not explicitly set.
        provider = self.ai_provider.lower()
        if provider == "openai":
            self.use_local_models = False
            self.use_bedrock = False
        elif provider == "ollama":
            self.use_local_models = True
            self.use_bedrock = False
        elif provider == "bedrock":
            self.use_local_models = False
            self.use_bedrock = True

        # Embedding provider — explicit EMBEDDING_PROVIDER wins, else
        # mirror AI_PROVIDER. Keeps existing deployments working without
        # an env change.
        if not self.embedding_provider:
            self.embedding_provider = provider

        return self


settings = Settings()
