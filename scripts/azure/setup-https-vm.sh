#!/bin/bash
# DEVOPS: Script para configurar HTTPS na VM
# Executa os 3 passos necessários: gerar certificados, aplicar nginx config e reiniciar proxy

set -eu

VM_IP="${1:-20.86.142.1}"
VM_USER="${VM_USER:-azureuser}"
PROJECT_DIR="${PROJECT_DIR:-/home/azureuser/projeto/sky-poc-infra}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=========================================="
echo " Configurando HTTPS na VM"
echo "==========================================${NC}"
echo ""
echo "VM: $VM_USER@$VM_IP"
echo "Projeto: $PROJECT_DIR"
echo ""

# Tentar encontrar chave SSH funcionando
SSH_KEY_PATH=""
SSH_KEYS_TO_TRY=(
    "$PROJECT_ROOT/keys/azure/team/id_rsa_poc"
    "$PROJECT_ROOT/keys/azure/team/id_rsa_staging"
    "$PROJECT_ROOT/keys/azure/team/id_rsa_dev"
    "$PROJECT_ROOT/keys/azure/team/id_rsa_prod"
    "$PROJECT_ROOT/keys/azure/id_rsa"
    "$HOME/.ssh/id_rsa"
    "$HOME/.ssh/id_ed25519"
)

echo -e "${BLUE}1.  Testando conexão SSH...${NC}"
for key in "${SSH_KEYS_TO_TRY[@]}"; do
    if [ ! -f "$key" ]; then
        continue
    fi
    
    chmod 600 "$key" 2>/dev/null || true
    
    echo -n "  Tentando $key... "
    if ssh -i "$key" \
        -o ConnectTimeout=10 \
        -o StrictHostKeyChecking=accept-new \
        -o BatchMode=yes \
        "$VM_USER@$VM_IP" "echo 'SSH OK'" >/dev/null 2>&1; then
        SSH_KEY_PATH="$key"
        echo -e "${GREEN}[OK] OK${NC}"
        break
    else
        echo -e "${RED}[ERROR]${NC}"
    fi
done

if [ -z "$SSH_KEY_PATH" ]; then
    echo ""
    echo -e "${RED}[ERROR] Não foi possível conectar à VM via SSH com nenhuma chave${NC}"
    echo ""
    echo "Verifique:"
    echo "  - IP da VM está correto? ($VM_IP)"
    echo "  - Firewall permite SSH (porta 22)?"
    echo "  - VM está acessível? (ping $VM_IP)"
    echo ""
    echo "Chaves testadas:"
    for key in "${SSH_KEYS_TO_TRY[@]}"; do
        if [ -f "$key" ]; then
            echo "  - $key"
        fi
    done
    echo ""
    echo "[INFO] Alternativa: Execute os comandos manualmente na VM:"
    echo "   cd $PROJECT_DIR"
    echo "   bash scripts/azure/generate-self-signed-certs.sh . $VM_IP"
    echo "   bash scripts/azure/apply-nginx-config.sh ."
    echo "   docker compose restart proxy"
    exit 1
fi

echo -e "${GREEN}[OK] Conexão SSH OK${NC}"
echo ""

# Passo 1: Gerar certificados
echo -e "${BLUE}2.  Gerando certificados SSL auto-assinados...${NC}"
if ssh -i "$SSH_KEY_PATH" \
    -o ConnectTimeout=10 \
    -o StrictHostKeyChecking=accept-new \
    "$VM_USER@$VM_IP" "cd $PROJECT_DIR && bash scripts/azure/generate-self-signed-certs.sh . $VM_IP" 2>&1; then
    echo -e "${GREEN}[OK] Certificados gerados${NC}"
else
    echo -e "${RED}[ERROR] Erro ao gerar certificados${NC}"
    exit 1
fi

echo ""

# Passo 2: Aplicar configuração Nginx
echo -e "${BLUE}3.  Aplicando configuração Nginx (HTTPS)...${NC}"
if ssh -i "$SSH_KEY_PATH" \
    -o ConnectTimeout=10 \
    -o StrictHostKeyChecking=accept-new \
    "$VM_USER@$VM_IP" "cd $PROJECT_DIR && bash scripts/azure/apply-nginx-config.sh ." 2>&1; then
    echo -e "${GREEN}[OK] Configuração Nginx aplicada${NC}"
else
    echo -e "${RED}[ERROR] Erro ao aplicar configuração Nginx${NC}"
    exit 1
fi

echo ""

# Passo 3: Reiniciar proxy
echo -e "${BLUE}4.  Reiniciando proxy Nginx...${NC}"
if ssh -i "$SSH_KEY_PATH" \
    -o ConnectTimeout=10 \
    -o StrictHostKeyChecking=accept-new \
    "$VM_USER@$VM_IP" "cd $PROJECT_DIR && docker compose restart proxy" 2>&1; then
    echo -e "${GREEN}[OK] Proxy reiniciado${NC}"
else
    echo -e "${YELLOW}[WARNING] Erro ao reiniciar proxy (pode ser que não esteja rodando)${NC}"
    echo "Tente manualmente: docker compose restart proxy"
fi

echo ""
echo -e "${GREEN}=========================================="
echo "[OK] HTTPS Configurado!"
echo "==========================================${NC}"
echo ""
echo "Acesse:"
echo "  - HTTP:  http://$VM_IP (redireciona para HTTPS)"
echo "  - HTTPS: https://$VM_IP"
echo ""
echo -e "${YELLOW}[WARNING] NOTA: Certificados auto-assinados gerarão aviso no navegador.${NC}"
echo "   Para produção, use Let's Encrypt ou certificados válidos."
echo ""

