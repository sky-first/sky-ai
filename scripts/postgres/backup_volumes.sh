#!/bin/bash
# scripts/postgres/backup_volumes.sh
# Backup automatizado dos volumes Docker e banco de dados PostgreSQL
# Mantém backups dos últimos 7 dias

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKUP_DIR="$PROJECT_DIR/backups/$(date +%Y%m%d_%H%M%S)"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Iniciando backup de volumes e banco de dados...${NC}"

# Criar diretório de backup
mkdir -p "$BACKUP_DIR"

# Verificar se o container PostgreSQL está rodando
if ! docker ps | grep -q "ai_saas_postgres_prod"; then
  echo -e "${RED}ERROR: Container PostgreSQL não está rodando${NC}"
  exit 1
fi

# Backup PostgreSQL (dump do banco)
echo -e "${BLUE}Fazendo backup do PostgreSQL...${NC}"
if docker exec ai_saas_postgres_prod pg_dump -U postgres ai_saas_db | gzip > "$BACKUP_DIR/postgres_${TIMESTAMP}.sql.gz"; then
  echo -e "${GREEN}✓ Backup do PostgreSQL concluído: postgres_${TIMESTAMP}.sql.gz${NC}"
  # Verificar tamanho do arquivo
  SIZE=$(du -h "$BACKUP_DIR/postgres_${TIMESTAMP}.sql.gz" | cut -f1)
  echo -e "${GREEN}  Tamanho: $SIZE${NC}"
else
  echo -e "${RED}ERROR: Falha ao fazer backup do PostgreSQL${NC}"
  exit 1
fi

# Backup de volumes (opcional - descomente se necessário)
# echo -e "${BLUE}Fazendo backup dos volumes Docker...${NC}"
# docker run --rm \
#   -v ai_saas_postgres_prod_data:/data:ro \
#   -v "$BACKUP_DIR":/backup \
#   alpine tar czf /backup/postgres_volume_${TIMESTAMP}.tar.gz -C /data . || {
#   echo -e "${YELLOW}⚠️  Aviso: Falha ao fazer backup do volume (pode ser normal se o volume não existir)${NC}"
# }

# Backup do Redis (opcional - apenas se necessário)
# if docker ps | grep -q "ai_saas_redis_prod"; then
#   echo -e "${BLUE}Fazendo backup do Redis...${NC}"
#   docker exec ai_saas_redis_prod redis-cli --rdb /data/dump.rdb || true
#   docker cp ai_saas_redis_prod:/data/dump.rdb "$BACKUP_DIR/redis_${TIMESTAMP}.rdb" || true
# fi

echo -e "${GREEN}✅ Backup concluído em: $BACKUP_DIR${NC}"

# Limpar backups antigos (manter apenas últimos 7 dias)
echo -e "${BLUE}Limpando backups antigos (mantendo últimos 7 dias)...${NC}"
find "$PROJECT_DIR/backups" -type d -mtime +7 -exec rm -rf {} + 2>/dev/null || true
find "$PROJECT_DIR/backups" -type f -name "*.sql.gz" -mtime +7 -delete 2>/dev/null || true
find "$PROJECT_DIR/backups" -type f -name "*.tar.gz" -mtime +7 -delete 2>/dev/null || true

echo -e "${GREEN}✅ Limpeza concluída${NC}"

# Listar backups disponíveis
echo ""
echo -e "${BLUE}Backups disponíveis:${NC}"
ls -lh "$PROJECT_DIR/backups"/*/*.sql.gz 2>/dev/null | tail -5 || echo "Nenhum backup anterior encontrado"


