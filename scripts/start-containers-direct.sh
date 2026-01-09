#!/bin/bash
# Script direto para iniciar containers

RESOURCE_GROUP="${1:-skyfirstlabs-poc}"
VM_NAME="${2:-skyfirstlabs-staging}"

echo "🚀 Iniciando containers diretamente..."
az vm run-command invoke \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --command-id RunShellScript \
  --scripts '
    echo "=== Containers existentes ==="
    docker ps -a --format "{{.Names}}: {{.Status}}"
    echo ""
    echo "=== Iniciando containers ==="
    docker start ai_saas_postgres_prod ai_saas_redis_prod ai_saas_backend_prod ai_saas_frontend_prod ai_saas_proxy 2>&1
    echo ""
    echo "=== Aguardando 15 segundos ==="
    sleep 15
    echo ""
    echo "=== Status final ==="
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
  ' 2>&1

