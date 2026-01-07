#!/bin/bash
# setup-vm-runtime.sh - Refactored script for VM maintenance
# Handles .env bootstrap, IP updates, secret injection, and container restart with health checks.
# Version: 1.0.4 (Stabilization: robust paths, sudo management, and checklist logging)

set -eo pipefail

echo "=========================================="
echo "🚀 VM RUNTIME SETUP & MAINTENANCE (v1.0.4)"
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
  if grep -q "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=${val}|" .env
  else
    printf "%s=%s\n" "$key" "$val" >> .env
  fi
}

if [ -n "$OPENAI_API_KEY_BOOTSTRAP" ]; then
  ensure_kv "OPENAI_API_KEY" "$OPENAI_API_KEY_BOOTSTRAP"
  ensure_kv "AI_SERVICE_URL" "http://ai:8001"
  ensure_kv "AI_SERVICE_TYPE" "real"
  echo '✅ OPENAI_API_KEY configurada'
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
