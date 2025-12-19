#!/bin/bash

# Script para verificar a estrutura do projeto na VM do Azure
# Execute este script do seu computador local

set -e

# Obter IP da VM automaticamente do Terraform
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TERRAFORM_DIR="$SCRIPT_DIR/../../infra/azure"
VM_IP=$(cd "$TERRAFORM_DIR" && terraform output -raw vm_public_ip 2>/dev/null || echo "172.191.77.30")
VM_USER="azureuser"
SSH_KEY="keys/azure/id_rsa"

echo "Verificando estrutura do projeto na VM Azure..."
echo "VM: $VM_USER@$VM_IP"
echo ""

# Verificar se a chave SSH existe
if [ ! -f "$SSH_KEY" ]; then
    echo "Chave SSH não encontrada: $SSH_KEY"
    exit 1
fi

echo "Estrutura de diretórios:"
echo "================================"
echo ""

# Verificar estrutura do projeto
ssh -i "$SSH_KEY" "$VM_USER@$VM_IP" << 'EOF'
echo "1⃣ Diretório ~/projeto:"
if [ -d ~/projeto ]; then
    echo "Existe"
    echo ""
    echo "Conteúdo:"
    ls -la ~/projeto/ 2>/dev/null | grep -E "^d" | awk '{print "    " $9}' | grep -v "^\.$" | grep -v "^\.\.$"
    echo ""
else
    echo "Não existe"
    echo ""
fi

echo "2⃣ Diretório ~/projeto/poc-deploy:"
if [ -d ~/projeto/poc-deploy ]; then
    echo "Existe"
    echo ""
    echo "Estrutura:"
    cd ~/projeto/poc-deploy
    find . -maxdepth 2 -type f -o -type d | sort | head -30 | sed 's|^\./|   |' | sed 's|^|   |'
    echo ""
    echo "Arquivos principais:"
    ls -lh docker-compose*.yml env.example 2>/dev/null | awk '{print "    " $9 " (" $5 ")"}'
    echo ""
else
    echo "Não existe"
    echo ""
fi

echo "3⃣ Diretórios backend e frontend:"
if [ -d ~/projeto/backend ]; then
    echo "Backend existe"
    ls -ld ~/projeto/backend | awk '{print "      " $9 " (modificado: " $6 " " $7 " " $8 ")"}'
else
    echo "Backend não existe"
fi

if [ -d ~/projeto/frontend ]; then
    echo "Frontend existe"
    ls -ld ~/projeto/frontend | awk '{print "      " $9 " (modificado: " $6 " " $7 " " $8 ")"}'
else
    echo "Frontend não existe"
fi
echo ""

echo "4⃣ Docker e Docker Compose:"
if command -v docker &> /dev/null; then
    echo "Docker instalado: $(docker --version 2>/dev/null | awk '{print $3}' | tr -d ',')"
else
    echo "Docker não instalado"
fi

if command -v docker-compose &> /dev/null || docker compose version &> /dev/null; then
    echo "Docker Compose instalado"
else
    echo "Docker Compose não instalado"
fi
echo ""

echo "5⃣ Containers Docker rodando:"
if command -v docker &> /dev/null; then
    CONTAINERS=$(docker ps --format "{{.Names}}" 2>/dev/null)
    if [ -z "$CONTAINERS" ]; then
        echo "Nenhum container rodando"
    else
        echo "Containers ativos:"
        echo "$CONTAINERS" | while read container; do
            echo "$container"
        done
    fi
else
    echo "Docker não disponível (execute 'newgrp docker' se necessário)"
fi
echo ""

echo "6⃣ Arquivo .env:"
if [ -f ~/projeto/poc-deploy/.env ]; then
    echo "Existe"
    echo "Tamanho: $(ls -lh ~/projeto/poc-deploy/.env | awk '{print $5}')"
    echo "Variáveis configuradas:"
    grep -E "^[A-Z_]+=" ~/projeto/poc-deploy/.env 2>/dev/null | cut -d'=' -f1 | sed 's/^/      - /' | head -10
else
    echo "Não existe (copie de env.example)"
fi
echo ""

echo "7⃣ Espaço em disco:"
df -h ~ | tail -1 | awk '{print "    Disponível: " $4 " de " $2 " (" $5 " usado)"}'
echo ""

EOF

echo "Verificação concluída!"
echo ""
echo "Para ver mais detalhes, conecte-se à VM:"
echo "./access_server_azure.sh"



