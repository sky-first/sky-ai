# DevOps: Configuração Centralizada - Single Source of Truth

## 📋 Visão Geral

Este documento descreve a abordagem DevOps de **centralização de configuração** implementada neste projeto. Todas as configurações de URLs, IPs e caminhos são gerenciadas no repositório de infraestrutura (`sky-poc-infra`), seguindo o princípio de **Single Source of Truth**.

## 🎯 Princípios

### 1. Single Source of Truth (SSOT)
- **Todas as configurações** vêm do arquivo `.env` gerenciado pelo DevOps
- Backend e Frontend **nunca** têm URLs hardcoded
- O repositório de infraestrutura é a **única fonte** de verdade

### 2. Separação de Responsabilidades
- **DevOps (sky-poc-infra)**: Gerencia todas as configurações
- **Backend (sky-poc-backend)**: Apenas lê variáveis de ambiente
- **Frontend (sky-poc-frontend)**: Apenas lê variáveis de ambiente

### 3. Configuração Automática
- Scripts de deploy **atualizam automaticamente** o `.env` com IPs corretos
- Validação automática durante o deploy
- Correção automática de problemas comuns

## 📁 Estrutura de Configuração

```
sky-poc-infra/                    ← DevOps controla TUDO aqui
├── .env                          ← Única fonte de verdade (gerado no deploy)
├── env.example                   ← Template com documentação
└── scripts/
    └── azure/
        ├── ensure-complete-env.sh              ← Garante .env completo
        ├── fix-next-public-api-url.sh          ← Corrige NEXT_PUBLIC_API_URL
        └── diagnose-frontend-backend-error.sh   ← Diagnóstico de erros

sky-poc-backend/                  ← Apenas lê do .env
└── src/
    └── config.py                 ← process.env['DATABASE_URL'] (sem defaults hardcoded)

sky-poc-frontend/                 ← Apenas lê do .env
└── src/
    └── lib/
        └── api.ts                ← process.env.NEXT_PUBLIC_API_URL (sem defaults hardcoded)
```

## 🔧 Variáveis Críticas

### NEXT_PUBLIC_API_URL

**Propósito**: URL que o frontend usa para chamar o backend

**Opções de Configuração**:

1. **Path Relativo (RECOMENDADO)**:
   ```
   NEXT_PUBLIC_API_URL=/api/v1
   ```
   - ✅ Funciona através do Nginx, independente do IP
   - ✅ Evita problemas de CORS e mixed-content
   - ✅ Funciona em qualquer ambiente (dev, staging, prod)

2. **URL Completa com IP Público**:
   ```
   NEXT_PUBLIC_API_URL=http://20.86.142.1/api/v1
   ```
   - ⚠️ Depende do IP da VM
   - ⚠️ Precisa ser atualizado se o IP mudar
   - ✅ Útil quando precisa de URL absoluta

**❌ NUNCA USE**:
- `http://localhost:8000/api/v1` (não funciona em containers Docker)
- `http://127.0.0.1:8000/api/v1` (não funciona em containers Docker)
- URLs hardcoded no código do frontend

### CORS_ORIGINS

**Propósito**: Origens permitidas para requisições CORS

**Formato**:
```
CORS_ORIGINS=http://20.86.142.1,http://20.86.142.1:3000,http://localhost:3000,http://localhost
```

**❌ NUNCA USE**:
- `*` (permite qualquer origem - vulnerabilidade de segurança)
- `0.0.0.0` (não é uma origem válida)

## 🚀 Scripts de Deploy

### ensure-complete-env.sh

**Propósito**: Garante que o `.env` tenha todas as variáveis necessárias

**O que faz**:
- Cria `.env` a partir de `env.example` se não existir
- Gera senhas seguras automaticamente
- Detecta e corrige problemas comuns (ex: localhost:8000)
- Atualiza `NEXT_PUBLIC_API_URL` automaticamente

**Uso**:
```bash
./scripts/azure/ensure-complete-env.sh [PROJECT_DIR]
```

### fix-next-public-api-url.sh

**Propósito**: Corrige especificamente o `NEXT_PUBLIC_API_URL`

**O que faz**:
- Detecta problemas (localhost:8000, IP desatualizado, etc.)
- Corrige automaticamente
- Prefere path relativo por padrão

**Uso**:
```bash
# Preferir path relativo (recomendado)
./scripts/azure/fix-next-public-api-url.sh [PROJECT_DIR] true

# Usar IP completo
./scripts/azure/fix-next-public-api-url.sh [PROJECT_DIR] false
```

### diagnose-frontend-backend-error.sh

**Propósito**: Diagnóstico específico para erro "Failed to load data. Please check if the backend is running on port 8000"

**O que faz**:
- Verifica containers Docker
- Verifica `NEXT_PUBLIC_API_URL`
- Testa conectividade backend
- Verifica CORS
- Analisa logs do frontend
- Aplica correções automáticas quando possível

**Uso**:
```bash
./scripts/azure/diagnose-frontend-backend-error.sh [PROJECT_DIR]
```

## 🔄 Fluxo de Deploy

### 1. Deploy Automático (GitHub Actions)

```
1. Terraform cria/atualiza infraestrutura
2. Scripts clonam/atualizam repositórios
3. ensure-complete-env.sh garante .env completo
4. fix-next-public-api-url.sh corrige URLs se necessário
5. Docker Compose sobe containers
6. Frontend lê NEXT_PUBLIC_API_URL do .env
7. Backend lê variáveis do .env via Docker Compose
```

### 2. Deploy Manual

```bash
# 1. Garantir .env completo
./scripts/azure/ensure-complete-env.sh

# 2. Corrigir NEXT_PUBLIC_API_URL se necessário
./scripts/azure/fix-next-public-api-url.sh

# 3. Subir containers
docker compose up -d --build

# 4. Se houver erro, diagnosticar
./scripts/azure/diagnose-frontend-backend-error.sh
```

## 🐛 Resolução de Problemas

### Erro: "Failed to load data. Please check if the backend is running on port 8000"

**Causas Comuns**:
1. `NEXT_PUBLIC_API_URL` usando `localhost:8000`
2. `NEXT_PUBLIC_API_URL` não configurado
3. IP desatualizado no `.env`
4. Frontend não foi reiniciado após mudanças

**Solução**:
```bash
# 1. Diagnosticar
./scripts/azure/diagnose-frontend-backend-error.sh

# 2. Corrigir automaticamente
./scripts/azure/fix-next-public-api-url.sh

# 3. Reiniciar frontend
docker compose restart frontend
```

### Erro: CORS bloqueando requisições

**Causas**:
1. `CORS_ORIGINS` não inclui a origem do frontend
2. `CORS_ORIGINS` usando `*` (não permitido)

**Solução**:
```bash
# Verificar CORS_ORIGINS no .env
grep CORS_ORIGINS .env

# Atualizar se necessário (incluir IP da VM)
# CORS_ORIGINS=http://20.86.142.1,http://20.86.142.1:3000,http://localhost:3000
```

## ✅ Checklist de Validação

Antes de considerar o deploy completo, verifique:

- [ ] `.env` existe e tem todas as variáveis obrigatórias
- [ ] `NEXT_PUBLIC_API_URL` não usa `localhost:8000`
- [ ] `NEXT_PUBLIC_API_URL` está configurado (path relativo ou IP correto)
- [ ] `CORS_ORIGINS` não contém `*`
- [ ] `CORS_ORIGINS` inclui o IP da VM
- [ ] Containers estão rodando (backend, frontend, proxy)
- [ ] Backend responde em `/api/v1/health`
- [ ] Frontend consegue acessar o backend (sem erros no console)

## 📚 Referências

- [12 Factor App - Config](https://12factor.net/config)
- [Next.js Environment Variables](https://nextjs.org/docs/basic-features/environment-variables)
- [Docker Compose Environment Variables](https://docs.docker.com/compose/environment-variables/)

## 🔐 Segurança

### Boas Práticas

1. **Nunca commitar `.env`** no Git
2. **Usar `.env.example`** como template
3. **Gerar senhas seguras** automaticamente
4. **Validar CORS_ORIGINS** (nunca usar `*`)
5. **Rotacionar secrets** periodicamente

### Variáveis Sensíveis

As seguintes variáveis são **sensíveis** e nunca devem ser expostas:
- `POSTGRES_PASSWORD`
- `REDIS_PASSWORD`
- `JWT_SECRET_KEY`
- `ENCRYPTION_KEY`

## 📝 Manutenção

### Atualizar IP da VM

Se o IP da VM mudar:

```bash
# 1. Atualizar env.example (documentação)
# 2. Os scripts de deploy atualizam automaticamente o .env
# 3. Ou executar manualmente:
./scripts/azure/fix-next-public-api-url.sh
```

### Adicionar Nova Variável

1. Adicionar em `env.example` com documentação
2. Adicionar em `ensure-complete-env.sh` se necessário
3. Documentar no código do backend/frontend
4. Atualizar este documento

---

**Última atualização**: 2026-01-02  
**Mantido por**: Equipe DevOps

