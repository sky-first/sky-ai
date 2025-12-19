#!/bin/bash

set -e

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configurações
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_FILE="$PROJECT_DIR/logs/optimization_$(date +%Y%m%d_%H%M%S).log"
BACKUP_DIR="$PROJECT_DIR/backups/$(date +%Y%m%d_%H%M%S)"

# Criar diretórios necessários
mkdir -p "$(dirname "$LOG_FILE")" "$BACKUP_DIR"

# Função de logging
log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1" | tee -a "$LOG_FILE"
}

log_success() {
    echo -e "${GREEN} $1${NC}" | tee -a "$LOG_FILE"
}

log_error() {
    echo -e "${RED} $1${NC}" | tee -a "$LOG_FILE"
}

log_warning() {
    echo -e "${YELLOW}  $1${NC}" | tee -a "$LOG_FILE"
}

# Função de validação pré-requisitos
check_prerequisites() {
    log "Verificando pré-requisitos..."
    
    local errors=0
    
    # Verificar Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker não está instalado"
        errors=$((errors + 1))
    fi
    
    # Verificar Docker Compose
    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        log_error "Docker Compose não está instalado"
        errors=$((errors + 1))
    fi
    
    # Verificar se containers estão rodando
    if ! docker ps | grep -q "ai_saas_postgres_prod"; then
        log_error "Container PostgreSQL não está rodando"
        errors=$((errors + 1))
    fi
    
    # Verificar memória disponível
    AVAIL_MEM=$(free -m | awk '/^Mem:/ {print $7}')
    if [ "$AVAIL_MEM" -lt 2048 ]; then
        log_warning "Memória disponível baixa: ${AVAIL_MEM}MB (recomendado: 2GB+)"
    fi
    
    if [ $errors -gt 0 ]; then
        log_error "Pré-requisitos não atendidos. Abortando."
        exit 1
    fi
    
    log_success "Pré-requisitos verificados"
}

# Backup de configurações atuais
backup_configurations() {
    log "Criando backup das configurações atuais..."
    
    CONTAINER_NAME="ai_saas_postgres_prod"
    
    # Backup PostgreSQL config
    if docker ps | grep -q "$CONTAINER_NAME"; then
        docker exec "$CONTAINER_NAME" sh -c "cat /var/lib/postgresql/data/postgresql.conf" > "$BACKUP_DIR/postgresql.conf.backup" 2>/dev/null || true
        log_success "Backup do PostgreSQL criado"
    fi
    
    # Backup docker-compose.yml
    if [ -f "$PROJECT_DIR/docker-compose.yml" ]; then
        cp "$PROJECT_DIR/docker-compose.yml" "$BACKUP_DIR/docker-compose.yml.backup"
        log_success "Backup do docker-compose.yml criado"
    fi
    
    log_success "Backups salvos em: $BACKUP_DIR"
}

# Coletar métricas antes da otimização
collect_baseline_metrics() {
    log "Coletando métricas baseline..."
    
    METRICS_FILE="$BACKUP_DIR/baseline_metrics.txt"
    
    {
        echo "=== Métricas Baseline - $(date) ==="
        echo ""
        echo "--- Sistema ---"
        free -h
        echo ""
        echo "--- CPU ---"
        top -bn1 | grep "Cpu(s)"
        echo ""
        echo "--- Docker Containers ---"
        docker stats --no-stream
        echo ""
        echo "--- PostgreSQL Connections ---"
        docker exec ai_saas_postgres_prod psql -U postgres -t -c "SELECT count(*) FROM pg_stat_activity;" 2>/dev/null || echo "N/A"
        echo ""
        echo "--- Redis Memory ---"
        docker exec ai_saas_redis_prod redis-cli INFO memory 2>/dev/null | grep used_memory_human || echo "N/A"
    } > "$METRICS_FILE"
    
    log_success "Métricas baseline salvas em: $METRICS_FILE"
}

# Otimizar PostgreSQL
optimize_postgresql() {
    log "Otimizando PostgreSQL..."
    
    MAX_CONNECTIONS=${1:-300}
    WORK_MEM_MB=${2:-2}
    
    CONTAINER_NAME="ai_saas_postgres_prod"
    
    if ! docker ps | grep -q "$CONTAINER_NAME"; then
        log_error "Container PostgreSQL não está rodando"
        return 1
    fi
    
    # Verificar memória disponível
    AVAIL_MEM=$(free -m | awk '/^Mem:/ {print $7}')
    ESTIMATED_MEM=$((MAX_CONNECTIONS * WORK_MEM_MB / 2))
    
    if [ $ESTIMATED_MEM -gt $AVAIL_MEM ]; then
        log_warning "Memória estimada (${ESTIMATED_MEM}MB) excede disponível (${AVAIL_MEM}MB)"
        log_warning "Ajustando work_mem para 1MB..."
        WORK_MEM_MB=1
    fi
    
    # Configurar max_connections
    log "Configurando max_connections = $MAX_CONNECTIONS..."
    docker exec "$CONTAINER_NAME" sh -c "
        MAX_CONN=$MAX_CONNECTIONS
        if grep -q \"^max_connections\" /var/lib/postgresql/data/postgresql.conf; then
            sed -i \"s/^max_connections = [0-9]*/max_connections = \$MAX_CONN/g\" /var/lib/postgresql/data/postgresql.conf
        elif grep -q \"^#max_connections\" /var/lib/postgresql/data/postgresql.conf; then
            sed -i \"s/^#max_connections = [0-9]*/max_connections = \$MAX_CONN/g\" /var/lib/postgresql/data/postgresql.conf
        else
            echo '' >> /var/lib/postgresql/data/postgresql.conf
            echo '# Maximum number of connections' >> /var/lib/postgresql/data/postgresql.conf
            echo \"max_connections = \$MAX_CONN\" >> /var/lib/postgresql/data/postgresql.conf
        fi
    " || { log_error "Falha ao configurar max_connections"; return 1; }
    
    # Configurar work_mem
    log "Configurando work_mem = ${WORK_MEM_MB}MB..."
    docker exec "$CONTAINER_NAME" sh -c "
        WORK_MEM_VAL=${WORK_MEM_MB}MB
        if grep -q \"^work_mem\" /var/lib/postgresql/data/postgresql.conf; then
            sed -i \"s/^work_mem = [0-9]*[a-zA-Z]*/work_mem = \$WORK_MEM_VAL/g\" /var/lib/postgresql/data/postgresql.conf
        elif grep -q \"^#work_mem\" /var/lib/postgresql/data/postgresql.conf; then
            sed -i \"s/^#work_mem = [0-9]*[a-zA-Z]*/work_mem = \$WORK_MEM_VAL/g\" /var/lib/postgresql/data/postgresql.conf
        else
            echo '' >> /var/lib/postgresql/data/postgresql.conf
            echo '# Work memory for operations' >> /var/lib/postgresql/data/postgresql.conf
            echo \"work_mem = \$WORK_MEM_VAL\" >> /var/lib/postgresql/data/postgresql.conf
        fi
    " || { log_error "Falha ao configurar work_mem"; return 1; }
    
    # Configurações adicionais otimizadas
    log "Aplicando configurações adicionais..."
    docker exec "$CONTAINER_NAME" sh -c "
        # shared_buffers (25% da RAM disponível, mínimo 128MB)
        SHARED_BUFFERS=\$((AVAIL_MEM * 25 / 100))
        if [ \$SHARED_BUFFERS -lt 128 ]; then SHARED_BUFFERS=128; fi
        if grep -q \"^shared_buffers\" /var/lib/postgresql/data/postgresql.conf; then
            sed -i \"s/^shared_buffers = [0-9]*[a-zA-Z]*/shared_buffers = \${SHARED_BUFFERS}MB/g\" /var/lib/postgresql/data/postgresql.conf
        else
            echo '' >> /var/lib/postgresql/data/postgresql.conf
            echo 'shared_buffers = '\${SHARED_BUFFERS}MB'' >> /var/lib/postgresql/data/postgresql.conf
        fi
        
        # effective_cache_size (50-75% da RAM)
        EFFECTIVE_CACHE=\$((AVAIL_MEM * 60 / 100))
        if grep -q \"^effective_cache_size\" /var/lib/postgresql/data/postgresql.conf; then
            sed -i \"s/^effective_cache_size = [0-9]*[a-zA-Z]*/effective_cache_size = \${EFFECTIVE_CACHE}MB/g\" /var/lib/postgresql/data/postgresql.conf
        else
            echo '' >> /var/lib/postgresql/data/postgresql.conf
            echo 'effective_cache_size = '\${EFFECTIVE_CACHE}MB'' >> /var/lib/postgresql/data/postgresql.conf
        fi
        
        # maintenance_work_mem
        if ! grep -q \"^maintenance_work_mem\" /var/lib/postgresql/data/postgresql.conf; then
            echo '' >> /var/lib/postgresql/data/postgresql.conf
            echo 'maintenance_work_mem = 64MB' >> /var/lib/postgresql/data/postgresql.conf
        fi
        
        # checkpoint_completion_target
        if ! grep -q \"^checkpoint_completion_target\" /var/lib/postgresql/data/postgresql.conf; then
            echo '' >> /var/lib/postgresql/data/postgresql.conf
            echo 'checkpoint_completion_target = 0.9' >> /var/lib/postgresql/data/postgresql.conf
        fi
    " || log_warning "Algumas configurações adicionais podem não ter sido aplicadas"
    
    # Reiniciar PostgreSQL
    log "Reiniciando PostgreSQL..."
    docker restart "$CONTAINER_NAME"
    
    # Aguardar PostgreSQL estar pronto
    log "Aguardando PostgreSQL iniciar..."
    for i in {1..30}; do
        if docker exec "$CONTAINER_NAME" pg_isready -U postgres > /dev/null 2>&1; then
            log_success "PostgreSQL está respondendo"
            break
        fi
        if [ $i -eq 30 ]; then
            log_error "PostgreSQL não está respondendo após 60 segundos"
            return 1
        fi
        sleep 2
    done
    
    # Verificar configurações
    MAX_CONN=$(docker exec "$CONTAINER_NAME" psql -U postgres -t -c "SHOW max_connections;" 2>&1 | grep -v "WARNING" | tr -d ' \n' || echo "")
    WORK_MEM=$(docker exec "$CONTAINER_NAME" psql -U postgres -t -c "SHOW work_mem;" 2>&1 | grep -v "WARNING" | tr -d ' \n' || echo "")
    
    if [ -n "$MAX_CONN" ] && [ "$MAX_CONN" != "erro" ]; then
        log_success "max_connections configurado: $MAX_CONN"
    fi
    if [ -n "$WORK_MEM" ] && [ "$WORK_MEM" != "erro" ]; then
        log_success "work_mem configurado: $WORK_MEM"
    fi
    
    log_success "PostgreSQL otimizado"
}

# Otimizar Redis
optimize_redis() {
    log "Otimizando Redis..."
    
    CONTAINER_NAME="ai_saas_redis_prod"
    MAX_MEMORY=${1:-400}
    
    if ! docker ps | grep -q "$CONTAINER_NAME"; then
        log_warning "Container Redis não está rodando, pulando otimização"
        return 0
    fi
    
    # Verificar configuração atual
    CURRENT_CMD=$(docker inspect "$CONTAINER_NAME" --format='{{.Config.Cmd}}' 2>/dev/null || echo "")
    
    # Se já tem maxmemory configurado, não fazer nada
    if echo "$CURRENT_CMD" | grep -q "maxmemory"; then
        log_warning "Redis já tem maxmemory configurado"
        return 0
    fi
    
    log "Redis será otimizado na próxima reinicialização do container"
    log "Adicione ao docker-compose.yml:"
    log "  command: redis-server --requirepass \${REDIS_PASSWORD} --maxmemory ${MAX_MEMORY}mb --maxmemory-policy allkeys-lru"
    
    log_success "Instruções de otimização do Redis fornecidas"
}

# Validar otimizações
validate_optimizations() {
    log "Validando otimizações aplicadas..."
    
    CONTAINER_NAME="ai_saas_postgres_prod"
    local errors=0
    
    # Verificar se PostgreSQL está respondendo
    if ! docker exec "$CONTAINER_NAME" pg_isready -U postgres > /dev/null 2>&1; then
        log_error "PostgreSQL não está respondendo"
        errors=$((errors + 1))
    else
        log_success "PostgreSQL está respondendo"
    fi
    
    # Verificar conexões
    CURRENT_CONN=$(docker exec "$CONTAINER_NAME" psql -U postgres -t -c "SELECT count(*) FROM pg_stat_activity;" 2>&1 | grep -v "WARNING" | tr -d ' \n' || echo "0")
    MAX_CONN=$(docker exec "$CONTAINER_NAME" psql -U postgres -t -c "SHOW max_connections;" 2>&1 | grep -v "WARNING" | tr -d ' \n' || echo "0")
    
    if [ "$CURRENT_CONN" != "0" ] && [ "$MAX_CONN" != "0" ]; then
        PERCENT=$((CURRENT_CONN * 100 / MAX_CONN))
        if [ $PERCENT -lt 80 ]; then
            log_success "Uso de conexões: $PERCENT% ($CURRENT_CONN/$MAX_CONN)"
        else
            log_warning "Uso de conexões alto: $PERCENT% ($CURRENT_CONN/$MAX_CONN)"
        fi
    fi
    
    if [ $errors -gt 0 ]; then
        log_error "Validação falhou com $errors erro(s)"
        return 1
    fi
    
    log_success "Validação concluída"
}

# Coletar métricas após otimização
collect_post_metrics() {
    log "Coletando métricas pós-otimização..."
    
    METRICS_FILE="$BACKUP_DIR/post_optimization_metrics.txt"
    
    {
        echo "=== Métricas Pós-Otimização - $(date) ==="
        echo ""
        echo "--- Sistema ---"
        free -h
        echo ""
        echo "--- CPU ---"
        top -bn1 | grep "Cpu(s)"
        echo ""
        echo "--- Docker Containers ---"
        docker stats --no-stream
        echo ""
        echo "--- PostgreSQL Connections ---"
        docker exec ai_saas_postgres_prod psql -U postgres -t -c "SELECT count(*) FROM pg_stat_activity;" 2>/dev/null || echo "N/A"
        docker exec ai_saas_postgres_prod psql -U postgres -c "SHOW max_connections;" 2>/dev/null || echo "N/A"
        docker exec ai_saas_postgres_prod psql -U postgres -c "SHOW work_mem;" 2>/dev/null || echo "N/A"
        echo ""
        echo "--- Redis Memory ---"
        docker exec ai_saas_redis_prod redis-cli INFO memory 2>/dev/null | grep used_memory_human || echo "N/A"
    } > "$METRICS_FILE"
    
    log_success "Métricas pós-otimização salvas em: $METRICS_FILE"
}

# Função principal
main() {
    echo "=========================================="
    echo "Otimização de Infraestrutura - DevOps"
    echo "=========================================="
    echo ""
    
    log "Iniciando processo de otimização..."
    log "Log: $LOG_FILE"
    log "Backup: $BACKUP_DIR"
    echo ""
    
    # Fase 1: Preparação
    check_prerequisites
    backup_configurations
    collect_baseline_metrics
    
    # Fase 2: Otimizações
    optimize_postgresql "${1:-300}" "${2:-2}"
    optimize_redis "${3:-400}"
    
    # Fase 3: Validação
    sleep 5  # Aguardar estabilização
    validate_optimizations
    collect_post_metrics
    
    echo ""
    echo "=========================================="
    log_success "Otimização concluída!"
    echo "=========================================="
    echo ""
    echo "Próximos passos:"
    echo "1. Revise as métricas em: $BACKUP_DIR"
    echo "2. Execute: ./scripts/postgres/check_postgres_connections.sh"
    echo "3. Execute: ./scripts/monitor_resources.sh"
    echo "4. Monitore por 24h antes de aplicar mais otimizações"
    echo ""
    echo "Backups salvos em: $BACKUP_DIR"
    echo "Log completo: $LOG_FILE"
    echo ""
}

# Executar
main "$@"
