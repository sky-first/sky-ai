#!/bin/bash
# Deploy sequencial com health checks
# Garante que containers iniciem na ordem correta e aguardem health checks

set -eu

PROJECT_DIR="${1:-/home/azureuser/projeto/sky-poc-infra}"
cd "$PROJECT_DIR" || {
    if [ -d ~/projeto/sky-poc-infra ]; then
        cd ~/projeto/sky-poc-infra
    elif [ -d ~/projeto/poc-deploy ]; then
        cd ~/projeto/poc-deploy
    else
        echo "❌ ERRO: Diretório do projeto não encontrado"
        exit 1
    fi
}

MAX_WAIT=300  # 5 minutos máximo por serviço
WAIT_INTERVAL=5

wait_for_healthy() {
    local service=$1
    local container_name=$2
    local check_cmd=$3
    
    echo "Aguardando $service ficar healthy..."
    local elapsed=0
    
    while [ $elapsed -lt $MAX_WAIT ]; do
        if eval "$check_cmd" > /dev/null 2>&1; then
            echo "✅ $service está healthy"
            return 0
        fi
        
        sleep $WAIT_INTERVAL
        elapsed=$((elapsed + WAIT_INTERVAL))
        echo "  Aguardando... (${elapsed}s/${MAX_WAIT}s)"
    done
    
    echo "❌ ERRO: $service não ficou healthy após ${MAX_WAIT}s"
    return 1
}

echo "=========================================="
echo "🚀 Deploy Sequencial com Health Checks"
echo "=========================================="
echo ""

# 1. Parar containers existentes
echo "1️⃣ Parando containers existentes..."
sudo docker compose down || echo "Nenhum container rodando"
echo ""

# 2. Garantir .env completo
echo "2️⃣ Garantindo .env completo..."
bash scripts/azure/ensure-complete-env.sh "$PROJECT_DIR" || {
    echo "❌ ERRO: Falha ao garantir .env completo"
    exit 1
}
echo ""

# 3. Corrigir docker-compose.yml
echo "3️⃣ Corrigindo docker-compose.yml..."
bash scripts/azure/fix-docker-compose.sh "$PROJECT_DIR" || {
    echo "❌ ERRO: Falha ao corrigir docker-compose.yml"
    exit 1
}
echo ""

# 4. Aplicar configuração do nginx
echo "4️⃣ Configurando nginx..."
bash scripts/azure/apply-nginx-config.sh "$PROJECT_DIR" || {
    echo "❌ ERRO: Falha ao configurar nginx"
    exit 1
}
echo ""

# 5. Iniciar Postgres
echo "5️⃣ Iniciando PostgreSQL..."
sudo docker compose up -d postgres || {
    echo "❌ ERRO: Falha ao iniciar PostgreSQL"
    exit 1
}
wait_for_healthy "PostgreSQL" "ai_saas_postgres_prod" "sudo docker exec ai_saas_postgres_prod pg_isready -U postgres"
echo ""

# 6. Iniciar Redis
echo "6️⃣ Iniciando Redis..."
sudo docker compose up -d redis || {
    echo "❌ ERRO: Falha ao iniciar Redis"
    exit 1
}
wait_for_healthy "Redis" "ai_saas_redis_prod" "sudo docker exec ai_saas_redis_prod redis-cli ping | grep -q PONG"
echo ""

# 7. Executar migrações (se existir serviço migrate)
if grep -q "^  migrate:" docker-compose.yml; then
    echo "7️⃣ Executando migrações..."
    sudo docker compose up migrate || {
        echo "⚠️  Migrações falharam (continuando...)"
    }
    echo ""
fi

# 8. Iniciar Backend
echo "8️⃣ Iniciando Backend..."
sudo docker compose up -d backend || {
    echo "❌ ERRO: Falha ao iniciar Backend"
    exit 1
}
wait_for_healthy "Backend" "ai_saas_backend_prod" "curl -f -s http://localhost:8000/health > /dev/null 2>&1 || curl -f -s http://localhost:8000/api/health > /dev/null 2>&1" || {
    echo "⚠️  Backend não respondeu ao health check (pode estar iniciando)"
    sleep 30
}
echo ""

# 9. Iniciar Worker e Beat
echo "9️⃣ Iniciando Worker e Beat..."
sudo docker compose up -d worker beat || {
    echo "⚠️  Worker/Beat falharam (não crítico)"
}
sleep 10
echo ""

# 10. Iniciar Frontend (se buildado)
if grep -q "^  frontend:" docker-compose.yml; then
    echo "🔟 Iniciando Frontend..."
    sudo docker compose up -d frontend || {
        echo "⚠️  Frontend falhou (pode ser erro de build)"
    }
    sleep 15
    echo ""
fi

# 11. Iniciar Proxy
echo "1️⃣1️⃣ Iniciando Proxy/Nginx..."
sudo docker compose up -d proxy || {
    echo "❌ ERRO: Falha ao iniciar Proxy"
    exit 1
}
sleep 5
wait_for_healthy "Proxy" "ai_saas_proxy" "curl -f -s http://localhost/health > /dev/null 2>&1 || curl -f -s http://localhost > /dev/null 2>&1" || {
    echo "⚠️  Proxy não respondeu (verificando logs...)"
    sudo docker compose logs proxy --tail=20
}
echo ""

# 12. Status final
echo "=========================================="
echo "📊 Status Final dos Containers"
echo "=========================================="
sudo docker compose ps
echo ""

# 13. Verificar porta 80
echo "=========================================="
echo "🔍 Verificando Porta 80"
echo "=========================================="
if sudo ss -tlnp | grep -q ":80 " || sudo netstat -tlnp 2>/dev/null | grep -q ":80 "; then
    echo "✅ Porta 80 está escutando"
else
    echo "❌ ERRO: Porta 80 não está escutando"
    exit 1
fi
echo ""

echo "=========================================="
echo "✅ Deploy Sequencial Concluído"
echo "=========================================="

