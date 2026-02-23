#!/bin/bash

# Script: Validar aplicações em Produção
# Purpose: Verificar status de todos os pods, databases, e integrações
# Usage: ./scripts/validate-applications-prod.sh

set -e

NAMESPACE="prod"

echo "[OK] Validando Aplicações em Produção"
echo ""

# 1. Verificar Pods Status
echo "1.  Status dos Pods em $NAMESPACE..."
echo ""
kubectl get pods -n $NAMESPACE -o wide || {
    echo "[ERROR] Nenhum pod encontrado em $NAMESPACE"
    exit 1
}

echo ""
echo "2.  Verificar replicas e readiness..."
echo ""
echo "Backend Deployment:"
kubectl get deployment -n $NAMESPACE -l app=backend -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.replicas}/{.status.readyReplicas}{"\n"}{end}'

echo ""
echo "Frontend Deployment:"
kubectl get deployment -n $NAMESPACE -l app=frontend -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.replicas}/{.status.readyReplicas}{"\n"}{end}'

echo ""
echo "AI Engine Deployment:"
kubectl get deployment -n $NAMESPACE -l app=ai -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.replicas}/{.status.readyReplicas}{"\n"}{end}'

# 3. Verificar Database StatefulSets
echo ""
echo "3.  Verificar Databases..."
echo ""
echo "PostgreSQL StatefulSet:"
kubectl get statefulset -n $NAMESPACE -l app=postgresql -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.replicas}/{.status.readyReplicas}{"\n"}{end}'

echo ""
echo "Redis StatefulSet:"
kubectl get statefulset -n $NAMESPACE -l app=redis -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.replicas}/{.status.readyReplicas}{"\n"}{end}'

# 4. Verificar PVCs (Persistent Volumes)
echo ""
echo "4.  Verificar Persistent Volumes..."
echo ""
kubectl get pvc -n $NAMESPACE

# 5. Verificar Secrets sincronizados
echo ""
echo "5.  Verificar ExternalSecrets..."
echo ""
kubectl get externalsecrets -n $NAMESPACE || echo "[WARNING] Nenhum ExternalSecret encontrado"

echo ""
echo "Secrets criados:"
kubectl get secrets -n $NAMESPACE | grep -E "^[a-z]" | wc -l
echo "secrets encontrados"

# 6. Verificar Services
echo ""
echo "6.  Verificar Services..."
echo ""
kubectl get svc -n $NAMESPACE

# 7. Verificar ConfigMaps
echo ""
echo "7.  Verificar ConfigMaps..."
echo ""
kubectl get configmap -n $NAMESPACE

# 8. Verificar Health dos Pods
echo ""
echo "8.  Verificar logs dos pods para erros..."
echo ""
echo "Últimos erros encontrados (últimos 5 min):"
kubectl logs -n $NAMESPACE --all-containers=true --timestamps=true --since=5m | grep -i error | tail -5 || echo "[OK] Nenhum erro encontrado"

# 9. Test básico Backend
echo ""
echo "9.  Testar conectividade Backend (port-forward)..."
echo ""
echo "Você pode testar com:"
echo "  kubectl port-forward svc/sky-backend-prod-common-app 8000:80 -n $NAMESPACE &"
echo "  curl http://localhost:8000/api/v1/health"

# 10. Resumo
echo ""
echo "========================================="
echo "[OK] Validação de Aplicações Completa!"
echo "========================================="
echo ""
echo "Próximos passos:"
echo "1. Verificar logs: kubectl logs <pod-name> -n $NAMESPACE"
echo "2. Port-forward para testes locais"
echo "3. Validar Database connectivity"
echo "4. Testar API endpoints"
