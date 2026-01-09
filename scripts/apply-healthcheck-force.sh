#!/bin/bash
# Script para aplicar healthcheck forçando (ignora conflitos)
set -eu

RESOURCE_GROUP="${1:-skyfirstlabs-poc}"
VM_NAME="${2:-skyfirstlabs-staging}"

echo "🚀 Aplicando healthcheck (modo direto)..."
echo ""

# Script muito simples e direto
APPLY_SCRIPT='cd /home/azureuser/projeto/sky-poc-infra 2>/dev/null || cd /home/azureuser/projeto/poc-deploy 2>/dev/null || exit 1
if grep -A 10 "frontend:" docker-compose.yml | grep -q "healthcheck:"; then
    echo "✅ Healthcheck já existe"
else
    echo "Aplicando healthcheck..."
    cp docker-compose.yml docker-compose.yml.backup
    # Método mais simples: usar perl ou python inline
    python3 << PYEOF
import re
with open("docker-compose.yml", "r") as f:
    content = f.read()
if "healthcheck:" not in content or "frontend:" in content[:content.find("healthcheck:")]:
    # Encontrar onde inserir (após networks do frontend)
    pattern = r"(frontend:.*?networks:\s+- ai_saas_network)"
    replacement = r"\1\n    # Healthcheck\n    healthcheck:\n      test: [\"CMD\", \"wget\", \"--quiet\", \"--tries=1\", \"--spider\", \"http://localhost:3000/ || exit 1\"]\n      interval: 30s\n      timeout: 10s\n      retries: 5\n      start_period: 90s"
    new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    if new_content != content:
        with open("docker-compose.yml", "w") as f:
            f.write(new_content)
        print("✅ Healthcheck aplicado")
    else:
        print("❌ Erro ao aplicar")
        exit(1)
else:
    print("✅ Healthcheck já existe")
PYEOF
fi
docker compose down
docker compose up -d
sleep 25
docker ps --filter "name=frontend\|proxy" --format "{{.Names}}: {{.Status}}"
curl -s -o /dev/null -w "HTTP: %{http_code}\n" http://localhost || echo "Aguardando..."'

# Executar diretamente sem aguardar
echo "Executando (pode levar 2-3 minutos)..."
az vm run-command invoke \
    --resource-group "$RESOURCE_GROUP" \
    --name "$VM_NAME" \
    --command-id RunShellScript \
    --scripts "$APPLY_SCRIPT" \
    --output json 2>&1 | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if 'value' in data and len(data['value']) > 0:
        msg = data['value'][0].get('message', '')
        print(msg.replace('[stdout]', '').replace('[stderr]', ''))
    elif 'error' in data:
        print('Erro:', data.get('error', {}).get('message', 'Erro desconhecido'))
    else:
        print('Resposta inesperada:', json.dumps(data, indent=2))
except json.JSONDecodeError:
    output = sys.stdin.read()
    if 'Conflict' in output:
        print('⚠️  Comando anterior ainda em execução. O healthcheck será aplicado quando o comando anterior finalizar.')
        print('💡 Aguarde 5-10 minutos e verifique manualmente via SSH ou execute novamente.')
    else:
        print('Output bruto:', output)
except Exception as e:
    print(f'Erro: {e}')
" 2>/dev/null || echo "Comando executado"

echo ""
echo "✅ Script executado"
echo ""
echo "💡 Se houver conflito, aguarde alguns minutos e verifique:"
echo "   ssh -i keys/azure/team/id_rsa_poc azureuser@20.185.60.67"
echo "   cd /home/azureuser/projeto/sky-poc-infra"
echo "   grep -A 10 'frontend:' docker-compose.yml | grep -A 5 'healthcheck:'"

