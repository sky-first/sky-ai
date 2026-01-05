#!/bin/bash
# Aplica nginx.conf HTTP-only se certificados SSL não existirem
# Garante que nginx sempre funcione

set -eu

PROJECT_DIR="${1:-/home/azureuser/projeto/sky-poc-infra}"
cd "$PROJECT_DIR" || {
    if [ -d ~/projeto/sky-poc-infra ]; then
        cd ~/projeto/sky-poc-infra
    elif [ -d ~/projeto/poc-deploy ]; then
        cd ~/projeto/poc-deploy
    else
        echo "❌ ERRO: Diretório do projeto não encontrado"
        exit 1
    fi
}

NGINX_CONF="docker/nginx/nginx.conf"
NGINX_HTTP_ONLY="docker/nginx/nginx.conf.http-only"
CERTS_DIR="certs"

echo "=========================================="
echo "🔧 Configurando Nginx"
echo "=========================================="
echo ""

# Criar diretório se não existir
mkdir -p docker/nginx

# Verificar se certificados SSL existem
HAS_CERTS=false
if [ -d "$CERTS_DIR" ] && [ -f "$CERTS_DIR/fullchain.pem" ] && [ -f "$CERTS_DIR/privkey.pem" ]; then
    HAS_CERTS=true
    echo "✅ Certificados SSL encontrados"
else
    echo "⚠️  Certificados SSL não encontrados"
fi

# Se não tem certificados, usar HTTP-only
if [ "$HAS_CERTS" = "false" ]; then
    echo "⚠️  Certificados SSL não encontrados - usando configuração HTTP-only"
    if [ -f "$NGINX_HTTP_ONLY" ]; then
        echo "Aplicando configuração HTTP-only..."
        # Fazer backup do nginx.conf atual
        if [ -f "$NGINX_CONF" ]; then
            cp "$NGINX_CONF" "${NGINX_CONF}.backup.$(date +%Y%m%d_%H%M%S)" 2>/dev/null || true
        fi
        # Copiar nginx.conf.http-only para nginx.conf
        cp "$NGINX_HTTP_ONLY" "$NGINX_CONF"
        echo "✅ nginx.conf HTTP-only aplicado (sem redirect HTTPS)"
    else
        # Criar nginx.conf HTTP-only básico se não existir
        echo "Criando nginx.conf HTTP-only..."
        cat > "$NGINX_CONF" << 'NGINXEOF'
server {
  listen 80;
  server_name _;
  
  location /api/ {
    proxy_pass http://backend:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  }
  
  location /health {
    proxy_pass http://backend:8000/health;
    access_log off;
  }
  
  location / {
    proxy_pass http://frontend:3000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  }
}
NGINXEOF
        echo "✅ nginx.conf HTTP-only criado"
    fi
else
    # Se tem certificados, verificar se nginx.conf está configurado para HTTPS
    if grep -q "return 301 https" "$NGINX_CONF" && ! grep -q "# return 301 https" "$NGINX_CONF"; then
        echo "✅ nginx.conf configurado para HTTPS"
    else
        echo "⚠️  nginx.conf não está redirecionando para HTTPS"
    fi
fi

# Validar configuração
# NOTA: este script valida via `docker run nginx -t` fora da rede do docker compose.
# Por isso, hostnames como `frontend` e `backend` (usados em proxy_pass) não resolvem DNS
# durante o teste. Para evitar falso negativo, adicionamos entradas temporárias de hosts.
if docker run --rm \
    --add-host frontend:127.0.0.1 \
    --add-host backend:127.0.0.1 \
    -v "$(pwd)/docker/nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro" \
    nginx:1.25-alpine nginx -t 2>&1 | grep -q "successful"; then
    echo "✅ Configuração do nginx válida"
else
    echo "❌ ERRO: Configuração do nginx inválida"
    echo "💡 Dica: execute para ver o erro completo:"
    echo "   docker run --rm --add-host frontend:127.0.0.1 --add-host backend:127.0.0.1 -v \"\$(pwd)/docker/nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro\" nginx:1.25-alpine nginx -t"
    exit 1
fi

echo ""
echo "=========================================="
echo "✅ Nginx Configurado"
echo "=========================================="

