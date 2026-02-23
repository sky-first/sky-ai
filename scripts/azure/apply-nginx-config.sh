#!/bin/bash
# DEVOPS: Aplica nginx.conf HTTP-only ou HTTPS baseado na presença de certificados SSL
# Se certificados existirem, usa nginx.conf.secure (HTTPS com redirect HTTP->HTTPS)
# Se não existirem, usa nginx.conf.http-only (HTTP apenas)
# Garante que nginx sempre funcione

set -eu

PROJECT_DIR="${1:-/home/azureuser/projeto/sky-poc-infra}"
cd "$PROJECT_DIR" || {
    if [ -d ~/projeto/sky-poc-infra ]; then
        cd ~/projeto/sky-poc-infra
    elif [ -d ~/projeto/poc-deploy ]; then
        cd ~/projeto/poc-deploy
    else
        echo "[ERROR] ERRO: Diretório do projeto não encontrado"
        exit 1
    fi
}

NGINX_CONF="docker/nginx/nginx.conf"
NGINX_HTTP_ONLY="docker/nginx/nginx.conf.http-only"
NGINX_SECURE="docker/nginx/nginx.conf.secure"
CERTS_DIR="certs"

echo "=========================================="
echo " Configurando Nginx"
echo "=========================================="
echo ""

# Criar diretório se não existir
mkdir -p docker/nginx

# Verificar se certificados SSL existem
HAS_CERTS=false
if [ -d "$CERTS_DIR" ] && [ -f "$CERTS_DIR/fullchain.pem" ] && [ -f "$CERTS_DIR/privkey.pem" ]; then
    HAS_CERTS=true
    echo "[OK] Certificados SSL encontrados em $CERTS_DIR"
else
    echo "[WARNING] Certificados SSL não encontrados em $CERTS_DIR"
    echo "[INFO] Dica: Execute scripts/azure/generate-self-signed-certs.sh para gerar certificados auto-assinados (POC)"
fi

# Aplicar configuração baseada na presença de certificados
if [ "$HAS_CERTS" = "true" ]; then
    echo " Aplicando configuração HTTPS..."
    if [ -f "$NGINX_SECURE" ]; then
        # Fazer backup do nginx.conf atual
        if [ -f "$NGINX_CONF" ]; then
            cp "$NGINX_CONF" "${NGINX_CONF}.backup.$(date +%Y%m%d_%H%M%S)" 2>/dev/null || true
        fi
        # Copiar nginx.conf.secure para nginx.conf
        cp "$NGINX_SECURE" "$NGINX_CONF"
        echo "[OK] nginx.conf HTTPS aplicado (redirect HTTP->HTTPS habilitado)"
    else
        echo "[ERROR] ERRO: $NGINX_SECURE não encontrado"
        exit 1
    fi
else
    echo "[WARNING] Certificados SSL não encontrados - usando configuração HTTP-only"
    if [ -f "$NGINX_HTTP_ONLY" ]; then
        echo "Aplicando configuração HTTP-only..."
        # Fazer backup do nginx.conf atual
        if [ -f "$NGINX_CONF" ]; then
            cp "$NGINX_CONF" "${NGINX_CONF}.backup.$(date +%Y%m%d_%H%M%S)" 2>/dev/null || true
        fi
        # Copiar nginx.conf.http-only para nginx.conf
        cp "$NGINX_HTTP_ONLY" "$NGINX_CONF"
        echo "[OK] nginx.conf HTTP-only aplicado (sem redirect HTTPS)"
    else
        # Criar nginx.conf HTTP-only básico se não existir
        echo "Criando nginx.conf HTTP-only básico..."
        cat > "$NGINX_CONF" << 'NGINXEOF'
server {
  listen 80;
  server_name _;
  
  resolver 127.0.0.11 ipv6=off valid=10s;
  set $frontend_upstream "frontend:3000";
  set $backend_upstream "backend:8000";
  
  location /api/v1/ {
    proxy_pass http://$backend_upstream;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  }
  
  location /health {
    proxy_pass http://$backend_upstream/health;
    access_log off;
  }
  
  location / {
    proxy_pass http://$frontend_upstream;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  }
}
NGINXEOF
        echo "[OK] nginx.conf HTTP-only criado"
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
    echo "[OK] Configuração do nginx válida"
else
    echo "[ERROR] ERRO: Configuração do nginx inválida"
    echo "[INFO] Dica: execute para ver o erro completo:"
    echo "   docker run --rm --add-host frontend:127.0.0.1 --add-host backend:127.0.0.1 -v \"\$(pwd)/docker/nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro\" nginx:1.25-alpine nginx -t"
    exit 1
fi

echo ""
echo "=========================================="
echo "[OK] Nginx Configurado"
echo "=========================================="

