#!/bin/bash
# setup-vm-runtime.sh - Refactored script for VM maintenance
# Handles .env bootstrap, IP updates, secret injection, and container restart with health checks.
# Version: 1.0.5 (Fixed: Expand database URLs with real values before Docker Compose)

set -eo pipefail

echo "=========================================="
echo "🚀 VM RUNTIME SETUP & MAINTENANCE (v1.0.5)"
echo "🕒 Started at: $(date)"
echo "=========================================="
echo ''

# 1. Detectar Diretório do Projeto
# Usar um caminho fixo e simples conforme sugestão do usuário para evitar erros de shell
BASE="/home/azureuser/projeto"
INFRA_DIR=""

echo "📁 Verificando diretório base: $BASE"
if [ ! -d "$BASE" ]; then
    echo "🏗️  Criando diretório base..."
    sudo mkdir -p "$BASE"
fi
sudo chown -R azureuser:azureuser "$BASE"

if [ -d "${BASE}/sky-poc-infra" ]; then
  INFRA_DIR="${BASE}/sky-poc-infra"
elif [ -d "${BASE}/poc-deploy" ]; then
  INFRA_DIR="${BASE}/poc-deploy"
else
  echo '⚠️  Diretório de infraestrutura não encontrado - tentando clonar repositórios...'
  cd "$BASE" || { echo "❌ ERRO: Não foi possível entrar no diretório $BASE"; exit 1; }
  
  if [ -n "$GITHUB_TOKEN" ]; then
    AUTH_REPO_URL="https://x-access-token:${GITHUB_TOKEN}@github.com"
  else
    AUTH_REPO_URL="https://github.com"
  fi
  
  echo "📥 Clonando repositório principal (branch: ${BRANCH})..."
  git clone -b "${BRANCH}" "${AUTH_REPO_URL}/${REPO}.git" sky-poc-infra || { echo "❌ Erro ao clonar sky-poc-infra"; exit 1; }
  
  INFRA_DIR="${BASE}/sky-poc-infra"
fi

echo "✅ Diretório de infra: ${INFRA_DIR}"
cd "${INFRA_DIR}" || { echo '❌ ERRO: Não foi possível entrar no diretório'; exit 1; }

# Garantir que o diretório é seguro para o git
git config --global --add safe.directory "${INFRA_DIR}" 2>/dev/null || true

# 2. Bootstrap .env
echo ''
echo '📝 Verificando arquivo .env...'
if [ ! -f .env ]; then
  if [ -f env.example ]; then
    echo '📝 Criando .env a partir de env.example...'
    cp env.example .env
    chmod 600 .env
  else
    echo '❌ ERRO: env.example não encontrado!'
    # Listar arquivos para diagnóstico
    ls -la
    exit 1
  fi
fi

# 3. Injeção de Segredos
echo ''
echo '🔐 Configurando variáveis de ambiente...'
ensure_kv() {
  local key="$1"; local val="$2"
  if [ -z "$val" ]; then return; fi
  
  # Usar escape para caracteres especiais no sed
  local escaped_val=$(echo "$val" | sed 's/[&/\]/\\&/g')
  
  if grep -q "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=${escaped_val}|" .env
  else
    echo "${key}=${val}" >> .env
  fi
}

# Injetar segredos passados via variáveis de ambiente
[ -n "$POSTGRES_PASSWORD" ] && { ensure_kv "POSTGRES_PASSWORD" "$POSTGRES_PASSWORD"; echo '✅ POSTGRES_PASSWORD configurada'; }
[ -n "$REDIS_PASSWORD" ] && { ensure_kv "REDIS_PASSWORD" "$REDIS_PASSWORD"; echo '✅ REDIS_PASSWORD configurada'; }
[ -n "$JWT_SECRET_KEY" ] && { ensure_kv "JWT_SECRET_KEY" "$JWT_SECRET_KEY"; echo '✅ JWT_SECRET_KEY configurada'; }
[ -n "$ENCRYPTION_KEY" ] && { ensure_kv "ENCRYPTION_KEY" "$ENCRYPTION_KEY"; echo '✅ ENCRYPTION_KEY configurada'; }
[ -n "$SENTRY_DSN" ] && { ensure_kv "SENTRY_DSN" "$SENTRY_DSN"; echo '✅ SENTRY_DSN configurada'; }

if [ -n "$OPENAI_API_KEY_BOOTSTRAP" ]; then
  ensure_kv "OPENAI_API_KEY" "$OPENAI_API_KEY_BOOTSTRAP"
  ensure_kv "AI_SERVICE_URL" "http://ai:8001"
  ensure_kv "AI_SERVICE_TYPE" "real"
  echo '✅ Configurações de IA prontas'
fi

# 4. Atualizar IPs no .env
if [ -n "$VM_IP" ]; then
  echo "🌐 Sincronizando IP da VM: $VM_IP"
  
  # CORS_ORIGINS
  CORS_VAL="http://$VM_IP,http://$VM_IP:3000,http://localhost:3000,http://localhost"
  ensure_kv "CORS_ORIGINS" "$CORS_VAL"
  
  # Caso o valor atual de NEXT_PUBLIC_API_URL contenha um IP placeholder ou URL absoluta
  if grep -q "NEXT_PUBLIC_API_URL=" .env; then
    # Se já tiver http, substitui o host. Se for relativo (/api/v1), mantém.
    if grep -q "NEXT_PUBLIC_API_URL=http://" .env; then
      sed -i "s|NEXT_PUBLIC_API_URL=http://[^/ ]*/api/v1|NEXT_PUBLIC_API_URL=http://$VM_IP/api/v1|g" .env
    fi
  fi
  
  echo '✅ Endereços IP sincronizados'
fi

# 4.5. Expandir URLs de banco de dados com valores reais
# CRÍTICO: Docker Compose não expande sintaxe ${VAR:-default} quando variáveis não estão definidas
# Precisamos expandir manualmente para garantir que as URLs estão completas antes do docker compose
echo ''
echo '🔧 Expandindo URLs de banco de dados com valores reais...'

# Função helper para ler valores do .env de forma segura
read_env_value() {
  local key="$1"
  local default="$2"
  local val=$(grep "^${key}=" .env 2>/dev/null | cut -d'=' -f2- | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | sed "s/^[\"']//;s/[\"']$//" || echo "")
  echo "${val:-$default}"
}

# Função para fazer URL-encoding de senhas com caracteres especiais
# CRÍTICO: Senhas podem conter caracteres que quebram URLs (como @, :, /, #, etc.)
url_encode_password() {
  local password="$1"
  # Usar Python para fazer URL-encoding seguro (disponível em todas as VMs Linux modernas)
  python3 -c "import urllib.parse; print(urllib.parse.quote('$password', safe=''))" 2>/dev/null || \
    echo "$password" | sed 's/:/%3A/g; s/@/%40/g; s/#/%23/g; s/\//%2F/g; s/\?/%3F/g; s/\[/%5B/g; s/\]/%5D/g; s/ /%20/g'
}

# Garantir que variáveis básicas existem (com valores padrão se necessário)
if ! grep -q "^POSTGRES_USER=" .env; then
  POSTGRES_USER_DEFAULT="${POSTGRES_USER:-postgres}"
  ensure_kv "POSTGRES_USER" "$POSTGRES_USER_DEFAULT"
  echo "✅ POSTGRES_USER configurada (padrão: $POSTGRES_USER_DEFAULT)"
fi

if ! grep -q "^POSTGRES_DB=" .env; then
  POSTGRES_DB_DEFAULT="${POSTGRES_DB:-ai_saas_db}"
  ensure_kv "POSTGRES_DB" "$POSTGRES_DB_DEFAULT"
  echo "✅ POSTGRES_DB configurada (padrão: $POSTGRES_DB_DEFAULT)"
fi

# Ler valores do .env (após garantir que existem)
POSTGRES_USER_VAL=$(read_env_value "POSTGRES_USER" "postgres")
POSTGRES_PASSWORD_VAL=$(read_env_value "POSTGRES_PASSWORD" "")
POSTGRES_DB_VAL=$(read_env_value "POSTGRES_DB" "ai_saas_db")

# Validar que temos senha (não pode estar vazia ou com valor padrão placeholder)
if [ -z "$POSTGRES_PASSWORD_VAL" ]; then
  echo '❌ ERRO: POSTGRES_PASSWORD não está configurada no .env!'
  echo '   Configure POSTGRES_PASSWORD antes de continuar.'
  echo '   Dica: A variável deve ser passada via ambiente ou configurada manualmente.'
  exit 1
fi

# Verificar se a senha não é um placeholder comum
if [[ "$POSTGRES_PASSWORD_VAL" =~ ^(secure_password_here|password|postgres|changeme|changeit)$ ]]; then
  echo "⚠️  AVISO: POSTGRES_PASSWORD parece ser um placeholder padrão: '${POSTGRES_PASSWORD_VAL:0:5}...'"
  echo "   Recomendamos usar uma senha forte em produção."
fi

# Validar valores básicos
if [ -z "$POSTGRES_USER_VAL" ]; then
  echo '❌ ERRO: POSTGRES_USER está vazio!'
  exit 1
fi

if [ -z "$POSTGRES_DB_VAL" ]; then
  echo '❌ ERRO: POSTGRES_DB está vazio!'
  exit 1
fi

# Construir URLs expandidas (asyncpg é o driver assíncrono usado pelo backend e AI)
# CRÍTICO: Senhas podem conter caracteres especiais que quebram URLs (@, :, /, #, etc.)
# Precisamos fazer URL-encoding da senha para garantir que a URL seja válida
POSTGRES_PASSWORD_ENCODED=$(url_encode_password "$POSTGRES_PASSWORD_VAL")
BACKEND_DB_URL="postgresql+asyncpg://${POSTGRES_USER_VAL}:${POSTGRES_PASSWORD_ENCODED}@postgres:5432/${POSTGRES_DB_VAL}"
AI_DB_URL="postgresql+asyncpg://${POSTGRES_USER_VAL}:${POSTGRES_PASSWORD_ENCODED}@postgres:5432/${POSTGRES_DB_VAL}"

# Atualizar URLs no .env (usando ensure_kv que já faz escape correto)
ensure_kv "BACKEND_DATABASE_URL" "$BACKEND_DB_URL"
ensure_kv "AI_DATABASE_URL" "$AI_DB_URL"

echo "✅ BACKEND_DATABASE_URL expandida (usuário: $POSTGRES_USER_VAL, DB: $POSTGRES_DB_VAL)"
echo "✅ AI_DATABASE_URL expandida (usuário: $POSTGRES_USER_VAL, DB: $POSTGRES_DB_VAL)"

# Validação final: verificar que as URLs foram escritas corretamente
if ! grep -q "^BACKEND_DATABASE_URL=postgresql" .env; then
  echo '❌ ERRO: Falha ao escrever BACKEND_DATABASE_URL no .env!'
  exit 1
fi

if ! grep -q "^AI_DATABASE_URL=postgresql" .env; then
  echo '❌ ERRO: Falha ao escrever AI_DATABASE_URL no .env!'
  exit 1
fi

chmod 600 .env

# 5. Validar Docker Compose e Dependências
echo ''
echo '📂 Validando ambiente Docker...'
if command -v docker-compose >/dev/null 2>&1; then
  DOCKER_CMD="docker-compose"
else
  DOCKER_CMD="docker compose"
fi

# Garantir que subdiretórios existem (clonados pelo script de atualização ou pelo setup-vm-runtime se falhou)
REPOS="sky-poc-backend sky-poc-frontend sky-poc-ai"
for dir in $REPOS; do
  if [ ! -d "../$dir" ]; then
    echo "⚠️  AVISO: Diretório não encontrado: ../$dir"
  fi
done

# 6. Reiniciar Containers
echo ''
echo '🚀 Reiniciando serviços via Docker Compose...'

# Garantir que nada está travando as portas
$DOCKER_CMD down || true

# Iniciar containers
if ! $DOCKER_CMD up -d --build; then
  echo '❌ ERRO: Falha ao iniciar containers'
  $DOCKER_CMD ps || true
  $DOCKER_CMD logs --tail=100 || true
  exit 1
fi

echo '⏳ Aguardando serviços estabilizarem (30s)...'
sleep 30

# 7. Verificação de Saúde
echo ''
echo '🏥 Checklist de Saúde:'

# A. Verificar se há containers rodando
RUNNING_COUNT=$(docker ps --format '{{.Names}}' | wc -l)
if [ "$RUNNING_COUNT" -gt 0 ]; then
  echo "✅ Containers rodando: $RUNNING_COUNT"
else
  echo "❌ ERRO: Nenhum container está rodando!"
  $DOCKER_CMD ps
  exit 1
fi

# B. Verificar containers críticos
CRITICAL="ai_saas_postgres_prod ai_saas_redis_prod ai_saas_backend_prod ai_saas_proxy"
for container in $CRITICAL; do
  if docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
    echo "✅ Container OK: $container"
  else
    echo "❌ FALHA: Container CRÍTICO offline: $container"
    docker ps -a --filter "name=${container}"
    exit 1
  fi
done

# C. Health check HTTP local
echo '🏥 Testando API Gateway (http://localhost/health)...'
MAX_RETRIES=5
RETRY_DELAY=5
HEALTH_OK=false

for i in $(seq 1 $MAX_RETRIES); do
  HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://localhost/health 2>/dev/null || echo '000')
  if [ "$HTTP_CODE" = '200' ]; then
    echo "✅ API Gateway respondendo (HTTP $HTTP_CODE)"
    HEALTH_OK=true
    break
  else
    echo "⏳ Tentativa $i/$MAX_RETRIES: HTTP $HTTP_CODE"
    if [ $i -lt $MAX_RETRIES ]; then sleep $RETRY_DELAY; fi
  fi
done

if [ "$HEALTH_OK" != "true" ]; then
  echo "❌ ERRO: API Gateway não respondeu com sucesso em $MAX_RETRIES tentativas"
  $DOCKER_CMD logs ai_saas_proxy --tail=20 2>/dev/null || true
  exit 1
fi

echo ''
echo '✅ OPERAÇÃO CONCLUÍDA COM SUCESSO!'
echo '=========================================='
