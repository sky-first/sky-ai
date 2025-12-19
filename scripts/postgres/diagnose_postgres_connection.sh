#!/bin/bash

set -e

echo "Diagnóstico de Conexão PostgreSQL"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_status() {
    if [ $1 -eq 0 ]; then
        echo -e "${GREEN}OK${NC}: $2"
    else
        echo -e "${RED}ERRO${NC}: $2"
    fi
}

print_warning() {
    echo -e "${YELLOW}AVISO${NC}: $1"
}

if docker ps | grep -q ai_saas_postgres_prod; then
    print_status 0 "Container está rodando"
    CONTAINER_RUNNING=0
else
    print_status 1 "Container não está rodando"
    CONTAINER_RUNNING=1
fi

if sudo netstat -tlnp 2>/dev/null | grep -q ":5433" || sudo ss -tlnp 2>/dev/null | grep -q ":5433"; then
    print_status 0 "Porta 5433 está escutando"
    PORT_LISTENING=0
else
    print_status 1 "Porta 5433 não está escutando"
    PORT_LISTENING=1
fi

if [ $CONTAINER_RUNNING -eq 0 ]; then
    LISTEN_ADDR=$(docker exec ai_saas_postgres_prod sh -c "grep '^listen_addresses' /var/lib/postgresql/data/postgresql.conf 2>/dev/null || echo 'não encontrado'")
    if echo "$LISTEN_ADDR" | grep -q "listen_addresses = '\*'"; then
        print_status 0 "listen_addresses = *"
    else
        print_status 1 "listen_addresses não configurado corretamente: $LISTEN_ADDR"
    fi
    
    if docker exec ai_saas_postgres_prod sh -c "grep -q 'host.*all.*all.*0.0.0.0/0.*md5' /var/lib/postgresql/data/pg_hba.conf" 2>/dev/null; then
        print_status 0 "pg_hba.conf permite conexões externas"
    else
        print_status 1 "pg_hba.conf não permite conexões externas"
    fi
fi

if command -v ufw > /dev/null 2>&1; then
    UFW_STATUS=$(sudo ufw status | head -1)
    if echo "$UFW_STATUS" | grep -q "Status: active"; then
        if sudo ufw status | grep -q "5433/tcp"; then
            print_status 0 "Porta 5433 liberada no UFW"
        else
            print_status 1 "Porta 5433 não liberada no UFW"
        fi
    fi
fi

if [ $CONTAINER_RUNNING -eq 0 ]; then
    if docker exec ai_saas_postgres_prod pg_isready -U postgres > /dev/null 2>&1; then
        print_status 0 "PostgreSQL responde localmente"
    else
        print_status 1 "PostgreSQL não responde localmente"
    fi
fi

INSTANCE_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || hostname -I | awk '{print $1}')
echo ""
echo "Informações de conexão:"
echo "Host: $INSTANCE_IP"
echo "Port: 5433"
echo "Database: ai_saas_db"
echo "Username: postgres"

if [ $CONTAINER_RUNNING -ne 0 ] || [ $PORT_LISTENING -ne 0 ]; then
    echo ""
    echo "Problemas encontrados. Verifique acima."
else
    echo ""
    echo "Todos os checks básicos passaram."
fi
