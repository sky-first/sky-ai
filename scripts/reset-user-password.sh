#!/bin/bash
# Script para resetar senha de usuário na VM Azure
# Resolve erro 500 causado por hash de senha corrompido
# Uso: ./scripts/reset-user-password.sh [VM_IP] [EMAIL] [PASSWORD] [RESOURCE_GROUP] [VM_NAME]

set -eu

VM_IP="${1:-20.185.60.67}"
EMAIL="${2:-test@example.com}"
PASSWORD="${3:-Test@2024!Secure}"
RESOURCE_GROUP="${4:-skyfirstlabs-poc}"
VM_NAME="${5:-skyfirstlabs-staging}"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}    Resetar Senha de Usuário${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${BLUE}VM IP:${NC} $VM_IP"
echo -e "${BLUE}Email:${NC} $EMAIL"
echo -e "${BLUE}Resource Group:${NC} $RESOURCE_GROUP"
echo -e "${BLUE}VM Name:${NC} $VM_NAME"
echo ""

# Verificar Azure CLI
if ! command -v az >/dev/null 2>&1; then
    echo -e "${RED}[ERROR] Azure CLI não encontrado${NC}"
    echo "   Instale: https://docs.microsoft.com/cli/azure/install-azure-cli"
    exit 1
fi

# Verificar login
if ! az account show >/dev/null 2>&1; then
    echo -e "${RED}[ERROR] Não está logado no Azure CLI${NC}"
    echo "   Execute: az login"
    exit 1
fi

echo -e "${GREEN}[OK] Azure CLI configurado${NC}"
echo ""

echo -e "${BLUE} Executando reset de senha...${NC}"

# Escapar senha para uso em Python (substituir ' por \' e " por \")
ESCAPED_PASSWORD=$(echo "$PASSWORD" | sed "s/'/\\\\'/g" | sed 's/"/\\"/g')
ESCAPED_EMAIL=$(echo "$EMAIL" | sed "s/'/\\\\'/g" | sed 's/"/\\"/g')

# Gerar hash da senha primeiro
echo -e "${BLUE} Gerando hash da senha...${NC}"
HASH_RESULT=$(az vm run-command invoke \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --command-id RunShellScript \
  --scripts "
    docker exec ai_saas_backend_prod python -c \"
import sys
sys.path.insert(0, '/app')
from src.core.security import get_password_hash
hash_value = get_password_hash('$ESCAPED_PASSWORD')
print(hash_value)
\"
  " 2>&1)

# Extrair hash do resultado
NEW_HASH=$(echo "$HASH_RESULT" | python3 -c "
import sys
import json
import re
try:
    data = json.load(sys.stdin)
    if 'value' in data and len(data['value']) > 0:
        message = data['value'][0].get('message', '')
        # Procurar hash bcrypt (começa com $2)
        match = re.search(r'\\\$2[abxy]\\\$[0-9]+\\\$[A-Za-z0-9./]+', message)
        if match:
            print(match.group(0))
except:
    pass
" 2>/dev/null || echo "")

if [ -z "$NEW_HASH" ] || [ ${#NEW_HASH} -lt 20 ]; then
    echo -e "${RED}[ERROR] Erro ao gerar hash da senha${NC}"
    echo "$HASH_RESULT"
    exit 1
fi

echo -e "${GREEN}[OK] Hash gerado (${#NEW_HASH} caracteres)${NC}"
echo ""

# Atualizar senha diretamente no banco via SQL
echo -e "${BLUE} Atualizando senha no banco de dados...${NC}"
RESULT=$(az vm run-command invoke \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --command-id RunShellScript \
  --scripts "
    # Gerar hash novamente dentro do container para garantir que está correto
    HASH=\$(docker exec ai_saas_backend_prod python -c \"
import sys
sys.path.insert(0, '/app')
from src.core.security import get_password_hash
print(get_password_hash('$ESCAPED_PASSWORD'))
\" 2>&1 | grep -o '\$2[abxy]\$[0-9]\+\$[A-Za-z0-9./]\{53\}')
    
    if [ -z \"\$HASH\" ] || [ \${#HASH} -lt 50 ]; then
      echo '[ERROR] Erro ao gerar hash'
      exit 1
    fi
    
    # Atualizar no banco
    docker exec ai_saas_postgres_prod psql -U postgres -d ai_saas_db -c \"
      UPDATE users 
      SET password_hash = '\$HASH'
      WHERE email = '$ESCAPED_EMAIL';
      
      SELECT 
        email,
        CASE 
          WHEN LENGTH(password_hash) = 60 AND password_hash LIKE '\\\$2%' THEN '[OK] Senha atualizada com sucesso'
          ELSE '[ERROR] Erro ao atualizar senha'
        END as status,
        LENGTH(password_hash) as hash_tamanho,
        LEFT(password_hash, 20) as hash_inicio
      FROM users 
      WHERE email = '$ESCAPED_EMAIL';
    \" 2>&1
  " 2>&1)

# Extrair resultado - melhorar parsing do JSON
OUTPUT=$(echo "$RESULT" | python3 -c "
import sys
import json
try:
    data = json.load(sys.stdin)
    if 'value' in data and len(data['value']) > 0:
        message = data['value'][0].get('message', '')
        print(message)
except:
    pass
" 2>/dev/null || echo "$RESULT")

# Limpar output (remover [stdout] e [stderr])
CLEAN_OUTPUT=$(echo "$OUTPUT" | sed 's/\[stdout\]//g' | sed 's/\[stderr\]//g' | grep -v "^$" | tail -20)

# Verificar se foi bem-sucedido
if echo "$CLEAN_OUTPUT" | grep -q "[OK]\|sucesso\|successfully\|Password updated\|Senha resetada"; then
    echo -e "${GREEN}[OK] Senha resetada com sucesso!${NC}"
    echo ""
    echo "$CLEAN_OUTPUT"
    echo ""
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}    Credenciais Atualizadas${NC}"
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}Email:${NC} $EMAIL"
    echo -e "${CYAN}Senha:${NC} $PASSWORD"
    echo ""
    echo -e "${GREEN}[OK] Agora você pode fazer login normalmente!${NC}"
    echo ""
    
    # Validar hash no banco (opcional)
    echo -e "${BLUE} Validando hash no banco...${NC}"
    VALIDATION=$(az vm run-command invoke \
      --resource-group "$RESOURCE_GROUP" \
      --name "$VM_NAME" \
      --command-id RunShellScript \
      --scripts "
        docker exec ai_saas_postgres_prod psql -U postgres -d ai_saas_db -t -c \"
          SELECT 
            CASE 
              WHEN LENGTH(password_hash) >= 20 AND password_hash LIKE '\\\$2%' THEN '[OK] Hash válido'
              ELSE '[ERROR] Hash ainda inválido'
            END as status,
            LENGTH(password_hash) as tamanho,
            LEFT(password_hash, 20) as inicio
          FROM users 
          WHERE email = '$ESCAPED_EMAIL' 
          LIMIT 1;
        \" 2>&1 | grep -v '^$' | head -3
      " 2>&1)
    
    VALIDATION_OUTPUT=$(echo "$VALIDATION" | grep -o '"message":"[^"]*"' | sed 's/"message":"//;s/"$//' | sed 's/\\n/\n/g' || echo "")
    if [ -n "$VALIDATION_OUTPUT" ]; then
        echo "$VALIDATION_OUTPUT"
    fi
    
else
    echo -e "${RED}[ERROR] Erro ao resetar senha${NC}"
    echo ""
    echo "$CLEAN_OUTPUT"
    echo ""
    echo -e "${YELLOW}Output completo (debug):${NC}"
    echo "$OUTPUT" | head -30
    echo ""
    echo -e "${YELLOW}[INFO] Possíveis causas:${NC}"
    echo "   1. Container backend não está rodando"
    echo "   2. Usuário não existe no banco"
    echo "   3. Problema de conexão com banco de dados"
    echo ""
    echo -e "${BLUE}Verifique os logs:${NC}"
    echo "   az vm run-command invoke -g $RESOURCE_GROUP -n $VM_NAME --command-id RunShellScript --scripts 'docker logs ai_saas_backend_prod --tail 50'"
    exit 1
fi

echo ""
echo -e "${GREEN}[OK] Processo concluído!${NC}"
echo ""
echo -e "${BLUE}Próximos passos:${NC}"
echo "   1. Tente fazer login com as credenciais acima"
echo "   2. Se ainda houver erro, verifique os logs do backend"
echo "   3. Considere aplicar a correção preventiva no código (security.py)"

