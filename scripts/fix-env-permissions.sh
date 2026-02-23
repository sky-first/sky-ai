#!/bin/bash
# scripts/fix-env-permissions.sh
# Verifica e corrige permissões do .env (para uso na VM Linux)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_DIR/.env"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

if [ ! -f "$ENV_FILE" ]; then
    echo -e "${YELLOW}.env não encontrado em $ENV_FILE${NC}"
    exit 0
fi

# Verificar permissões atuais
CURRENT_PERMS=$(stat -c "%a" "$ENV_FILE" 2>/dev/null || echo "000")

if [ "$CURRENT_PERMS" = "600" ] || [ "$CURRENT_PERMS" = "400" ]; then
    echo -e "${GREEN}[OK] Permissões corretas: $CURRENT_PERMS${NC}"
    exit 0
fi

echo -e "${YELLOW}Permissões atuais: $CURRENT_PERMS${NC}"
echo -e "${BLUE}Corrigindo para 600 (rw-------)...${NC}"

chmod 600 "$ENV_FILE"

NEW_PERMS=$(stat -c "%a" "$ENV_FILE" 2>/dev/null || echo "000")
if [ "$NEW_PERMS" = "600" ]; then
    echo -e "${GREEN}[OK] Permissões corrigidas: $NEW_PERMS${NC}"
else
    echo -e "${RED}[ERROR] Erro ao corrigir permissões${NC}"
    exit 1
fi

