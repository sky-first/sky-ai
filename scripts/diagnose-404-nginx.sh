#!/bin/bash

# Script para diagnosticar erro 404 do nginx ingress controller
# Uso: ./scripts/diagnose-404-nginx.sh [namespace] [host]

# Não usar set -e para permitir tratamento de erros
set +e

NAMESPACE="${1:-staging}"
HOST="${2:-workspace-stg.skyfirstlabs.com}"
SERVICE_NAME="sky-fe-stg-common-app"

echo "=========================================="
echo " DIAGNÓSTICO: 404 Not Found - Nginx"
echo "=========================================="
echo ""
echo "Namespace: $NAMESPACE"
echo "Host: $HOST"
echo "Service: $SERVICE_NAME"
echo ""

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ERRORS=0
WARNINGS=0

# Função para log
log_info() {
    echo -e "${YELLOW}ℹ  $1${NC}"
}

log_success() {
    echo -e "${GREEN}[OK] $1${NC}"
}

log_error() {
    echo -e "${RED}[ERROR] $1${NC}"
    ((ERRORS++))
}

log_warning() {
    echo -e "${YELLOW}[WARNING] $1${NC}"
    ((WARNINGS++))
}

echo "=========================================="
echo "1.  Verificando Ingress"
echo "=========================================="
echo ""

# Verificar se o kubectl está configurado e conectado
if ! kubectl cluster-info &>/dev/null; then
    log_error "Não é possível conectar ao cluster Kubernetes"
    echo ""
    log_info "Verifique se você está conectado ao cluster correto:"
    echo "  kubectl config current-context"
    echo ""
    log_info "Para conectar ao cluster AKS staging, execute:"
    echo "  az aks get-credentials --resource-group <resource-group> --name <cluster-name> --overwrite-existing"
    echo ""
    exit 1
fi

# Verificar se o namespace existe
if ! kubectl get namespace "$NAMESPACE" &>/dev/null; then
    log_error "Namespace '$NAMESPACE' não existe ou não há permissão para acessá-lo"
    echo ""
    log_info "Namespaces disponíveis:"
    kubectl get namespaces 2>/dev/null | head -10
    echo ""
    exit 1
fi

# Verificar se o Ingress existe
if kubectl get ingress -n "$NAMESPACE" 2>/dev/null | grep -q "$HOST"; then
    log_success "Ingress encontrado para $HOST"
    
    # Mostrar detalhes do Ingress
    echo ""
    log_info "Detalhes do Ingress:"
    kubectl get ingress -n "$NAMESPACE" -o wide | grep "$HOST" || true
    echo ""
    
    # Verificar anotações do Ingress
    log_info "Anotações do Ingress:"
    INGRESS_NAME=$(kubectl get ingress -n "$NAMESPACE" -o jsonpath='{.items[?(@.spec.rules[*].host=="'$HOST'")].metadata.name}' 2>/dev/null | awk '{print $1}')
    if [ -n "$INGRESS_NAME" ]; then
        kubectl get ingress -n "$NAMESPACE" "$INGRESS_NAME" -o yaml | grep -A 30 "annotations:" || true
    else
        kubectl get ingress -n "$NAMESPACE" -o yaml | grep -A 20 "annotations:" || true
    fi
    echo ""
    
    # Verificar regras do Ingress
    log_info "Regras do Ingress:"
    kubectl get ingress -n "$NAMESPACE" -o yaml | grep -A 10 "rules:" || true
    echo ""
else
    log_error "Ingress NÃO encontrado para $HOST no namespace $NAMESPACE"
    echo ""
    log_info "Ingresses disponíveis no namespace $NAMESPACE:"
    kubectl get ingress -n "$NAMESPACE" 2>/dev/null || log_error "Erro ao listar ingresses"
    echo ""
    log_info "Todos os ingresses (todos os namespaces):"
    kubectl get ingress --all-namespaces 2>/dev/null | grep -i "$(echo $HOST | cut -d. -f1)" || true
fi

echo ""
echo "=========================================="
echo "2.  Verificando Service"
echo "=========================================="
echo ""

# Verificar se o serviço existe
if kubectl get svc -n "$NAMESPACE" "$SERVICE_NAME" &>/dev/null; then
    log_success "Service $SERVICE_NAME encontrado"
    
    # Mostrar detalhes do serviço
    echo ""
    log_info "Detalhes do Service:"
    kubectl get svc -n "$NAMESPACE" "$SERVICE_NAME" -o wide
    echo ""
    
    # Verificar se o serviço tem endpoints
    ENDPOINTS=$(kubectl get endpoints -n "$NAMESPACE" "$SERVICE_NAME" -o jsonpath='{.subsets[*].addresses[*].ip}' 2>/dev/null || echo "")
    if [ -n "$ENDPOINTS" ]; then
        log_success "Service tem endpoints: $ENDPOINTS"
    else
        log_error "Service NÃO tem endpoints (pods não estão conectados ao serviço)"
    fi
    echo ""
else
    log_error "Service $SERVICE_NAME NÃO encontrado no namespace $NAMESPACE"
    echo ""
    log_info "Services disponíveis:"
    kubectl get svc -n "$NAMESPACE" 2>/dev/null | head -10
fi

echo ""
echo "=========================================="
echo "3.  Verificando Pods"
echo "=========================================="
echo ""

# Verificar pods do frontend
PODS=$(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=common-app -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || echo "")

if [ -z "$PODS" ]; then
    # Tentar encontrar pods por nome
    PODS=$(kubectl get pods -n "$NAMESPACE" | grep -E "(frontend|fe)" | awk '{print $1}' || echo "")
fi

if [ -n "$PODS" ]; then
    log_success "Pods encontrados: $(echo $PODS | wc -w)"
    echo ""
    
    for pod in $PODS; do
        log_info "Pod: $pod"
        
        # Status do pod
        STATUS=$(kubectl get pod -n "$NAMESPACE" "$pod" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
        READY=$(kubectl get pod -n "$NAMESPACE" "$pod" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "Unknown")
        
        if [ "$STATUS" = "Running" ] && [ "$READY" = "True" ]; then
            log_success "  Status: $STATUS, Ready: $READY"
        else
            log_error "  Status: $STATUS, Ready: $READY"
        fi
        
        # Verificar logs recentes para erros
        echo ""
        log_info "  Últimas linhas dos logs (últimos 5 erros):"
        kubectl logs -n "$NAMESPACE" "$pod" --tail=100 2>&1 | grep -i "error\|404\|not found" | tail -5 || log_info "  Nenhum erro encontrado nos logs recentes"
        echo ""
    done
else
    log_error "Nenhum pod do frontend encontrado no namespace $NAMESPACE"
    echo ""
    log_info "Todos os pods no namespace:"
    kubectl get pods -n "$NAMESPACE" 2>/dev/null | head -10
fi

echo ""
echo "=========================================="
echo "4.  Verificando Roteamento do Ingress"
echo "=========================================="
echo ""

# Verificar se há conflitos de path
log_info "Verificando conflitos de path no mesmo host..."
INGRESS_PATHS=$(kubectl get ingress -n "$NAMESPACE" -o jsonpath='{.items[*].spec.rules[?(@.host=="'$HOST'")].http.paths[*].path}' 2>/dev/null || echo "")

if [ -n "$INGRESS_PATHS" ]; then
    log_info "Paths configurados para $HOST:"
    echo "$INGRESS_PATHS" | tr ' ' '\n' | sort -u
    echo ""
    
    # Verificar se há path /api que pode estar capturando requisições
    if echo "$INGRESS_PATHS" | grep -q "/api"; then
        log_warning "Path /api encontrado - pode estar interferindo com rotas do frontend"
        log_info "Paths mais específicos têm precedência sobre paths menos específicos"
    fi
else
    log_warning "Não foi possível verificar paths do Ingress"
fi

echo ""
echo "=========================================="
echo "5.  Teste de Conectividade"
echo "=========================================="
echo ""

# Verificar se conseguimos acessar o serviço diretamente (se estiver no cluster)
log_info "Testando conectividade com o serviço..."
SERVICE_IP=$(kubectl get svc -n "$NAMESPACE" "$SERVICE_NAME" -o jsonpath='{.spec.clusterIP}' 2>/dev/null || echo "")
SERVICE_PORT=$(kubectl get svc -n "$NAMESPACE" "$SERVICE_NAME" -o jsonpath='{.spec.ports[0].port}' 2>/dev/null || echo "80")

if [ -n "$SERVICE_IP" ]; then
    log_info "Service ClusterIP: $SERVICE_IP:$SERVICE_PORT"
    log_info "Para testar dentro do cluster, execute:"
    echo "  kubectl run -it --rm debug --image=curlimages/curl --restart=Never -- curl http://$SERVICE_NAME.$NAMESPACE.svc.cluster.local:$SERVICE_PORT/"
else
    log_warning "Não foi possível obter IP do serviço"
fi

echo ""
echo "=========================================="
echo " RESUMO"
echo "=========================================="
echo ""
echo "Erros encontrados: $ERRORS"
echo "Avisos: $WARNINGS"
echo ""

if [ $ERRORS -eq 0 ]; then
    log_success "Não foram encontrados erros críticos"
    echo ""
    log_info "Próximos passos:"
    echo "  1. Verifique se o ArgoCD sincronizou as mudanças recentes"
    echo "  2. Verifique os logs dos pods do frontend para erros específicos"
    echo "  3. Teste acessar o serviço diretamente (se possível)"
    echo "  4. Verifique se o Next.js está configurado corretamente para roteamento client-side"
else
    log_error "Foram encontrados $ERRORS erro(s) que precisam ser corrigidos"
    echo ""
    log_info "Ações recomendadas:"
    echo "  1. Corrija os erros listados acima"
    echo "  2. Verifique se os pods estão rodando e saudáveis"
    echo "  3. Verifique se o serviço tem endpoints válidos"
    echo "  4. Verifique se o Ingress está configurado corretamente"
fi

echo ""
echo "=========================================="
echo " COMANDOS ÚTEIS"
echo "=========================================="
echo ""
echo "Ver logs do frontend:"
echo "  kubectl logs -n $NAMESPACE -l app.kubernetes.io/name=common-app --tail=100"
echo ""
echo "Descrever Ingress:"
echo "  kubectl describe ingress -n $NAMESPACE | grep -A 20 '$HOST'"
echo ""
echo "Descrever Service:"
echo "  kubectl describe svc -n $NAMESPACE $SERVICE_NAME"
echo ""
echo "Ver eventos do namespace:"
echo "  kubectl get events -n $NAMESPACE --sort-by='.lastTimestamp' | tail -20"
echo ""
