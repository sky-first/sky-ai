#!/bin/bash
# Script de Conexão ao Cluster AKS + Ollama
# Executar após receber acesso ao cluster

set -e

echo "🔐 Conectando ao Cluster AKS Sky..."
echo ""

# 1. Login na Azure
echo "Passo 1/3: Login na Azure"
az login

# 2. Baixar credenciais do cluster
echo ""
echo "Passo 2/3: Configurando kubectl"
az aks get-credentials --resource-group sky-aks-staging-rg --name sky-aks-staging

# 3. Verificar conexão
echo ""
echo "Passo 3/3: Testando conexão"
kubectl get pods -n ollama

echo ""
echo "✅ Conexão estabelecida com sucesso!"
echo ""
echo "Próximo passo: execute ./scripts/ollama-port-forward.sh"
