# DevOps: Configuração de Repositórios - Single Source of Truth

## 📋 Visão Geral

Este documento descreve como os repositórios **sky-poc-backend**, **sky-poc-frontend** e **sky-poc-ai** devem ser configurados para apontar para o deploy centralizado gerenciado pelo repositório de infraestrutura (`sky-poc-infra`).

## 🎯 Princípio Fundamental

**TODAS as configurações vêm do repositório de infraestrutura (`sky-poc-infra`).**

Os repositórios individuais (backend, frontend, AI) **NUNCA** devem ter:
- URLs hardcoded (localhost, IPs fixos)
- Valores padrão que assumem ambiente específico
- Configurações que dependem do ambiente de desenvolvimento local

## 📁 Estrutura de Configuração

```
sky-poc-infra/                    ← ÚNICA FONTE DE VERDADE
├── .env                          ← Configuração centralizada (gerado no deploy)
├── env.example                   ← Template com documentação
├── docker-compose.yml            ← Orquestração e injeção de variáveis
└── scripts/azure/                ← Scripts de deploy e validação
    ├── ensure-complete-env.sh
    ├── fix-next-public-api-url.sh
    └── diagnose-frontend-backend-error.sh

sky-poc-backend/                  ← Apenas lê variáveis de ambiente
├── src/config/settings.py        ← Usa Pydantic Settings (sem defaults hardcoded)
└── docker/Dockerfile             ← Não define variáveis de ambiente

sky-poc-frontend/                 ← Apenas lê variáveis de ambiente
├── src/lib/api/client.ts         ← Usa process.env.NEXT_PUBLIC_API_URL (sem fallback hardcoded)
└── docker/Dockerfile             ← Não define variáveis de ambiente

sky-poc-ai/                       ← Apenas lê variáveis de ambiente
├── config/settings.py            ← Usa Pydantic Settings (sem defaults hardcoded)
└── (sem Dockerfile próprio - usa do infra)
```

## 🔧 Configuração por Repositório

### 1. Frontend (sky-poc-frontend)

#### Variável Crítica: `NEXT_PUBLIC_API_URL`

**❌ ERRADO** (hardcoded):
```typescript
// src/lib/api/client.ts
export function getApiBaseUrl(): string {
  return env?.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1"  // ❌ FALLBACK HARDCODED
}
```

**✅ CORRETO** (sem fallback):
```typescript
// src/lib/api/client.ts
export function getApiBaseUrl(): string {
  const env = (globalThis as any)?.process?.env
  if (!env?.NEXT_PUBLIC_API_URL) {
    throw new Error("NEXT_PUBLIC_API_URL não está configurado. Configure no .env do sky-poc-infra")
  }
  return env.NEXT_PUBLIC_API_URL
}
```

**Ou melhor ainda** (com validação):
```typescript
// src/lib/api/client.ts
export function getApiBaseUrl(): string {
  const env = (globalThis as any)?.process?.env
  const apiUrl = env?.NEXT_PUBLIC_API_URL
  
  if (!apiUrl) {
    if (typeof window !== "undefined") {
      // No browser, tentar usar path relativo como fallback seguro
      return "/api/v1"
    }
    throw new Error("NEXT_PUBLIC_API_URL não está configurado")
  }
  
  return apiUrl
}
```

#### Onde é usado:
- `src/lib/api/client.ts` - Função `getApiBaseUrl()`
- `src/app/login/page.tsx` - Log de debug (deve usar a função centralizada)

#### Como é injetado:
No `docker-compose.yml` do `sky-poc-infra`:
```yaml
frontend:
  environment:
    NEXT_PUBLIC_API_URL: ${NEXT_PUBLIC_API_URL:-/api/v1}  # Path relativo recomendado
```

### 2. Backend (sky-poc-backend)

#### Variáveis Críticas:
- `DATABASE_URL` - Conexão com PostgreSQL
- `CORS_ORIGINS` - Origens permitidas para CORS
- `REDIS_URL` - Conexão com Redis
- `AI_SERVICE_URL` - URL do serviço AI (se aplicável)

**❌ ERRADO** (defaults hardcoded):
```python
# src/config/settings.py
CORS_ORIGINS: str = Field(
    default="http://localhost:3000,http://localhost:3001",  # ❌ DEFAULT HARDCODED
)
DATABASE_URL: str = Field(
    default="postgresql+asyncpg://postgres:postgres@localhost:5432/ai_saas_db",  # ❌ DEFAULT HARDCODED
)
```

**✅ CORRETO** (sem defaults ou defaults seguros):
```python
# src/config/settings.py
CORS_ORIGINS: str = Field(
    default="",  # ✅ VAZIO - obriga configuração explícita
    description="CORS allowed origins (comma-separated). DEVE ser configurado no .env do sky-poc-infra",
)
DATABASE_URL: str = Field(
    default="",  # ✅ VAZIO - obriga configuração explícita
    description="Database connection URL. DEVE ser configurado no .env do sky-poc-infra",
)
```

**Ou com validação**:
```python
# src/config/settings.py
@field_validator('CORS_ORIGINS')
def validate_cors_origins(cls, v):
    if not v or v.strip() == "":
        raise ValueError("CORS_ORIGINS deve ser configurado no .env do sky-poc-infra")
    if v == "*" or "0.0.0.0" in v:
        raise ValueError("CORS_ORIGINS não pode ser '*' ou conter '0.0.0.0' (vulnerabilidade de segurança)")
    return v
```

#### Como é injetado:
No `docker-compose.yml` do `sky-poc-infra`:
```yaml
backend:
  environment:
    DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER:-postgres}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB:-ai_saas_db}
    CORS_ORIGINS: ${CORS_ORIGINS:-http://localhost:3000}
    # ... outras variáveis
```

### 3. AI Service (sky-poc-ai)

#### Variáveis Críticas:
- `DATABASE_URL` - Conexão com PostgreSQL (compartilhado com backend)
- `OPENAI_API_KEY` - Chave da API OpenAI
- `CELERY_BROKER_URL` - URL do broker Celery (Redis)

**❌ ERRADO** (defaults hardcoded):
```python
# config/settings.py
database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/ai_saas_db"  # ❌ DEFAULT HARDCODED
celery_broker_url: str = "redis://localhost:6379/0"  # ❌ DEFAULT HARDCODED
```

**✅ CORRETO** (sem defaults):
```python
# config/settings.py
database_url: str = Field(
    default="",
    description="Database connection URL. DEVE ser configurado no .env do sky-poc-infra",
)
celery_broker_url: str = Field(
    default="",
    description="Celery broker URL. DEVE ser configurado no .env do sky-poc-infra",
)
```

## 🚀 Processo de Deploy

### 1. Preparação (no sky-poc-infra)

```bash
# 1. Garantir que .env está completo e correto
./scripts/azure/ensure-complete-env.sh

# 2. Validar configurações críticas
./scripts/azure/fix-next-public-api-url.sh . true  # Preferir path relativo

# 3. Verificar que não há problemas
./scripts/azure/diagnose-frontend-backend-error.sh
```

### 2. Build e Deploy

```bash
# No sky-poc-infra
docker compose build
docker compose up -d
```

### 3. Validação Pós-Deploy

```bash
# Verificar que containers estão rodando
docker compose ps

# Verificar logs
docker compose logs frontend | grep -i "NEXT_PUBLIC_API_URL"
docker compose logs backend | grep -i "CORS_ORIGINS"

# Testar conectividade
curl http://20.86.142.1/api/v1/health
```

## ✅ Checklist de Validação

### Frontend
- [ ] `src/lib/api/client.ts` não tem fallback hardcoded para `localhost:8000`
- [ ] `src/app/login/page.tsx` usa função centralizada (não log direto)
- [ ] `env.example` do frontend não tem valores de produção hardcoded
- [ ] Dockerfile do frontend não define `NEXT_PUBLIC_API_URL`

### Backend
- [ ] `src/config/settings.py` não tem defaults hardcoded de `localhost`
- [ ] Validação de `CORS_ORIGINS` rejeita `*` e `0.0.0.0`
- [ ] `DATABASE_URL` não tem default hardcoded
- [ ] Dockerfile do backend não define variáveis de ambiente

### AI Service
- [ ] `config/settings.py` não tem defaults hardcoded de `localhost`
- [ ] `DATABASE_URL` compartilhado com backend (mesma configuração)
- [ ] `CELERY_BROKER_URL` aponta para Redis configurado no infra

### Infraestrutura
- [ ] `.env` tem todas as variáveis necessárias
- [ ] `NEXT_PUBLIC_API_URL` está configurado (preferencialmente `/api/v1`)
- [ ] `CORS_ORIGINS` inclui IP da VM de produção
- [ ] Scripts de deploy atualizam automaticamente IPs

## 🔍 Diagnóstico de Problemas

### Erro: "Failed to load data. Please check if the backend is running on port 8000"

**Causa**: `NEXT_PUBLIC_API_URL` está usando `localhost:8000` ou não está configurado.

**Solução**:
```bash
# No sky-poc-infra
./scripts/azure/fix-next-public-api-url.sh . true
docker compose restart frontend
```

### Erro: CORS bloqueando requisições

**Causa**: `CORS_ORIGINS` não inclui a origem do frontend.

**Solução**:
```bash
# No sky-poc-infra/.env
CORS_ORIGINS=http://20.86.142.1,http://20.86.142.1:3000,http://localhost:3000,http://localhost

# Reiniciar backend
docker compose restart backend
```

### Erro: Backend não consegue conectar ao banco

**Causa**: `DATABASE_URL` está incorreto ou não está configurado.

**Solução**:
```bash
# Verificar .env
grep DATABASE_URL .env

# Deve ser algo como:
# DATABASE_URL=postgresql+asyncpg://postgres:senha@postgres:5432/ai_saas_db
```

## 📚 Referências

- [DEVOPS-CONFIGURACAO-CENTRALIZADA.md](./DEVOPS-CONFIGURACAO-CENTRALIZADA.md) - Princípios gerais
- [env.example](../env.example) - Template de configuração
- [docker-compose.yml](../docker-compose.yml) - Orquestração de containers

## 🎓 Boas Práticas

1. **Nunca hardcode URLs ou IPs** nos repositórios individuais
2. **Sempre use variáveis de ambiente** para configuração
3. **Valide configurações críticas** no código (rejeite valores inválidos)
4. **Documente dependências** de variáveis de ambiente
5. **Use path relativo** para `NEXT_PUBLIC_API_URL` quando possível (evita CORS)
6. **Teste localmente** com `.env.local` antes de fazer deploy
7. **Valide após deploy** que todas as configurações estão corretas

