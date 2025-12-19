#!/bin/bash

set -e

echo "Configurando PostgreSQL para aceitar conexões externas..."

if ! docker ps | grep -q ai_saas_postgres_prod; then
    echo "ERRO: Container não está rodando!"
    echo "Execute: docker compose -f docker-compose.postgres-only.yml up -d"
    exit 1
fi

docker exec ai_saas_postgres_prod sh -c "
    if ! grep -q 'host.*all.*all.*0.0.0.0/0.*md5' /var/lib/postgresql/data/pg_hba.conf; then
        echo '' >> /var/lib/postgresql/data/pg_hba.conf
        echo '# Aceitar conexões externas' >> /var/lib/postgresql/data/pg_hba.conf
        echo 'host    all             all             0.0.0.0/0               md5' >> /var/lib/postgresql/data/pg_hba.conf
        echo 'host    all             all             ::/0                    md5' >> /var/lib/postgresql/data/pg_hba.conf
    fi
"

docker exec ai_saas_postgres_prod sh -c "
    if grep -q \"^listen_addresses = 'localhost'\" /var/lib/postgresql/data/postgresql.conf; then
        sed -i \"s/^listen_addresses = 'localhost'/listen_addresses = '*'/g\" /var/lib/postgresql/data/postgresql.conf
    elif grep -q \"^#listen_addresses = 'localhost'\" /var/lib/postgresql/data/postgresql.conf; then
        sed -i \"s/^#listen_addresses = 'localhost'/listen_addresses = '*'/g\" /var/lib/postgresql/data/postgresql.conf
    elif ! grep -q \"^listen_addresses = '\*'\" /var/lib/postgresql/data/postgresql.conf; then
        if grep -q \"^listen_addresses\" /var/lib/postgresql/data/postgresql.conf; then
            sed -i \"s/^listen_addresses.*/listen_addresses = '*'/g\" /var/lib/postgresql/data/postgresql.conf
        else
            echo '' >> /var/lib/postgresql/data/postgresql.conf
            echo 'listen_addresses = '\''*'\''' >> /var/lib/postgresql/data/postgresql.conf
        fi
    fi
"

docker restart ai_saas_postgres_prod
sleep 5

if ! docker ps | grep -q ai_saas_postgres_prod; then
    echo "ERRO: Falha ao reiniciar container"
    exit 1
fi

if command -v ufw > /dev/null 2>&1; then
    UFW_STATUS=$(sudo ufw status | head -1)
    if echo "$UFW_STATUS" | grep -q "Status: active"; then
        if ! sudo ufw status | grep -q "5433/tcp"; then
            sudo ufw allow 5433/tcp
        fi
    fi
fi

sleep 3
if sudo netstat -tlnp 2>/dev/null | grep -q ":5433" || sudo ss -tlnp 2>/dev/null | grep -q ":5433"; then
    INSTANCE_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || hostname -I | awk '{print $1}')
    echo "Configuração concluída!"
    echo "Host: $INSTANCE_IP"
    echo "Port: 5433"
    echo "Database: ai_saas_db"
else
    sleep 5
    if sudo netstat -tlnp 2>/dev/null | grep -q ":5433" || sudo ss -tlnp 2>/dev/null | grep -q ":5433"; then
        INSTANCE_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || hostname -I | awk '{print $1}')
        echo "Configuração concluída!"
    else
        echo "ERRO: Porta 5433 não está escutando"
        echo "Verifique: docker logs ai_saas_postgres_prod"
        exit 1
    fi
fi
