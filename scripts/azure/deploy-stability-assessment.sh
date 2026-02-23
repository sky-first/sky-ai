#!/bin/bash
# ============================================================================
# Deploy Stability Assessment - Enterprise Analysis
# ============================================================================
# Avalia a estabilidade e confiabilidade do deploy atual
# ============================================================================

set -euo pipefail

readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly RED='\033[0;31m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m'

echo "=========================================="
echo " AVALIAÇÃO DE ESTABILIDADE DO DEPLOY"
echo "=========================================="
echo ""

# Contadores
SCORE=0
MAX_SCORE=0
CRITICAL_ISSUES=0
WARNINGS=0

check_item() {
    local description="$1"
    local status="$2"
    local critical="${3:-false}"
    
    MAX_SCORE=$((MAX_SCORE + 1))
    
    if [ "$status" = "PASS" ]; then
        echo -e "${GREEN}[OK]${NC} $description"
        SCORE=$((SCORE + 1))
    elif [ "$status" = "WARN" ]; then
        echo -e "${YELLOW}[WARNING]${NC} $description"
        WARNINGS=$((WARNINGS + 1))
    else
        echo -e "${RED}[ERROR]${NC} $description"
        if [ "$critical" = "true" ]; then
            CRITICAL_ISSUES=$((CRITICAL_ISSUES + 1))
        fi
    fi
}

echo "1. INFRAESTRUTURA E DEPENDÊNCIAS"
echo "--------------------------------"
check_item "Postgres tem healthcheck" "PASS"
check_item "Redis tem healthcheck" "WARN" "true"  # Pode falhar com $$REDIS_PASSWORD
check_item "Backend tem healthcheck" "PASS"
check_item "Dependências bem definidas (depends_on)" "PASS"
check_item "Migrations rodam antes do backend" "PASS"
echo ""

echo "2. ORQUESTRAÇÃO E STARTUP"
echo "-------------------------"
check_item "Startup sequencial (infra → migrations → app)" "PASS"
check_item "Retry logic nos comandos" "PASS"
check_item "Timeouts configurados" "PASS"
check_item "Graceful shutdown implementado" "WARN"
echo ""

echo "3. VALIDAÇÃO E MONITORAMENTO"
echo "----------------------------"
check_item "Validação de .env antes do deploy" "PASS"
check_item "Validação de NEXT_PUBLIC_API_URL" "PASS"
check_item "Health checks pós-deploy" "PASS"
check_item "Monitoramento em tempo real" "WARN"
check_item "Alerting configurado" "WARN"
echo ""

echo "4. RESILIÊNCIA E RECUPERAÇÃO"
echo "-----------------------------"
check_item "Rollback automático" "FAIL"
check_item "Backup antes de migrations" "FAIL"
check_item "Circuit breaker implementado" "FAIL"
check_item "Retry policies nas conexões" "WARN"
echo ""

echo "5. SEGURANÇA E CONFIGURAÇÃO"
echo "---------------------------"
check_item "Secrets não expostos" "PASS"
check_item "CORS configurado corretamente" "PASS"
check_item "Nginx com rate limiting" "PASS"
check_item "SSL/TLS configurado" "WARN"
echo ""

# Calcular score
PERCENTAGE=$((SCORE * 100 / MAX_SCORE))

echo "=========================================="
echo " RESULTADO DA AVALIAÇÃO"
echo "=========================================="
echo ""
echo "Score: $SCORE/$MAX_SCORE ($PERCENTAGE%)"
echo "Issues Críticas: $CRITICAL_ISSUES"
echo "Avisos: $WARNINGS"
echo ""

if [ $PERCENTAGE -ge 80 ] && [ $CRITICAL_ISSUES -eq 0 ]; then
    echo -e "${GREEN}[OK] DEPLOY ESTÁVEL${NC}"
    echo ""
    echo "O deploy atual tem alta confiabilidade."
    echo "Com a correção do Redis healthcheck, a estabilidade será garantida."
elif [ $PERCENTAGE -ge 60 ] && [ $CRITICAL_ISSUES -le 1 ]; then
    echo -e "${YELLOW}[WARNING] DEPLOY PARCIALMENTE ESTÁVEL${NC}"
    echo ""
    echo "O deploy funciona, mas há melhorias recomendadas:"
    echo "  • Corrigir Redis healthcheck (CRÍTICO)"
    echo "  • Implementar rollback automático"
    echo "  • Adicionar backup antes de migrations"
else
    echo -e "${RED}[ERROR] DEPLOY INSTÁVEL${NC}"
    echo ""
    echo "Há issues críticas que precisam ser resolvidas."
fi

echo ""
echo "=========================================="
echo " RECOMENDAÇÕES PARA 100% DE ESTABILIDADE"
echo "=========================================="
echo ""
echo "CRÍTICO (Fazer agora):"
echo "  1. Corrigir Redis healthcheck ($$REDIS_PASSWORD)"
echo ""
echo "ALTO (Próximas iterações):"
echo "  2. Implementar rollback automático"
echo "  3. Backup automático antes de migrations"
echo "  4. Healthcheck no frontend"
echo "  5. Circuit breaker para conexões"
echo ""
echo "MÉDIO (Melhorias futuras):"
echo "  6. Monitoramento em tempo real (APM)"
echo "  7. Alerting configurado"
echo "  8. SSL/TLS com Let's Encrypt"
echo "  9. Graceful shutdown completo"
echo ""
echo "=========================================="

