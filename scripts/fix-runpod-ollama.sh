#!/bin/bash

# =================================================================
# SCRIPT DE RECUPERAÇÃO OLLAMA - RUNPOD
# Este script deve ser executado DENTRO do Pod do RunPod.
# Ele garante que o Ollama está rodando e acessível via porta 19123.
# =================================================================

echo "🚀 Iniciando recuperação do ambiente Ollama..."

# 1. Garantir que o Ollama está rodando
if pgrep ollama > /dev/null; then
    echo "✅ Ollama já está em execução."
else
    echo "⚠️ Ollama não encontrado. Iniciando..."
    export OLLAMA_HOST=0.0.0.0:11434
    nohup ollama serve > /root/ollama.log 2>&1 &
    sleep 5
    echo "✅ Ollama iniciado em background."
fi

# 2. Liberar a porta 19123 (usada pelo domínio do RunPod)
# Normalmente ocupada pelo 'gotty' em Pods novos.
echo "Staging: Liberando porta 19123..."
PID_19123=$(lsof -t -i:19123)
if [ ! -z "$PID_19123" ]; then
    echo "Stopping process $PID_19123 on port 19123..."
    kill -9 $PID_19123
fi

# 3. Configurar o Nginx como Proxy reverso
# Isso mapeia o domínio público (que aponta para 19123) para o Ollama (11434)
if [ -f /etc/nginx/nginx.conf ]; then
    echo "🔧 Configurando Nginx Proxy..."
    
    # Criar backup se não existir
    [ ! -f /etc/nginx/nginx.conf.bak ] && cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.bak
    
    # Verificar se a configuração já existe
    if ! grep -q "listen 19123" /etc/nginx/nginx.conf; then
        sed -i '/http {/a \    server {\n        listen 19123;\n        location / {\n            proxy_pass http://localhost:11434;\n            proxy_set_header Host \$host;\n            proxy_set_header X-Real-IP \$remote_addr;\n        }\n    }' /etc/nginx/nginx.conf
        echo "✅ Configuração adicionada ao nginx.conf"
    else
        echo "ℹ️ Configuração já presente no nginx.conf"
    fi
    
    nginx -s reload
    echo "✅ Nginx recarregado."
else
    echo "❌ Erro: nginx.conf não encontrado em /etc/nginx/"
fi

echo "----------------------------------------------------"
echo "🏁 Recuperação concluída!"
echo "Teste agora no seu PC local:"
echo "curl https://\${RUNPOD_POD_ID}-19123.proxy.runpod.net/api/tags"
echo "----------------------------------------------------"
