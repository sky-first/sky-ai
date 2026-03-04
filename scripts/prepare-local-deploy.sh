#!/bin/bash
# scripts/prepare-local-deploy.sh
# Script para preparar ambiente local antes do deploy

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🚀 Preparando ambiente para deploy local...${NC}"
echo ""

# 1. Validar estrutura
echo -e "${BLUE}1. Validando estrutura de pastas...${NC}"
if [ -f "$PROJECT_DIR/scripts/validate_structure.sh" ]; then
  bash "$PROJECT_DIR/scripts/validate_structure.sh"
else
  echo -e "${YELLOW}⚠️  Script de validação não encontrado, pulando...${NC}"
fi

# 2. Verificar Docker
echo ""
echo -e "${BLUE}2. Verificando Docker...${NC}"
if ! command -v docker &> /dev/null; then
  echo -e "${RED}❌ Docker não está instalado${NC}"
  exit 1
fi

if ! docker ps &> /dev/null; then
  echo -e "${RED}❌ Docker não está rodando${NC}"
  exit 1
fi

echo -e "${GREEN}✅ Docker está instalado e rodando${NC}"

# 3. Verificar Docker Compose
echo ""
echo -e "${BLUE}3. Verificando Docker Compose...${NC}"
if ! docker compose version &> /dev/null; then
  echo -e "${RED}❌ Docker Compose não está instalado${NC}"
  exit 1
fi

echo -e "${GREEN}✅ Docker Compose está instalado${NC}"

# 4. Validar docker-compose.yml
echo ""
echo -e "${BLUE}4. Validando docker-compose.yml...${NC}"
if docker compose -f "$PROJECT_DIR/docker-compose.yml" config &> /dev/null; then
  echo -e "${GREEN}✅ docker-compose.yml válido${NC}"
else
  echo -e "${RED}❌ Erro na validação do docker-compose.yml${NC}"
  docker compose -f "$PROJECT_DIR/docker-compose.yml" config
  exit 1
fi

# 5. Verificar .env
echo ""
echo -e "${BLUE}5. Verificando arquivo .env...${NC}"
if [ ! -f "$PROJECT_DIR/.env" ]; then
  echo -e "${YELLOW}⚠️  Arquivo .env não encontrado${NC}"
  echo -e "${YELLOW}   Criando a partir de env.example...${NC}"
  
  if [ -f "$PROJECT_DIR/env.example" ]; then
    cp "$PROJECT_DIR/env.example" "$PROJECT_DIR/.env"
    echo -e "${GREEN}✅ Arquivo .env criado${NC}"
    echo -e "${YELLOW}⚠️  IMPORTANTE: Edite .env e configure os valores:${NC}"
    echo -e "${YELLOW}   - POSTGRES_PASSWORD${NC}"
    echo -e "${YELLOW}   - REDIS_PASSWORD${NC}"
    echo -e "${YELLOW}   - JWT_SECRET_KEY${NC}"
    echo -e "${YELLOW}   - ENCRYPTION_KEY${NC}"
    echo -e "${YELLOW}   - NEXT_PUBLIC_API_URL (para local com proxy: /api/v1)${NC}"
  else
    echo -e "${RED}❌ env.example não encontrado${NC}"
    exit 1
  fi
else
  echo -e "${GREEN}✅ Arquivo .env encontrado${NC}"
  
  # Verificar se tem valores placeholder
  if grep -q "secure_password_here\|generate_a_secure" "$PROJECT_DIR/.env"; then
    echo -e "${YELLOW}⚠️  .env contém valores placeholder${NC}"
    echo -e "${YELLOW}   Gere valores seguros antes do deploy${NC}"
  fi
fi

# 6. Verificar espaço em disco
echo ""
echo -e "${BLUE}6. Verificando espaço em disco...${NC}"
AVAILABLE=$(df -BG "$PROJECT_DIR" | tail -1 | awk '{print $4}' | sed 's/G//')
if [ "$AVAILABLE" -lt 10 ]; then
  echo -e "${YELLOW}⚠️  Pouco espaço em disco: ${AVAILABLE}GB disponível${NC}"
  echo -e "${YELLOW}   Recomendado: pelo menos 10GB${NC}"
else
  echo -e "${GREEN}✅ Espaço em disco suficiente: ${AVAILABLE}GB${NC}"
fi

# 7. Resumo
echo ""
echo -e "${GREEN}✅ Preparação concluída!${NC}"
echo ""
echo -e "${BLUE}Próximos passos:${NC}"
echo -e "  1. Edite .env e configure os valores (se necessário)"
echo -e "  2. Deploy infraestrutura: ${YELLOW}docker compose -f docker-compose.infrastructure.yml up -d${NC}"
echo -e "  3. Deploy completo: ${YELLOW}docker compose up -d --build${NC}"
echo ""

