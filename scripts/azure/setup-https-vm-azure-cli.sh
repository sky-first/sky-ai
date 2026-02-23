#!/bin/bash
# DEVOPS: Configura HTTPS na VM usando Azure CLI run-command (sem SSH direto)
# Útil quando Azure Bastion está habilitado ou SSH está bloqueado

set -eu

VM_IP="${1:-20.86.142.1}"
RESOURCE_GROUP="${RESOURCE_GROUP:-POC-SKY}"
VM_NAME="${VM_NAME:-poc-sky}"
PROJECT_DIR="${PROJECT_DIR:-/home/azureuser/projeto/sky-poc-infra}"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=========================================="
echo " Configurando HTTPS na VM (Azure CLI)"
echo "==========================================${NC}"
echo ""
echo "VM: $VM_NAME"
echo "Resource Group: $RESOURCE_GROUP"
echo "IP: $VM_IP"
echo ""

# Verificar Azure CLI
if ! command -v az >/dev/null 2>&1; then
    echo -e "${RED}[ERROR] Azure CLI não encontrado${NC}"
    echo "Instale: https://aka.ms/InstallAzureCLI"
    exit 1
fi

# Verificar login
if ! az account show >/dev/null 2>&1; then
    echo -e "${RED}[ERROR] Não está logado no Azure CLI${NC}"
    echo "Execute: az login"
    exit 1
fi

echo -e "${GREEN}[OK] Azure CLI OK${NC}"
echo ""

# Verificar e criar scripts se necessário
echo -e "${BLUE}0.  Verificando scripts na VM...${NC}"
az vm run-command invoke \
    -g "$RESOURCE_GROUP" \
    -n "$VM_NAME" \
    --command-id RunShellScript \
    --scripts "cd $PROJECT_DIR && mkdir -p scripts/azure && if [ ! -f scripts/azure/generate-self-signed-certs.sh ]; then cat > scripts/azure/generate-self-signed-certs.sh << 'SCRIPTEOF'
#!/bin/bash
set -eu
PROJECT_DIR=\"\${1:-\$(pwd)}\"
CERTS_DIR=\"\$PROJECT_DIR/certs\"
DOMAIN=\"\${2:-localhost}\"
mkdir -p \"\$CERTS_DIR\"
if [ -f \"\$CERTS_DIR/fullchain.pem\" ] && [ -f \"\$CERTS_DIR/privkey.pem\" ]; then
    echo \"[WARNING] Certificados já existem\"
    exit 0
fi
echo \"Gerando certificado para: \$DOMAIN\"
openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout \"\$CERTS_DIR/privkey.pem\" -out \"\$CERTS_DIR/fullchain.pem\" -subj \"/C=BR/ST=State/L=City/O=Organization/CN=\$DOMAIN\" -addext \"subjectAltName=IP:127.0.0.1,IP:\$DOMAIN,DNS:localhost,DNS:\$DOMAIN\" 2>/dev/null || openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout \"\$CERTS_DIR/privkey.pem\" -out \"\$CERTS_DIR/fullchain.pem\" -subj \"/C=BR/ST=State/L=City/O=Organization/CN=\$DOMAIN\"
chmod 600 \"\$CERTS_DIR/privkey.pem\"
chmod 644 \"\$CERTS_DIR/fullchain.pem\"
echo \"[OK] Certificados gerados\"
SCRIPTEOF
chmod +x scripts/azure/generate-self-signed-certs.sh && echo 'Script generate-self-signed-certs.sh criado'; fi" \
    --output json >/dev/null 2>&1 || true

echo -e "${GREEN}[OK] Scripts verificados/criados${NC}"
echo ""

# Passo 1: Gerar certificados
echo -e "${BLUE}1.  Gerando certificados SSL auto-assinados...${NC}"
RESULT=$(az vm run-command invoke \
    -g "$RESOURCE_GROUP" \
    -n "$VM_NAME" \
    --command-id RunShellScript \
    --scripts "cd $PROJECT_DIR && bash scripts/azure/generate-self-signed-certs.sh . $VM_IP" \
    --output json 2>&1)

if echo "$RESULT" | jq -e '.value[0].message' >/dev/null 2>&1; then
    echo "$RESULT" | jq -r '.value[0].message' | grep -v "^$" || echo "[OK] Certificados gerados"
else
    echo "$RESULT" | grep -i "error\|erro" >/dev/null && {
        echo -e "${RED}[ERROR] Erro ao gerar certificados${NC}"
        echo "$RESULT"
        exit 1
    } || echo -e "${GREEN}[OK] Certificados gerados${NC}"
fi

echo ""

# Passo 2: Aplicar configuração Nginx (simplificado - apenas copia nginx.conf.secure se certificados existirem)
echo -e "${BLUE}2.  Aplicando configuração Nginx (HTTPS)...${NC}"
RESULT=$(az vm run-command invoke \
    -g "$RESOURCE_GROUP" \
    -n "$VM_NAME" \
    --command-id RunShellScript \
    --scripts "cd $PROJECT_DIR && if [ -f certs/fullchain.pem ] && [ -f certs/privkey.pem ]; then if [ -f docker/nginx/nginx.conf.secure ]; then cp docker/nginx/nginx.conf.secure docker/nginx/nginx.conf && echo '[OK] HTTPS config aplicado'; else echo '[WARNING] nginx.conf.secure não encontrado'; fi; else echo '[WARNING] Certificados não encontrados, mantendo HTTP-only'; fi" \
    --output json 2>&1)

if echo "$RESULT" | jq -e '.value[0].message' >/dev/null 2>&1; then
    echo "$RESULT" | jq -r '.value[0].message' | grep -v "^$" || echo -e "${GREEN}[OK] Configuração aplicada${NC}"
else
    echo "$RESULT" | grep -i "error\|erro" >/dev/null && {
        echo -e "${YELLOW}[WARNING] Aviso ao aplicar configuração${NC}"
    } || echo -e "${GREEN}[OK] Configuração aplicada${NC}"
fi

echo ""

# Passo 3: Reiniciar proxy
echo -e "${BLUE}3.  Reiniciando proxy Nginx...${NC}"
az vm run-command invoke \
    -g "$RESOURCE_GROUP" \
    -n "$VM_NAME" \
    --command-id RunShellScript \
    --scripts "cd $PROJECT_DIR && docker compose restart proxy" \
    --output json | jq -r '.value[0].message' || {
    echo -e "${YELLOW}[WARNING] Erro ao reiniciar proxy (pode ser que não esteja rodando)${NC}"
    echo "Tente manualmente: docker compose restart proxy"
}

echo -e "${GREEN}[OK] Proxy reiniciado${NC}"
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

