#!/bin/bash
# Script rápido para diagnosticar problema do frontend

set -eu

RESOURCE_GROUP="${1:-skyfirstlabs-poc}"
VM_NAME="${2:-skyfirstlabs-staging}"

echo " Verificando status do frontend..."
az vm run-command invoke \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --command-id RunShellScript \
  --scripts '
    echo "=== STATUS DO CONTAINER ==="
    docker ps --filter "name=ai_saas_frontend_prod" --format "{{.Names}}: {{.Status}}"
    echo ""
    
    echo "=== LOGS DO FRONTEND (últimas 30 linhas) ==="
    docker logs ai_saas_frontend_prod --tail 30 2>&1
    echo ""
    
    echo "=== TESTE DE PORTA 3000 (dentro do container) ==="
    docker exec ai_saas_frontend_prod sh -c "nc -zv localhost 3000 2>&1 || echo PORTA_NAO_ESCUTANDO" 2>&1 || echo "NC_NAO_DISPONIVEL"
    echo ""
    
    echo "=== TESTE HTTP (dentro do container) ==="
    docker exec ai_saas_frontend_prod sh -c "wget -qO- --timeout=3 http://localhost:3000 2>&1 | head -3 || echo ERRO_HTTP" 2>&1 || echo "WGET_NAO_DISPONIVEL"
    echo ""
    
    echo "=== TESTE NGINX -> FRONTEND ==="
    docker exec ai_saas_proxy wget -qO- --timeout=5 http://frontend:3000 2>&1 | head -5 || echo "ERRO_NGINX_FRONTEND"
    echo ""
    
    echo "=== PROCESSOS NO FRONTEND ==="
    docker exec ai_saas_frontend_prod sh -c "ps aux 2>&1" || echo "ERRO_PS"
  ' 2>&1

