#!/bin/bash
# Setup Simples do Ollama no RunPod - SEM NGINX!
set -e

echo "=== Instalando Ollama ==="
curl -fsSL https://ollama.com/install.sh | sh

echo "=== Iniciando Ollama na porta 19123 ==="
export OLLAMA_HOST=0.0.0.0:19123
nohup ollama serve > /tmp/ollama.log 2>&1 &
sleep 5

echo "=== Baixando modelos ==="
ollama pull nomic-embed-text
ollama pull phi3:medium
ollama pull phi3:mini

echo "=== Verificando configuração ==="
ss -tlnp | grep 19123
curl http://127.0.0.1:19123/api/tags

echo ""
echo "=== ✅ PRONTO! ==="
echo "URL pública: https://r3j02klu1kl8w1-19123.proxy.runpod.net"
