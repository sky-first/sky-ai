#!/bin/bash
# Deploy sequencial com health checks
# Garante que containers iniciem na ordem correta e aguardem health checks

set -eu

PROJECT_DIR="${1:-/home/azureuser/projeto/sky-poc-infra}"
# Usar caminho absoluto para garantir que funciona
if [ ! -d "$PROJECT_DIR" ]; then
    if [ -d "/home/azureuser/projeto/sky-poc-infra" ]; then
        PROJECT_DIR="/home/azureuser/projeto/sky-poc-infra"
    elif [ -d "/home/azureuser/projeto/poc-deploy" ]; then
        PROJECT_DIR="/home/azureuser/projeto/poc-deploy"
    else
        echo "[ERROR] ERRO: Diretório do projeto não encontrado"
        echo "   Procurou em: $PROJECT_DIR"
        echo "   E em: /home/azureuser/projeto/sky-poc-infra"
        echo "   E em: /home/azureuser/projeto/poc-deploy"
        exit 1
    fi
fi

cd "$PROJECT_DIR" || {
    echo "[ERROR] ERRO: Não foi possível entrar no diretório: $PROJECT_DIR"
    exit 1
}

echo " Diretório do projeto: $(pwd)"

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
            echo "[OK] $service está healthy"
            return 0
        fi
        
        sleep $WAIT_INTERVAL
        elapsed=$((elapsed + WAIT_INTERVAL))
        echo "  Aguardando... (${elapsed}s/${MAX_WAIT}s)"
    done
    
    echo "[ERROR] ERRO: $service não ficou healthy após ${MAX_WAIT}s"
    return 1
}

echo "=========================================="
echo " Deploy Sequencial com Health Checks"
echo "=========================================="
echo ""

# 1. Parar containers existentes
echo "1. Parando containers existentes..."
sudo docker compose down || echo "Nenhum container rodando"
echo ""

# 2. Garantir .env completo
echo "2. Garantindo .env completo..."
if [ -f scripts/azure/ensure-complete-env.sh ]; then
    bash scripts/azure/ensure-complete-env.sh "$PROJECT_DIR" || {
        echo "[WARNING] Aviso: Falha ao garantir .env completo (continuando...)"
    }
else
    echo "[WARNING] Script ensure-complete-env.sh não encontrado (continuando...)"
    if [ ! -f .env ] && [ -f env.example ]; then
        echo " Criando .env a partir de env.example..."
        cp env.example .env
        chmod 600 .env
    fi
fi
echo ""

# 3. Verificar docker-compose.yml
echo "3. Verificando docker-compose.yml..."
if [ ! -f docker-compose.yml ]; then
    echo "[ERROR] ERRO: docker-compose.yml não encontrado em $(pwd)"
    exit 1
fi
echo "[OK] docker-compose.yml encontrado"

# Corrigir docker-compose.yml se script existir
if [ -f scripts/azure/fix-docker-compose.sh ]; then
    bash scripts/azure/fix-docker-compose.sh "$PROJECT_DIR" || {
        echo "[WARNING] Aviso: Falha ao corrigir docker-compose.yml (continuando...)"
    }
fi
echo ""

# 4. Aplicar configuração do nginx
echo "4. Configurando nginx..."
if [ -f scripts/azure/apply-nginx-config.sh ]; then
    bash scripts/azure/apply-nginx-config.sh "$PROJECT_DIR" || {
        echo "[WARNING] Aviso: Falha ao configurar nginx (continuando...)"
    }
else
    echo "[WARNING] Script apply-nginx-config.sh não encontrado (continuando...)"
fi
echo ""

# 5. Iniciar Postgres
echo "5. Iniciando PostgreSQL..."
if ! sudo docker compose up -d postgres; then
    echo "[ERROR] ERRO: Falha ao iniciar PostgreSQL"
    echo "Logs do postgres:"
    sudo docker compose logs postgres --tail=30 2>/dev/null || true
    exit 1
fi

# Aguardar postgres ficar healthy
if ! wait_for_healthy "PostgreSQL" "ai_saas_postgres_prod" "sudo docker exec ai_saas_postgres_prod pg_isready -U postgres 2>/dev/null"; then
    echo "[ERROR] ERRO: PostgreSQL não ficou healthy"
    echo "Logs do postgres:"
    sudo docker compose logs postgres --tail=30 2>/dev/null || true
    exit 1
fi
echo ""

# 6. Iniciar Redis
echo "6. Iniciando Redis..."
if ! sudo docker compose up -d redis; then
    echo "[ERROR] ERRO: Falha ao iniciar Redis"
    echo "Logs do redis:"
    sudo docker compose logs redis --tail=30 2>/dev/null || true
    exit 1
fi

# Aguardar redis ficar healthy (usar REDIS_PASSWORD do .env se disponível)
REDIS_PASS=$(grep "^REDIS_PASSWORD=" .env 2>/dev/null | cut -d'=' -f2- || echo "")
if [ -n "$REDIS_PASS" ]; then
    REDIS_CHECK="sudo docker exec ai_saas_redis_prod redis-cli -a \"$REDIS_PASS\" ping 2>/dev/null | grep -q PONG"
else
    REDIS_CHECK="sudo docker exec ai_saas_redis_prod redis-cli ping 2>/dev/null | grep -q PONG"
fi

if ! wait_for_healthy "Redis" "ai_saas_redis_prod" "$REDIS_CHECK"; then
    echo "[ERROR] ERRO: Redis não ficou healthy"
    echo "Logs do redis:"
    sudo docker compose logs redis --tail=30 2>/dev/null || true
    exit 1
fi
echo ""

# 7. Executar migrações (se existir serviço migrate)
if grep -q "^  migrate:" docker-compose.yml; then
    echo "7. Executando migrações..."
    sudo docker compose up migrate || {
        echo "[WARNING] Migrações falharam (continuando...)"
    }
    echo ""
fi

# 7.5. Iniciar AI (se existir) - CRÍTICO: Backend depende do AI
if grep -q "^  ai:" docker-compose.yml; then
    echo "7..5. Iniciando AI Service..."
    if ! sudo docker compose up -d ai; then
        echo "[ERROR] ERRO: Falha ao iniciar AI Service"
        echo "Logs do ai:"
        sudo docker compose logs ai --tail=30 2>/dev/null || true
        exit 1
    fi
    
    # Aguardar AI ficar healthy (backend depende disso)
    echo "Aguardando AI Service ficar healthy..."
    if ! wait_for_healthy "AI Service" "ai_saas_ai_prod" "curl -f -s http://localhost:8001/health > /dev/null 2>&1"; then
        echo "[WARNING] AI Service não respondeu ao health check"
        echo "Logs do ai:"
        sudo docker compose logs ai --tail=30 2>/dev/null || true
        echo "Status do container:"
        sudo docker ps --filter "name=ai_saas_ai_prod" --format "table {{.Names}}\t{{.Status}}" || true
        # Não falhar aqui, pode estar iniciando ainda, mas backend vai esperar
    fi
    echo ""
fi

# 8. Iniciar Backend
echo "8. Iniciando Backend..."
if ! sudo docker compose up -d backend; then
    echo "[ERROR] ERRO: Falha ao iniciar Backend"
    echo "Logs do backend:"
    sudo docker compose logs backend --tail=30 2>/dev/null || true
    exit 1
fi

# Aguardar backend ficar healthy (com mais tentativas) - compatível POSIX
echo "Aguardando backend ficar healthy..."
sleep 15
i=1
while [ $i -le 12 ]; do
    if curl -f -s http://localhost:8000/health > /dev/null 2>&1 || curl -f -s http://localhost:8000/api/v1/health > /dev/null 2>&1; then
        echo "[OK] Backend está healthy (tentativa $i/12)"
        break
    fi
    if [ $i -eq 12 ]; then
        echo "[WARNING] Backend não respondeu ao health check após 12 tentativas"
        echo "Logs do backend:"
        sudo docker compose logs backend --tail=30 2>/dev/null || true
        echo "Status do container:"
        sudo docker ps --filter "name=ai_saas_backend_prod" --format "table {{.Names}}\t{{.Status}}" || true
        # Não falhar aqui, pode estar iniciando ainda
    else
        echo "  Aguardando backend... (tentativa $i/12)"
        sleep 5
    fi
    i=$((i + 1))
done
echo ""

# 9. Iniciar Worker e Beat
echo "9. Iniciando Worker e Beat..."
sudo docker compose up -d worker beat || {
    echo "[WARNING] Worker/Beat falharam (não crítico)"
}
sleep 10
echo ""

# 10. Iniciar Frontend (se buildado)
if grep -q "^  frontend:" docker-compose.yml; then
    echo " Iniciando Frontend..."
    if ! sudo docker compose up -d frontend; then
        echo "[ERROR] ERRO: Falha ao iniciar Frontend"
        echo "Logs do frontend:"
        sudo docker compose logs frontend --tail=30 2>/dev/null || true
        # Frontend não é crítico, continuar
        echo "[WARNING] Continuando sem frontend..."
    else
        echo "[OK] Frontend iniciado"
        sleep 15
    fi
    echo ""
fi

# 11. Iniciar Proxy
echo "1.1. Iniciando Proxy/Nginx..."
if ! sudo docker compose up -d proxy; then
    echo "[ERROR] ERRO: Falha ao iniciar Proxy"
    echo "Logs do proxy:"
    sudo docker compose logs proxy --tail=30 2>/dev/null || true
    exit 1
fi

sleep 10
echo "Aguardando proxy iniciar..."

# Verificar se proxy está rodando
if ! sudo docker ps | grep -q "ai_saas_proxy"; then
    echo "[ERROR] ERRO: Container proxy não está rodando"
    echo "Status dos containers:"
    sudo docker compose ps
    echo "Logs do proxy:"
    sudo docker compose logs proxy --tail=50 2>/dev/null || true
    exit 1
fi

# Tentar health check (mas não falhar se não responder ainda)
if ! wait_for_healthy "Proxy" "ai_saas_proxy" "curl -f -s http://localhost/health > /dev/null 2>&1 || curl -f -s http://localhost > /dev/null 2>&1"; then
    echo "[WARNING] Proxy não respondeu ao health check (verificando logs...)"
    sudo docker compose logs proxy --tail=30 2>/dev/null || true
    echo "Status do container proxy:"
    sudo docker ps --filter "name=ai_saas_proxy" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    # Não falhar aqui, pode estar iniciando ainda
fi
echo ""

# 12. Status final
echo "=========================================="
echo " Status Final dos Containers"
echo "=========================================="
sudo docker compose ps || {
    echo "[WARNING] docker compose ps falhou, tentando docker ps..."
    sudo docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
}
echo ""

# Verificar containers críticos
CRITICAL_CONTAINERS=("ai_saas_postgres_prod" "ai_saas_redis_prod" "ai_saas_backend_prod" "ai_saas_proxy")
MISSING_CONTAINERS=""
FAILED_CONTAINERS=""

for container in "${CRITICAL_CONTAINERS[@]}"; do
    if ! sudo docker ps --format "{{.Names}}" | grep -q "^${container}$"; then
        MISSING_CONTAINERS="${MISSING_CONTAINERS} ${container}"
        # Verificar se está parado com erro
        EXIT_CODE=$(sudo docker inspect "$container" --format='{{.State.ExitCode}}' 2>/dev/null || echo "unknown")
        if [ "$EXIT_CODE" != "0" ] && [ "$EXIT_CODE" != "unknown" ]; then
            FAILED_CONTAINERS="${FAILED_CONTAINERS} ${container}(exit:$EXIT_CODE)"
        fi
    fi
done

if [ -n "$MISSING_CONTAINERS" ]; then
    echo "[ERROR] ERRO: Containers críticos não estão rodando:$MISSING_CONTAINERS"
    if [ -n "$FAILED_CONTAINERS" ]; then
        echo "   Containers com erro:$FAILED_CONTAINERS"
    fi
    echo ""
    echo "Containers parados ou com erro:"
    sudo docker ps -a --filter "status=exited" --format "table {{.Names}}\t{{.Status}}\t{{.ExitCode}}" || true
    echo ""
    echo "Logs dos containers com problema:"
    for container in $MISSING_CONTAINERS; do
        echo "--- Logs de $container ---"
        sudo docker logs "$container" --tail=50 2>/dev/null || true
        echo ""
    done
    exit 1
fi

echo "[OK] Todos os containers críticos estão rodando"
echo ""

# 13. Verificar porta 80
echo "=========================================="
echo " Verificando Porta 80"
echo "=========================================="
if sudo ss -tlnp | grep -q ":80 " || sudo netstat -tlnp 2>/dev/null | grep -q ":80 "; then
    echo "[OK] Porta 80 está escutando"
else
    echo "[ERROR] ERRO: Porta 80 não está escutando"
    exit 1
fi
echo ""

echo "=========================================="
echo "[OK] Deploy Sequencial Concluído"
echo "=========================================="

