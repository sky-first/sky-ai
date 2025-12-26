#!/bin/bash
# scripts/check-ia-usage.sh
# Verifica se o backend precisa acessar o repositório IA

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$PROJECT_DIR/../sky-poc-backend"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}╔════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     Verificando Uso do IA no Backend               ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════════╝${NC}"
echo ""

if [ ! -d "$BACKEND_DIR" ]; then
    echo -e "${YELLOW}Backend não encontrado em: $BACKEND_DIR${NC}"
    echo -e "${YELLOW}Verificação não pode ser completada${NC}"
    exit 0
fi

echo -e "${BLUE}Verificando imports e referências ao IA...${NC}"
echo ""

# Verificar imports Python
FOUND_IMPORTS=0

# Procurar por imports relacionados a IA
if [ -d "$BACKEND_DIR/src" ]; then
    IMPORTS=$(grep -r "from.*ia\|import.*ia\|sky-poc-ai\|../ia\|../../ia" "$BACKEND_DIR/src" 2>/dev/null | head -10)
    
    if [ -n "$IMPORTS" ]; then
        echo -e "${YELLOW}⚠️  Referências ao IA encontradas:${NC}"
        echo "$IMPORTS"
        echo ""
        FOUND_IMPORTS=1
    else
        echo -e "${GREEN}✅ Nenhuma referência direta ao IA encontrada no código${NC}"
    fi
fi

# Verificar Dockerfile
echo ""
echo -e "${BLUE}Verificando Dockerfile do backend...${NC}"

if [ -f "$BACKEND_DIR/docker/Dockerfile" ]; then
    DOCKERFILE_IA=$(grep -i "ia\|ai" "$BACKEND_DIR/docker/Dockerfile" 2>/dev/null | grep -v "^#" | head -5)
    
    if [ -n "$DOCKERFILE_IA" ]; then
        echo -e "${YELLOW}⚠️  Referências ao IA no Dockerfile:${NC}"
        echo "$DOCKERFILE_IA"
        echo ""
        FOUND_IMPORTS=1
    else
        echo -e "${GREEN}✅ Dockerfile não referencia IA${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  Dockerfile não encontrado${NC}"
fi

# Verificar requirements.txt ou pyproject.toml
echo ""
echo -e "${BLUE}Verificando dependências...${NC}"

for file in "$BACKEND_DIR/requirements.txt" "$BACKEND_DIR/pyproject.toml" "$BACKEND_DIR/setup.py"; do
    if [ -f "$file" ]; then
        IA_DEPS=$(grep -i "ia\|ai" "$file" 2>/dev/null | grep -v "^#" | head -5)
        if [ -n "$IA_DEPS" ]; then
            echo -e "${YELLOW}⚠️  Referências ao IA em $(basename $file):${NC}"
            echo "$IA_DEPS"
            echo ""
            FOUND_IMPORTS=1
        fi
    fi
done

# Conclusão
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ $FOUND_IMPORTS -eq 1 ]; then
    echo -e "${YELLOW}⚠️  CONCLUSÃO: Backend parece usar IA${NC}"
    echo ""
    echo -e "${BLUE}RECOMENDAÇÃO:${NC}"
    echo -e "${YELLOW}Adicionar volume no docker-compose.yml:${NC}"
    echo ""
    echo -e "${GREEN}backend:${NC}"
    echo -e "${GREEN}  volumes:${NC}"
    echo -e "${GREEN}    - ../sky-poc-ai:/app/ia:ro${NC}"
    echo ""
else
    echo -e "${GREEN}✅ CONCLUSÃO: Backend não parece usar IA diretamente${NC}"
    echo -e "${GREEN}   Não é necessário montar como volume${NC}"
    echo ""
    echo -e "${BLUE}NOTA: Se IA for usado apenas como referência ou biblioteca,${NC}"
    echo -e "${BLUE}      pode estar sendo copiado durante o build do Docker${NC}"
fi

echo ""

