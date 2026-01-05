# 🔧 Resolver Erro: Arquivo .env Não Existe na VM

## 🚨 Problema

O smoke test falha porque o arquivo `.env` não existe na VM, impedindo que os containers do Docker Compose iniciem.

**Sintomas:**
- ❌ Arquivo .env NÃO existe na VM
- ❌ Containers não iniciam
- ❌ Proxy/nginx não está rodando
- ❌ Porta 80 não responde
- ❌ Health check retorna 000 (timeout)

## ✅ PASSO A PASSO PARA RESOLVER O ERRO

### 🟢 PASSO 1 — Acessar a VM

Entre na VM onde o deploy foi feito:

```bash
ssh azureuser@172.172.134.36
```

(ajuste o usuário e IP conforme necessário)

### 🟢 PASSO 2 — Ir até o diretório do projeto

O pipeline usa `~/projeto/sky-poc-infra` ou `~/projeto/poc-deploy`:

```bash
cd ~/projeto

# Verificar qual diretório existe
if [ -d sky-poc-infra ]; then
  cd sky-poc-infra
elif [ -d poc-deploy ]; then
  cd poc-deploy
else
  echo "❌ Nenhum diretório encontrado!"
  echo "Diretórios disponíveis:"
  ls -la
  exit 1
fi

# Confirmar
ls
# Você deve ver: docker-compose.yml, env.example, scripts/, etc.
```

**Alternativa (buscar automaticamente):**
```bash
find ~ -name docker-compose.yml -type f 2>/dev/null | head -1
# Depois entre no diretório retornado
```

### 🟢 PASSO 3 — Criar o arquivo .env (PASSO MAIS IMPORTANTE)

**OPÇÃO 1: Copiar do env.example (RECOMENDADO)**

```bash
# Verificar se env.example existe
if [ -f env.example ]; then
  cp env.example .env
  echo "✅ .env criado a partir de env.example"
  echo "⚠️  IMPORTANTE: Configure as senhas no .env!"
  chmod 600 .env
else
  echo "❌ env.example não encontrado!"
  exit 1
fi
```

**OPÇÃO 2: Criar manualmente (se env.example não existir)**

```bash
nano .env
```

Cole o conteúdo mínimo necessário:

```bash
# Database
POSTGRES_USER=postgres
POSTGRES_PASSWORD=secure_password_here
POSTGRES_DB=ai_saas_db
POSTGRES_PORT=5433

# Redis
REDIS_PASSWORD=secure_redis_password_here
REDIS_PORT=6379

# Backend (CRÍTICO)
DATABASE_URL=postgresql+asyncpg://postgres:secure_password_here@postgres:5432/ai_saas_db
JWT_SECRET_KEY=generate_a_secure_random_string_here
ENCRYPTION_KEY=generate_another_secure_key_here
BACKEND_PORT=8000
DEBUG=false

# CORS (ajuste o IP para o IP da sua VM)
CORS_ORIGINS=http://172.172.134.36,http://172.172.134.36:3000,http://localhost:3000,http://localhost

# Frontend
FRONTEND_PORT=3000
NEXT_PUBLIC_API_URL=/api/v1

# AI Service
AI_SERVICE_TYPE=mock
AI_SERVICE_URL=http://ai:8001
OPENAI_API_KEY=

# Sentry (opcional)
SENTRY_DSN=
```

**Gerar senhas seguras (RECOMENDADO):**

```bash
# Gerar senhas seguras
echo "POSTGRES_PASSWORD=$(openssl rand -base64 32)"
echo "REDIS_PASSWORD=$(openssl rand -base64 32)"
echo "JWT_SECRET_KEY=$(openssl rand -base64 32)"
echo "ENCRYPTION_KEY=$(openssl rand -base64 32)"
```

Depois edite o `.env` e substitua os valores:

```bash
nano .env
# Substitua secure_password_here pelos valores gerados acima
```

**Definir permissões corretas:**

```bash
chmod 600 .env
```

👉 **Sem esse arquivo, nada funciona!**

### 🟢 PASSO 4 — Verificar Docker e Docker Compose

Execute:

```bash
sudo docker --version
sudo docker compose version
```

**Se o segundo comando falhar, instale:**

```bash
sudo apt update
sudo apt install -y docker-compose-plugin
```

### 🟢 PASSO 5 — Subir os containers

No diretório do docker-compose.yml:

```bash
sudo docker compose up -d
```

Aguarde alguns segundos (10-30s) para os containers iniciarem.

### 🟢 PASSO 6 — Verificar se os containers estão rodando

```bash
sudo docker ps
```

Você deve ver vários containers rodando, algo parecido com:

```
CONTAINER ID   IMAGE                    STATUS
xxx            ai_saas_postgres_prod    Up X seconds
xxx            redis:7-alpine           Up X seconds
xxx            ai_saas_backend_prod    Up X seconds
xxx            ai_saas_frontend_prod   Up X seconds
xxx            ai_saas_proxy_prod      Up X seconds
xxx            ai_saas_ai_prod         Up X seconds
```

**Verificar status detalhado:**

```bash
sudo docker compose ps
```

**⚠️ Se algum não estiver rodando:**

```bash
# Ver logs de todos os containers
sudo docker compose logs --tail=50

# Ver logs de um container específico
sudo docker compose logs --tail=50 [nome-do-container]

# Exemplos:
sudo docker compose logs --tail=50 backend
sudo docker compose logs --tail=50 proxy
sudo docker compose logs --tail=50 postgres
```

### 🟢 PASSO 7 — Testar o health manualmente

**Na própria VM (localhost):**

```bash
curl http://localhost/health
```

**De fora da VM (IP público):**

```bash
curl http://172.172.134.36/health
```

**Resposta esperada:**

```
HTTP/1.1 200 OK
{"status":"healthy"}
```

ou

```
HTTP/1.1 200 OK
```

**Se retornar 200, está funcionando! ✅**

### 🟢 PASSO 8 — Validar porta 80

Confira se o nginx/proxy está escutando:

```bash
sudo ss -tulnp | grep :80
```

**Se aparecer algo como `docker-proxy` ou `nginx`, está OK ✅**

**Alternativa (verificar dentro do container):**

```bash
sudo docker exec ai_saas_proxy_prod nginx -T | grep "listen.*80"
```

### 🟢 PASSO 9 — Rodar o smoke test novamente

Agora execute o smoke test (manual ou pipeline):

**Manual (na VM):**

```bash
cd ~/projeto/sky-poc-infra  # ou poc-deploy
./scripts/smoke-tests.sh 172.172.134.36 120
```

**Ou deixe o pipeline rodar de novo** (deve passar agora)

## 🚨 SE DER ERRO EM ALGUM PASSO

### 🔴 Containers não sobem

Rode sem `-d` para ver os erros:

```bash
sudo docker compose up
```

(sem `-d`) e copie o erro que aparecer

**Erros comuns:**
- `.env` não existe → Volte ao PASSO 3
- Variáveis faltando no `.env` → Verifique `env.example`
- Porta já em uso → `sudo docker compose down` e tente novamente

### 🔴 Backend não conecta no banco

Normalmente falta variável no `.env`, verifique:

```bash
# Verificar se DATABASE_URL está correto
grep DATABASE_URL .env

# Deve ser algo como:
# DATABASE_URL=postgresql+asyncpg://postgres:senha@postgres:5432/ai_saas_db
```

**Se faltar, adicione:**

```bash
DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER:-postgres}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB:-ai_saas_db}
```

### 🔴 Proxy não sobe

Verifique no docker-compose.yml:

```bash
# Verificar depends_on
grep -A 5 "proxy:" docker-compose.yml

# Verificar nome correto dos serviços
grep "container_name:" docker-compose.yml

# Verificar porta 80 exposta
grep -A 3 "ports:" docker-compose.yml | grep "80"
```

**Ver logs do proxy:**

```bash
sudo docker compose logs proxy
```

### 🔴 Health check retorna 404 ou 500

**404 (Not Found):**
- Rota `/health` não existe no backend
- Verifique logs do backend: `sudo docker compose logs backend`

**500 (Internal Server Error):**
- Backend não consegue conectar no banco
- Verifique `DATABASE_URL` no `.env`
- Verifique se postgres está rodando: `sudo docker compose ps postgres`

### 🔴 Porta 80 não responde

**Verificar NSG (Network Security Group) no Azure:**

```bash
# Se tiver Azure CLI instalado
az network nsg rule list \
  --resource-group rg-ai-saas-staging \
  --nsg-name <nome-do-nsg> \
  --query "[?destinationPortRange=='80']"
```

**Verificar firewall da VM:**

```bash
sudo ufw status
# ou
sudo iptables -L -n | grep 80
```

## ✅ Checklist Final

Antes de considerar resolvido, verifique:

- [ ] `.env` existe em `~/projeto/sky-poc-infra/.env` (ou `poc-deploy`)
- [ ] `.env` tem permissões 600: `chmod 600 .env`
- [ ] `.env` contém todas as variáveis obrigatórias:
  - [ ] `POSTGRES_PASSWORD`
  - [ ] `REDIS_PASSWORD`
  - [ ] `JWT_SECRET_KEY`
  - [ ] `ENCRYPTION_KEY`
  - [ ] `DATABASE_URL`
- [ ] Todos os containers estão rodando: `sudo docker ps` mostra 6 containers
- [ ] Health check retorna 200: `curl http://localhost/health`
- [ ] Porta 80 está escutando: `sudo ss -tulnp | grep :80`
- [ ] Smoke test passa: `./scripts/smoke-tests.sh <IP> 120`

## 📝 Notas Importantes

1. **Caminho correto:** O pipeline usa `~/projeto/sky-poc-infra` ou `~/projeto/poc-deploy`, **não** `/home/azureuser/ai-saas`

2. **Usar sudo:** Na VM, sempre use `sudo` com comandos docker:
   - `sudo docker compose up -d`
   - `sudo docker ps`
   - `sudo docker compose logs`

3. **Senhas seguras:** Use `openssl rand -base64 32` para gerar senhas seguras, não use valores como "postgres" ou "123456"

4. **Variáveis obrigatórias:** O `.env` deve ter pelo menos:
   - `POSTGRES_PASSWORD`
   - `REDIS_PASSWORD`
   - `JWT_SECRET_KEY`
   - `ENCRYPTION_KEY`
   - `DATABASE_URL`

5. **Permissões:** O `.env` deve ter permissões 600 (apenas leitura/escrita para o dono):
   ```bash
   chmod 600 .env
   ```

## 🔄 Prevenção Futura

O pipeline foi corrigido para **sempre criar o `.env`** automaticamente. Mas se o problema persistir:

1. Verifique se o step "Bootstrap .env from env.example" está executando
2. Verifique se o `env.example` existe no repositório
3. Verifique os logs do pipeline no GitHub Actions

## 📚 Referências

- [README-DEPLOY-VM.md](../scripts/README-DEPLOY-VM.md) - Guia completo de deploy
- [env.example](../env.example) - Template do arquivo .env
- [smoke-tests.sh](../scripts/smoke-tests.sh) - Script de validação pós-deploy

