#!/bin/bash
# Script simples para reiniciar frontend e verificar status
# Execute quando não houver comandos em execução na VM

set -eu

RESOURCE_GROUP="${1:-skyfirstlabs-poc}"
VM_NAME="${2:-skyfirstlabs-staging}"

echo " Reiniciando frontend..."
az vm run-command invoke \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --command-id RunShellScript \
  --scripts '
    echo "=== REINICIANDO FRONTEND ==="
    docker restart ai_saas_frontend_prod
    echo ""
    echo "[OK] Frontend reiniciado"
    echo ""
    echo "Aguardando 20 segundos para o Next.js iniciar..."
    sleep 20
    echo ""
    echo "=== STATUS DO CONTAINER ==="
    docker ps --filter "name=ai_saas_frontend_prod" --format "{{.Names}}: {{.Status}}"
    echo ""
    echo "=== ÚLTIMAS 30 LINHAS DOS LOGS ==="
    docker logs ai_saas_frontend_prod --tail 30
    echo ""
    echo "=== TESTE DE PORTA 3000 ==="
    docker exec ai_saas_frontend_prod sh -c "wget -qO- --timeout=5 http://localhost:3000 2>&1 | head -3 || echo ERRO: Frontend não está respondendo"
    echo ""
    echo "=== TESTE NGINX -> FRONTEND ==="
    docker exec ai_saas_proxy wget -qO- --timeout=5 http://frontend:3000 2>&1 | head -3 || echo ERRO: Nginx não consegue conectar
    echo ""
    echo "=== RECURSOS DO CONTAINER ==="
    docker stats ai_saas_frontend_prod --no-stream --format "CPU: {{.CPUPerc}}, Memória: {{.MemUsage}}"
  ' 2>&1

echo ""
echo "[OK] Verificação concluída!"
echo ""
echo "[INFO] Se o frontend ainda não estiver respondendo:"
echo "   1. Verifique os logs acima para erros"
echo "   2. O Next.js pode estar compilando (pode demorar alguns minutos)"
echo "   3. Verifique recursos: docker stats ai_saas_frontend_prod"

