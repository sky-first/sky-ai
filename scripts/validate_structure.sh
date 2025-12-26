#!/bin/bash
# scripts/validate_structure.sh
# Valida estrutura de pastas antes do deploy
# Garante que todos os repositórios necessários estão presentes

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Validando estrutura de pastas...${NC}"

# Verificar se estamos no diretório correto (sky-poc-infra)
if [ ! -f "$PROJECT_DIR/docker-compose.yml" ]; then
  echo -e "${RED}ERROR: docker-compose.yml não encontrado em $PROJECT_DIR${NC}"
  echo -e "${YELLOW}Execute este script de dentro de sky-poc-infra/${NC}"
  exit 1
fi

echo -e "${GREEN}✓ docker-compose.yml encontrado${NC}"

# Verificar repositórios necessários
REQUIRED_DIRS=(
  "../sky-poc-backend"
  "../sky-poc-frontend"
  "../sky-poc-ai"
)

MISSING_DIRS=()
FOUND_DIRS=()

for dir in "${REQUIRED_DIRS[@]}"; do
  full_path="$PROJECT_DIR/$dir"
  if [ ! -d "$full_path" ]; then
    MISSING_DIRS+=("$dir")
    echo -e "${RED}✗ $dir não encontrado${NC}"
  else
    FOUND_DIRS+=("$dir")
    echo -e "${GREEN}✓ $dir encontrado${NC}"
  fi
done

if [ ${#MISSING_DIRS[@]} -gt 0 ]; then
  echo ""
  echo -e "${RED}ERROR: Diretórios faltando:${NC}"
  for dir in "${MISSING_DIRS[@]}"; do
    echo -e "  ${RED}- $dir${NC}"
  done
  echo ""
  echo -e "${YELLOW}Estrutura esperada:${NC}"
  echo "  poc-deploy/"
  echo "  ├── sky-poc-infra/     (você está aqui)"
  echo "  ├── sky-poc-backend/"
  echo "  ├── sky-poc-frontend/"
  echo "  └── sky-poc-ai/"
  echo ""
  exit 1
fi

# Verificar se docker-compose.yml referencia os caminhos corretos
echo ""
echo -e "${BLUE}Verificando referências no docker-compose.yml...${NC}"

WARNINGS=0

if grep -q "context: ../backend" "$PROJECT_DIR/docker-compose.yml"; then
  echo -e "${YELLOW}⚠️  WARNING: docker-compose.yml ainda usa 'context: ../backend'${NC}"
  echo -e "${YELLOW}   Deve ser 'context: ../sky-poc-backend'${NC}"
  WARNINGS=$((WARNINGS + 1))
fi

if grep -q "context: ../frontend" "$PROJECT_DIR/docker-compose.yml"; then
  echo -e "${YELLOW}⚠️  WARNING: docker-compose.yml ainda usa 'context: ../frontend'${NC}"
  echo -e "${YELLOW}   Deve ser 'context: ../sky-poc-frontend'${NC}"
  WARNINGS=$((WARNINGS + 1))
fi

# Verificar se os caminhos corretos estão presentes
if grep -q "context: ../sky-poc-backend" "$PROJECT_DIR/docker-compose.yml"; then
  echo -e "${GREEN}✓ Caminhos corretos para sky-poc-backend encontrados${NC}"
fi

if grep -q "context: ../sky-poc-frontend" "$PROJECT_DIR/docker-compose.yml"; then
  echo -e "${GREEN}✓ Caminhos corretos para sky-poc-frontend encontrados${NC}"
fi

# Verificar se .env existe (não obrigatório, mas recomendado)
if [ ! -f "$PROJECT_DIR/.env" ]; then
  echo -e "${YELLOW}⚠️  WARNING: Arquivo .env não encontrado${NC}"
  echo -e "${YELLOW}   Crie um arquivo .env baseado em env.example${NC}"
else
  echo -e "${GREEN}✓ Arquivo .env encontrado${NC}"
fi

echo ""
if [ $WARNINGS -eq 0 ]; then
  echo -e "${GREEN}✅ Estrutura validada com sucesso!${NC}"
  exit 0
else
  echo -e "${YELLOW}⚠️  Estrutura validada com $WARNINGS aviso(s)${NC}"
  exit 0
fi


