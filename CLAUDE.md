# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Development
python run_api.py           # Starts FastAPI on :8001

# Celery worker
celery -A worker.celery_app worker --loglevel=info

# Tests
pytest
pytest tests/path/to/test.py::test_name   # single test

# Linting
black src/ api/ core/ db/ config/
```

## What This Service Does

This is the AI engine for the Sky platform. It receives natural language questions from the backend and returns answers by:
1. Selecting the right data tables (Orchestrator LLM)
2. Generating and executing SQL (Specialist LLM)
3. Formatting the response (Formatter LLM)

It also generates dashboard layouts (Davinci agent) and bootstrap suggestions (Sherlock agent).

The service runs on port **8001**. The backend calls it via HTTP (`AI_SERVICE_URL`).

## Architecture

### Source Layout

```
api/
├── main.py                    # FastAPI app, startup (DB init, LangGraph pool)
├── dependencies.py            # Dependency injection (DB session, auth, providers)
├── schemas.py                 # Pydantic request/response models
└── routes/
    ├── connection_query.py    # Main query endpoint (largest file)
    ├── connection_discover.py # Data catalog / metadata refresh
    ├── agents.py              # Agent management
    ├── pipeline.py            # Pipeline orchestration
    ├── widget_titles.py       # Title suggestions
    └── knowledge_graph.py     # Relationship context

core/
├── agents/
│   ├── generic_sql_agent.py   # Main LangGraph agent definition
│   ├── davinci_dashboard_agent.py  # Dashboard generation agent
│   ├── factory.py             # Builds AgentConfig from DB metadata
│   └── checkpoint_manager.py  # LangGraph PostgreSQL checkpoints
├── llm/
│   ├── orchestrator.py        # Node 1: table selection
│   ├── specialist.py          # Node 2: SQL generation + execution
│   ├── formatter.py           # Node 3: natural language response
│   ├── providers.py           # OpenAI + Ollama provider implementations
│   ├── cache.py               # LRU inference cache (TTL=30min)
│   └── prompts/               # System prompts per node
├── data_sources/
│   ├── base.py                # Abstract interface (execute_sql, get_tables, etc.)
│   ├── bigquery_source.py
│   ├── sql_alchemy_source.py
│   ├── databricks_source.py
│   └── factory.py
├── rag/
│   ├── embeddings.py          # Ollama (nomic-embed-text) or OpenAI providers
│   ├── vector_store.py        # pgvector queries
│   ├── context_retrieval.py   # Top-K semantic search for table context
│   └── user_profiler.py       # Analyzes query history to prioritize tables
├── sql/
│   ├── validator_advanced.py  # Validates SQL before execution
│   ├── relationships.py       # Auto-detects JOIN conditions between tables
│   └── dialects.py            # POSTGRES, BIGQUERY, MYSQL, REDSHIFT
└── security/
    ├── audit.py               # Query audit logging (async flush thread)
    ├── rate_limiter_redis.py  # Per-user rate limiting
    └── security_config.py     # Row-level security (RLS) config

agent_registry/
├── loader.py                  # Loads agent definitions from YAML files
└── examples/
    ├── billing_default.yaml
    └── generic_space_default.yaml

db/
├── base.py                    # Async engine (asyncpg) + sync engine (psycopg2 for LangGraph)
├── session.py                 # AsyncSession factory
└── models.py                  # SQLAlchemy models (Space, Crew, DataConnection, TableMetadata, etc.)
```

### LangGraph Pipeline (3-Node)

```
Question
  ↓
[Node 1: Orchestrator]
  - RAG: embed question → pgvector search → retrieve table descriptions
  - Role-aware: admin/cfo/navigator/explorer profiles affect table prioritization
  - Output: chosen_tables (logical names), join_relationships, plan
  ↓
[Node 2: Specialist]
  - Generates SQL from question + table schemas
  - Validates SQL (syntax, table existence, no destructive ops)
  - Executes against real data source
  - Output: sql, data (rows), generated_title
  ↓
[Node 3: Formatter]
  - Formats data into natural language answer
  - Respects user locale (i18n)
  - Output: final answer string
```

Memory persists via **LangGraph PostgreSQL checkpoints** — each conversation thread maintains history across requests.

### Agent State

The `AgentState` TypedDict flows through all 3 nodes and carries: question, user context (user_id, space_id, crew_ids, platform_role, crew_role), RAG context, chat history, user preferences (creativity 0-100, length 0-100, response_format), chosen tables, SQL, data results, and final answer.

### Multi-Tenant Isolation

Access to data is scoped by `Space → Crew → User`. `TableMetadata` rows have a `crew_id` — agents only see tables where `crew_id IS NULL` (global) or `crew_id IN user.crew_ids`. Agent configs are built dynamically from DB metadata via `core/agents/factory.py`.

### LLM Providers

Controlled by `AI_PROVIDER` env var (`openai`, `ollama`, or `bedrock`):

| Role | OpenAI model | Ollama model | Bedrock model |
|---|---|---|---|
| Orchestrator | `gpt-4o-mini` | `qwen2.5-coder:32b` | `eu.anthropic.claude-sonnet-4-5-20250929-v1:0` |
| Specialist | `gpt-4o` | `qwen2.5-coder:32b` | `eu.anthropic.claude-sonnet-4-5-20250929-v1:0` |
| Embeddings | `text-embedding-3-large` | `nomic-embed-text` (768 dims) | _(falls back to OpenAI — Bedrock embeddings TBD)_ |

Ollama base URL: `https://ollama.skyfirstlabs.com` (configurable via `OLLAMA_BASE_URL`).

Bedrock region: `eu-west-1` (configurable via `BEDROCK_REGION`). Authentication on EKS is via IRSA — the `sky-eks-staging-bedrock` role is assumed automatically through the OIDC token mounted on the pod's ServiceAccount. No `AWS_ACCESS_KEY_ID` should be set when running on cluster.

### Semantic Cache

Queries are deduplicated using semantic similarity (crew-isolated). If a semantically equivalent question was asked recently, the cached answer is returned without hitting the LLM. Controlled by `ENABLE_INFERENCE_CACHE`.

### Key Endpoints

- `POST /connections/{id}/query` — Main query endpoint (language detect → RAG → orchestrator → specialist → formatter)
- `POST /connections/{id}/bootstrap` — Generate greeting + personalized suggestions (Sherlock agent, refreshes every 5min)
- `POST /connections/{id}/dashboard-plan` — Generate multi-widget dashboard (Davinci agent)
- `GET /connections/{id}/catalog` — List tables/columns
- `POST /connections/{id}/refresh` — Refresh metadata from data source
- `GET /health` — Health check

### Environment Variables

```bash
# LLM
AI_PROVIDER=ollama            # "openai" | "ollama" | "bedrock"
OPENAI_API_KEY=sk-...
OLLAMA_BASE_URL=https://ollama.skyfirstlabs.com
BEDROCK_REGION=eu-west-1      # only consumed when AI_PROVIDER=bedrock

# Models (Ollama)
LLM_MODEL_ORCHESTRATOR_LOCAL=phi3:medium
LLM_MODEL_SPECIALIST_LOCAL=phi3:medium
LLM_MODEL_EMBEDDING_LOCAL=nomic-embed-text

# Database
DATABASE_URL=postgresql+asyncpg://...

# Redis/Celery
CELERY_BROKER_URL=redis://...
REDIS_PASSWORD=...

# GCP (for BigQuery connections)
GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json

# Feature flags
ENABLE_INFERENCE_CACHE=true
MAX_QUERY_RESULTS=1000
QUERY_TIMEOUT_SECONDS=300
```
