#!/bin/bash

# Script: Health Check Completo de Produção
# Purpose: Validar saúde geral do cluster e aplicações
# Usage: ./scripts/health-check-prod.sh

set -e

echo "🏥 Health Check Completo - Ambiente de Produção"
echo "================================================="
echo ""

# 1. Verificar Nodes
echo "1.  Status dos Nodes..."
NODES=$(kubectl get nodes --no-headers | wc -l)
READY=$(kubectl get nodes -o jsonpath='{range .items[?(@.status.conditions[?(@.type=="Ready")].status=="True")]}.metadata.name{"\n"}{end}' | wc -l)

if [ "$NODES" -eq "$READY" ]; then
    echo "[OK] Todos os $NODES nodes estão ready"
else
    echo "[ERROR] Apenas $READY/$NODES nodes estão ready"
    exit 1
fi

# 2. Verificar Namespaces
echo ""
echo "2.  Verificando Namespaces..."
for ns in prod monitoring external-secrets argocd cert-manager; do
    if kubectl get namespace $ns &>/dev/null; then
        echo "[OK] Namespace $ns existe"
    else
        echo "[WARNING] Namespace $ns não encontrado"
    fi
done

# 3. Verificar Pods críticos
echo ""
echo "3.  Pods críticos..."
CRITICAL_PODS=(
    "prod:backend"
    "prod:frontend"
    "prod:postgresql"
    "prod:redis"
    "monitoring:prometheus"
    "monitoring:grafana"
    "argocd:argocd-server"
)

for pod_spec in "${CRITICAL_PODS[@]}"; do
    IFS=':' read -r ns label <<< "$pod_spec"
    RUNNING=$(kubectl get pods -n $ns -l app=$label -o jsonpath='{.items[?(@.status.phase=="Running")]}' | wc -l)
    if [ "$RUNNING" -gt 0 ]; then
        echo "[OK] $ns/$label: $RUNNING pods running"
    else
        echo "[ERROR] $ns/$label: Nenhum pod running"
    fi
done

# 4. Verificar PVCs
echo ""
echo "4.  Persistent Volumes..."
BOUND_PVCS=$(kubectl get pvc --all-namespaces -o jsonpath='{range .items[?(@.status.phase=="Bound")]}.metadata.namespace{"\n"}{end}' | wc -l)
UNBOUND_PVCS=$(kubectl get pvc --all-namespaces -o jsonpath='{range .items[?(@.status.phase!="Bound")]}.metadata.namespace{"\n"}{end}' | wc -l)

echo "[OK] $BOUND_PVCS PVCs bound"
if [ "$UNBOUND_PVCS" -gt 0 ]; then
    echo "[WARNING] $UNBOUND_PVCS PVCs unbound"
fi

# 5. Verificar Secrets
echo ""
echo "5.  ExternalSecrets sincronizados..."
SYNCED=$(kubectl get externalsecrets -n prod -o jsonpath='{range .items[?(@.status.conditions[?(@.type=="Ready")].status=="True")]}.metadata.name{"\n"}{end}' | wc -l)
TOTAL=$(kubectl get externalsecrets -n prod -o jsonpath='{range .items[*]}.metadata.name{"\n"}{end}' | wc -l)

if [ "$SYNCED" -eq "$TOTAL" ] && [ "$TOTAL" -gt 0 ]; then
    echo "[OK] Todos os $TOTAL ExternalSecrets sincronizados"
elif [ "$TOTAL" -eq 0 ]; then
    echo "[WARNING] Nenhum ExternalSecret encontrado (podem não estar aplicados ainda)"
else
    echo "[WARNING] $SYNCED/$TOTAL ExternalSecrets sincronizados"
fi

# 6. Verificar Ingress
echo ""
echo "6.  Ingress e Certificados..."
INGRESS=$(kubectl get ingress -n prod --no-headers | wc -l)
echo "[OK] $INGRESS Ingress resources em prod"

CERTS=$(kubectl get certificate -n prod --no-headers 2>/dev/null | wc -l)
if [ "$CERTS" -gt 0 ]; then
    echo "[OK] $CERTS Certificates configurados"
else
    echo "[WARNING] Nenhum Certificate encontrado (Cert-Manager pode não estar aplicado)"
fi

# 7. Verificar Services
echo ""
echo "7.  Services..."
kubectl get svc -n prod -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.type}{"\n"}{end}' | while read svc type; do
    echo "  $svc ($type)"
done

# 8. Verificar DNS (LoadBalancer)
echo ""
echo "8.  LoadBalancer IP..."
LB_IP=$(kubectl get svc -n ingress-nginx ingress-nginx-controller -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "PENDING")
if [ "$LB_IP" != "PENDING" ] && [ -n "$LB_IP" ]; then
    echo "[OK] LoadBalancer IP: $LB_IP"
    echo "   Configure DNS para apontar:"
    echo "   - workspace-prd.skyfirstlabs.com -> $LB_IP"
    echo "   - api-workspace-prd.skyfirstlabs.com -> $LB_IP"
    echo "   - workspace-prd-ai.skyfirstlabs.com -> $LB_IP"
else
    echo "⏳ LoadBalancer IP pendente (aguardando Azure)"
fi

# 9. Erros recentes
echo ""
echo "9.  Erros recentes (últimos 10 min)..."
ERROR_COUNT=$(kubectl logs --all-namespaces --all-containers=true --timestamps=true --since=10m 2>/dev/null | grep -i error | wc -l || echo "0")
if [ "$ERROR_COUNT" -eq 0 ]; then
    echo "[OK] Nenhum erro encontrado"
else
    echo "[WARNING] $ERROR_COUNT erros encontrados"
    kubectl logs --all-namespaces --all-containers=true --timestamps=true --since=10m 2>/dev/null | grep -i error | head -3
fi

# 10. Resumo
echo ""
echo "========================================="
echo "[OK] Health Check Completo!"
echo "========================================="
echo ""
echo "Próximos passos:"
echo "1. Se LoadBalancer IP está 'PENDING': aguarde 2-3 minutos e tente novamente"
echo "2. Configure DNS quando LoadBalancer IP estiver disponível"
echo "3. Teste HTTPS: https://workspace-prd.skyfirstlabs.com"
echo "4. Acesse Grafana: http://localhost:3000 (port-forward)"
echo "5. Verifique logs se houver erros"
