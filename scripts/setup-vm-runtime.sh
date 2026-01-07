#!/bin/bash
set -eo pipefail

echo '=========================================='
echo '🚀 Configurando e Iniciando Ambiente na VM'
echo '=========================================='
echo ''

# 1. Detectar Diretório do Projeto
BASE="/home/azureuser/projeto"
INFRA_DIR=""

if [ -d "${BASE}/sky-poc-infra" ]; then
  INFRA_DIR="${BASE}/sky-poc-infra"
elif [ -d "${BASE}/poc-deploy" ]; then
  INFRA_DIR="${BASE}/poc-deploy"
else
  echo '⚠️  Diretório de infraestrutura não encontrado - tentando clonar repositórios...'
  echo ''
  
  mkdir -p "$BASE" || { echo "❌ ERRO: Falha ao criar diretório $BASE"; exit 1; }
  chown -R azureuser:azureuser "$BASE" 2>/dev/null || true
  cd "$BASE" || { echo "❌ ERRO: Não foi possível entrar no diretório $BASE"; exit 1; }
  
  # Usar token se fornecido
  if [ -n "$GITHUB_TOKEN" ]; then
    AUTH_REPO_URL="https://x-access-token:${GITHUB_TOKEN}@github.com"
  else
    AUTH_REPO_URL="https://github.com"
  fi
  
  # Extrair owner se REPO for fornecido (ex: sky-first/sky-poc-infra)
  REPO_OWNER=${REPO%%/*}
  
  echo "📥 Clonando repositórios (branch: ${BRANCH})..."
  git clone -b "${BRANCH}" "${AUTH_REPO_URL}/${REPO}.git" sky-poc-infra || { echo "❌ Erro ao clonar sky-poc-infra"; exit 1; }
  
  INFRA_DIR="${BASE}/sky-poc-infra"
fi

echo "✅ Diretório de infra: ${INFRA_DIR}"
cd "${INFRA_DIR}" || { echo '❌ ERRO: Não foi possível entrar no diretório'; exit 1; }

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
    exit 1
  fi
fi

# 3. Injeção de Segredos
echo ''
echo '🔐 Injetando variáveis de ambiente...'
ensure_kv() {
  key="$1"; val="$2"
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
  echo '✅ OPENAI_API_KEY injetada'
fi

chmod 600 .env

# 4. Validar Caminhos para Docker Compose
echo ''
echo '📂 Validando caminhos...'
for dir in "../sky-poc-backend" "../sky-poc-frontend" "../sky-poc-ai"; do
  if [ ! -d "$dir" ]; then
    echo "⚠️  AVISO: Diretório dependente não encontrado: $dir"
  fi
done

# 5. Reiniciar Containers
echo ''
echo '🚀 Iniciando containers...'

if command -v docker-compose >/dev/null 2>&1; then
  DOCKER_CMD="docker-compose"
else
  DOCKER_CMD="docker compose"
fi

# Parar containers (cleanup)
$DOCKER_CMD down || true

# Iniciar containers
if ! $DOCKER_CMD up -d --build; then
  echo '❌ ERRO: Falha ao iniciar containers'
  $DOCKER_CMD ps || true
  $DOCKER_CMD logs --tail=50 || true
  exit 1
fi

echo '⏳ Aguardando containers estabilizarem (30s)...'
sleep 30

# 6. Validação de Saúde
echo ''
echo '🏥 Verificando saúde dos serviços...'
$DOCKER_CMD ps

# Verificar containers críticos
for container in ai_saas_postgres_prod ai_saas_redis_prod ai_saas_backend_prod ai_saas_proxy; do
  if ! docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
    echo "❌ ERRO: Container crítico não está rodando: ${container}"
    docker ps -a --filter "name=${container}" --format 'table {{.Names}}\t{{.Status}}\t{{.ExitCode}}'
    docker logs "${container}" --tail=30 2>/dev/null || true
    exit 1
  fi
done

# Health check HTTP local
echo '🏥 Testando health check local (curl http://localhost/health)...'
MAX_RETRIES=10
RETRY_DELAY=5
HEALTH_OK=false

for i in $(seq 1 $MAX_RETRIES); do
  HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://localhost/health 2>/dev/null || echo '000')
  if [ "$HTTP_CODE" = '200' ]; then
    echo "✅ Health check OK (HTTP $HTTP_CODE)"
    HEALTH_OK=true
    break
  else
    echo "⏳ Health check tentiva $i/$MAX_RETRIES: HTTP $HTTP_CODE"
    sleep $RETRY_DELAY
  fi
done

if [ "$HEALTH_OK" != "true" ]; then
  echo "❌ ERRO: Health check falhou após $MAX_RETRIES tentativas"
  $DOCKER_CMD ps
  $DOCKER_CMD logs --tail=20 proxy 2>/dev/null || true
  $DOCKER_CMD logs --tail=20 backend 2>/dev/null || true
  exit 1
fi

echo ''
echo '✅ Deploy na VM concluído com SUCESSO!'
echo '=========================================='
