#!/bin/bash

# Script: Validar HTTPS e TLS em Produção
# Purpose: Verificar se certificados foram emitidos e HTTPS está funcionando
# Usage: ./scripts/validate-https-prod.sh

set -e

NAMESPACE="prod"

echo " Validando HTTPS e TLS para ambiente de produção"
echo ""

# 1. Verificar Cert-Manager
echo "1.  Verificando Cert-Manager deployment..."
kubectl get deployment -n cert-manager cert-manager --no-headers || {
    echo "[ERROR] Cert-Manager não encontrado"
    echo "Execute: argocd app sync sky-cert-manager-prod"
    exit 1
}

# 2. Listar Certificates criados
echo ""
echo "2.  Verificando Certificates emitidos..."
kubectl get certificate -n $NAMESPACE || {
    echo "[WARNING] Nenhum Certificate encontrado em $NAMESPACE"
}

# 3. Verificar secrets TLS
echo ""
echo "3.  Verificando TLS Secrets..."
echo "Frontend TLS:"
kubectl get secret workspace-prd-tls -n $NAMESPACE -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -text -noout | grep -E "Subject:|Issuer:|Not Before|Not After" || echo "[ERROR] workspace-prd-tls não encontrado"

echo ""
echo "Backend TLS:"
kubectl get secret backend-prd-tls -n $NAMESPACE -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -text -noout | grep -E "Subject:|Issuer:|Not Before|Not After" || echo "[ERROR] backend-prd-tls não encontrado"

echo ""
echo "AI TLS:"
kubectl get secret ai-prd-tls -n $NAMESPACE -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -text -noout | grep -E "Subject:|Issuer:|Not Before|Not After" || echo "[ERROR] ai-prd-tls não encontrado"

# 4. Verificar Ingress
echo ""
echo "4.  Verificando Ingress resources..."
kubectl get ingress -n $NAMESPACE || echo "[ERROR] Nenhum Ingress encontrado"

# 5. Obter IP do Load Balancer
echo ""
echo "5.  Obtendo IP do Load Balancer (Nginx Ingress)..."
LB_IP=$(kubectl get svc -n ingress-nginx ingress-nginx-controller -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "PENDING")

if [ "$LB_IP" != "PENDING" ] && [ -n "$LB_IP" ]; then
    echo "[OK] Load Balancer IP: $LB_IP"
    echo ""
    echo "6.  Para usar em produção, configure DNS:"
    echo "  workspace-prd.skyfirstlabs.com          -> $LB_IP"
    echo "  api-workspace-prd.skyfirstlabs.com      -> $LB_IP"
    echo "  workspace-prd-ai.skyfirstlabs.com       -> $LB_IP"
else
    echo " Load Balancer IP ainda não atribuído (aguardando Azure)"
    echo "   Este é normal - pode levar alguns minutos"
    echo "   Verifique novamente em 2-3 minutos"
fi

# 7. Testar HTTPS (se LB IP estiver disponível)
if [ "$LB_IP" != "PENDING" ] && [ -n "$LB_IP" ]; then
    echo ""
    echo "7.  Testando conectividade HTTPS..."
    echo ""
    echo "Testing frontend:"
    curl -kI https://$LB_IP/ -H "Host: workspace-prd.skyfirstlabs.com" 2>/dev/null | head -5 || echo "[WARNING] Frontend não respondeu"
    
    echo ""
    echo "Testing backend:"
    curl -kI https://$LB_IP/api/v1/health -H "Host: api-workspace-prd.skyfirstlabs.com" 2>/dev/null | head -5 || echo "[WARNING] Backend não respondeu"
    
    echo ""
    echo "Testing AI:"
    curl -kI https://$LB_IP/ -H "Host: workspace-prd-ai.skyfirstlabs.com" 2>/dev/null | head -5 || echo "[WARNING] AI não respondeu"
fi

echo ""
echo "[OK] Validação de HTTPS completa!"
echo ""
echo "Próximo passo: Configurar DNS para apontar subdomínios ao LB IP"
