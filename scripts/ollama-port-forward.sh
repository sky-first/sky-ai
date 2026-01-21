#!/bin/bash
# Port-Forward do Ollama (Cluster → localhost:11434)
# Mantenha este script rodando enquanto usar o Ollama do cluster

echo "🔌 Iniciando Port-Forward do Ollama..."
echo "URL: http://localhost:11434"
echo ""
echo "⚠️  Mantenha este terminal aberto"
echo "   Para parar: Ctrl+C"
echo ""

kubectl port-forward svc/ollama-service -n ollama 11434:11434
