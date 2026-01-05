#!/bin/bash
# Script para executar diagnóstico na VM via Azure CLI Run Command
# Não requer SSH direto - usa Azure Run Command

set -eu

RESOURCE_GROUP="${RESOURCE_GROUP:-POC-SKY}"
VM_NAME="${VM_NAME:-poc-sky}"
VM_IP="${VM_IP:-172.172.134.36}"

echo "=========================================="
echo "🔍 Executando Diagnóstico Remoto na VM"
echo "=========================================="
echo ""
echo "Resource Group: $RESOURCE_GROUP"
echo "VM Name: $VM_NAME"
echo "VM IP: $VM_IP"
echo ""

# Verificar se Azure CLI está instalado
if ! command -v az &> /dev/null; then
    echo "❌ ERRO: Azure CLI não está instalado"
    echo "   Instale em: https://aka.ms/installazurecli"
    exit 1
fi

# Verificar se está logado
echo "Verificando autenticação Azure..."
if ! az account show &> /dev/null; then
    echo "❌ Não está autenticado no Azure CLI"
    echo "   Execute: az login"
    exit 1
fi
echo "✅ Autenticado no Azure"
echo ""

# Script a ser executado na VM
read -r -d '' SCRIPT_CONTENT << 'EOF' || true
set -eu
PROJECT_DIR="/home/azureuser/projeto/sky-poc-infra"
if [ ! -d "$PROJECT_DIR" ]; then
    if [ -d ~/projeto/poc-deploy ]; then
        PROJECT_DIR=~/projeto/poc-deploy
    else
        echo "❌ Diretório do projeto não encontrado"
        exit 1
    fi
fi
cd "$PROJECT_DIR"

# Baixar script de diagnóstico se não existir
if [ ! -f scripts/azure/fix-connection-issue.sh ]; then
    echo "Script de diagnóstico não encontrado localmente"
    echo "Executando diagnóstico básico..."
    
    echo "=== Status dos Containers ==="
    sudo docker compose ps || sudo docker-compose ps || sudo docker ps
    
    echo ""
    echo "=== Container Proxy ==="
    PROXY=$(sudo docker ps --format "{{.Names}}" | grep -E "proxy|nginx" | head -1)
    if [ -n "$PROXY" ]; then
        echo "Container: $PROXY"
        sudo docker logs --tail=20 "$PROXY" 2>&1 | tail -10
    else
        echo "❌ Proxy não está rodando"
    fi
    
    echo ""
    echo "=== Porta 80 ==="
    sudo ss -tlnp | grep ":80 " || sudo netstat -tlnp | grep ":80 " || echo "Porta 80 não está escutando"
    
    echo ""
    echo "=== Configuração Nginx ==="
    if [ -f docker/nginx/nginx.conf ]; then
        if grep -q "return 301 https" docker/nginx/nginx.conf && ! grep -q "# return 301 https" docker/nginx/nginx.conf; then
            echo "⚠️ PROBLEMA: nginx redirecionando para HTTPS sem certificados"
            if [ -f docker/nginx/nginx.conf.http-only ]; then
                echo "🔧 Aplicando correção..."
                sudo cp docker/nginx/nginx.conf docker/nginx/nginx.conf.backup
                sudo cp docker/nginx/nginx.conf.http-only docker/nginx/nginx.conf
                sudo docker compose restart proxy || sudo docker restart "$PROXY" 2>/dev/null || true
                echo "✅ Correção aplicada"
            fi
        fi
    fi
else
    bash scripts/azure/fix-connection-issue.sh
fi
EOF

echo "Executando diagnóstico na VM..."
echo ""

# Converter script para array (formato necessário para Azure CLI)
IFS=$'\n' read -d '' -r -a SCRIPTS_ARRAY <<< "$SCRIPT_CONTENT" || true

# Executar via Azure CLI
OUTPUT=$(az vm run-command invoke \
    --resource-group "$RESOURCE_GROUP" \
    --name "$VM_NAME" \
    --command-id RunShellScript \
    --scripts "${SCRIPTS_ARRAY[@]}" \
    --output json 2>&1)

if [ $? -eq 0 ]; then
    echo "=========================================="
    echo "✅ Comando executado com sucesso"
    echo "=========================================="
    echo ""
    
    # Extrair e mostrar mensagem
    echo "$OUTPUT" | jq -r '.value[0].message' 2>/dev/null || echo "$OUTPUT"
    
    echo ""
    echo "=========================================="
    echo "📋 Próximos Passos"
    echo "=========================================="
    echo ""
    echo "1. Se o problema foi corrigido, teste a conexão:"
    echo "   curl http://$VM_IP/health"
    echo ""
    echo "2. Se ainda houver problemas, verifique:"
    echo "   - NSG permite porta 80: az network nsg rule list -g $RESOURCE_GROUP --nsg-name ai-saas-nsg-poc-sky"
    echo "   - Containers estão rodando: az vm run-command invoke -g $RESOURCE_GROUP -n $VM_NAME --command-id RunShellScript --scripts 'sudo docker ps'"
    echo ""
else
    echo "❌ ERRO ao executar comando na VM"
    echo "$OUTPUT"
    exit 1
fi

