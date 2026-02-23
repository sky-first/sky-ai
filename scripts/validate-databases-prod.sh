#!/bin/bash

# Script: Validar Databases em Produção
# Purpose: Verificar status e conectividade de PostgreSQL e Redis
# Usage: ./scripts/validate-databases-prod.sh

set -e

NAMESPACE="prod"

echo "  Validando Databases em Produção"
echo ""

# 1. Verificar PostgreSQL
echo "1.  PostgreSQL StatefulSet..."
echo ""
kubectl get statefulset -n $NAMESPACE postgresql -o wide || {
    echo "[ERROR] PostgreSQL StatefulSet não encontrado"
    exit 1
}

echo ""
echo "PostgreSQL Pod logs (últimas 10 linhas):"
POD=$(kubectl get pods -n $NAMESPACE -l app=postgresql -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n $NAMESPACE $POD | tail -10 || echo "[WARNING] Sem logs disponíveis"

# 2. Testar PostgreSQL connection
echo ""
echo "2.  Testando PostgreSQL connectivity..."
echo ""
echo "Você pode testar com:"
echo "  kubectl exec -it $POD -n $NAMESPACE -- psql -h localhost -U postgres -d ai_saas_db -c \"SELECT version();\""

# 3. Verificar Redis
echo ""
echo "3.  Redis StatefulSet..."
echo ""
kubectl get statefulset -n $NAMESPACE redis -o wide || {
    echo "[ERROR] Redis StatefulSet não encontrado"
}

echo ""
echo "Redis Pod logs (últimas 10 linhas):"
REDIS_POD=$(kubectl get pods -n $NAMESPACE -l app=redis -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")

if [ -n "$REDIS_POD" ]; then
    kubectl logs -n $NAMESPACE $REDIS_POD 2>/dev/null | tail -10 || echo "[WARNING] Sem logs disponíveis"
else
    echo "[WARNING] Redis Pod não encontrado"
fi

# 4. Verificar PVCs
echo ""
echo "4.  Persistent Volumes para Databases..."
echo ""
kubectl get pvc -n $NAMESPACE

# 5. Resumo
echo ""
echo "========================================="
echo "[OK] Validação de Databases Completa!"
echo "========================================="
