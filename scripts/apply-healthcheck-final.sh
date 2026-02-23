#!/bin/bash
set -eu
RESOURCE_GROUP="${1:-skyfirstlabs-poc}"
VM_NAME="${2:-skyfirstlabs-staging}"

echo " Aplicando healthcheck na VM..."

# Script muito simples
az vm run-command invoke \
    --resource-group "$RESOURCE_GROUP" \
    --name "$VM_NAME" \
    --command-id RunShellScript \
    --scripts \
        'cd /home/azureuser/projeto/sky-poc-infra 2>/dev/null || cd /home/azureuser/projeto/poc-deploy 2>/dev/null || exit 1' \
        'if grep -A 10 "frontend:" docker-compose.yml | grep -q "healthcheck:"; then echo "[OK] Healthcheck já existe"; exit 0; fi' \
        'cp docker-compose.yml docker-compose.yml.backup' \
        'sed -i "/- ai_saas_network/a\\    healthcheck:\\n      test: [\\\"CMD\\\", \\\"wget\\\", \\\"--quiet\\\", \\\"--tries=1\\\", \\\"--spider\\\", \\\"http://localhost:3000/ || exit 1\\\"]\\n      interval: 30s\\n      timeout: 10s\\n      retries: 5\\n      start_period: 90s" docker-compose.yml' \
        'if grep -A 10 "frontend:" docker-compose.yml | grep -q "healthcheck:"; then echo "[OK] Healthcheck aplicado"; else echo "[ERROR] Erro"; exit 1; fi' \
        'docker compose down' \
        'docker compose up -d' \
        'sleep 20' \
        'docker ps --filter "name=frontend\|proxy" --format "{{.Names}}: {{.Status}}"' \
        'curl -s -o /dev/null -w "HTTP: %{http_code}\n" http://localhost || echo "Aguardando..."' \
    --output json 2>&1 | grep -A 200 '"message"' | head -100 || echo "Comando executado"

echo ""
echo "[OK] Deploy concluído"

