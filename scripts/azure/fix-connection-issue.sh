#!/bin/bash
# Script para diagnosticar e corrigir problema de conexão recusada
# Pode ser executado via Azure CLI Run Command ou SSH direto

set -eu

PROJECT_DIR="${PROJECT_DIR:-/home/azureuser/projeto/sky-poc-infra}"
cd "$PROJECT_DIR" || {
    # Tentar encontrar o diretório
    if [ -d ~/projeto/sky-poc-infra ]; then
        cd ~/projeto/sky-poc-infra
    elif [ -d ~/projeto/poc-deploy ]; then
        cd ~/projeto/poc-deploy
    else
        echo "❌ ERRO: Diretório do projeto não encontrado"
        exit 1
    fi
}

echo "=========================================="
echo "🔍 DIAGNÓSTICO: Conexão Recusada"
echo "=========================================="
echo ""

# 1. Verificar containers
echo "1️⃣ Verificando containers..."
echo "----------------------------------------"
if command -v docker &> /dev/null; then
    echo "Status dos containers:"
    sudo docker compose ps || sudo docker-compose ps || {
        echo "⚠️ docker compose não encontrado, tentando docker ps..."
        sudo docker ps
    }
    echo ""
else
    echo "❌ Docker não está instalado ou não está no PATH"
    exit 1
fi

# 2. Verificar nginx/proxy
echo "2️⃣ Verificando nginx/proxy..."
echo "----------------------------------------"
PROXY_CONTAINER=$(sudo docker ps --format "{{.Names}}" | grep -E "proxy|nginx" | head -1)
if [ -n "$PROXY_CONTAINER" ]; then
    echo "✅ Container proxy encontrado: $PROXY_CONTAINER"
    echo "Status:"
    sudo docker ps --filter "name=$PROXY_CONTAINER" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    echo ""
    echo "Logs recentes do proxy:"
    sudo docker logs --tail=20 "$PROXY_CONTAINER" 2>&1 | tail -10
else
    echo "❌ Container proxy/nginx não está rodando"
fi
echo ""

# 3. Verificar porta 80
echo "3️⃣ Verificando porta 80..."
echo "----------------------------------------"
if command -v ss &> /dev/null; then
    PORT_80=$(sudo ss -tlnp | grep ":80 " || true)
elif command -v netstat &> /dev/null; then
    PORT_80=$(sudo netstat -tlnp | grep ":80 " || true)
else
    PORT_80=""
fi

if [ -n "$PORT_80" ]; then
    echo "✅ Porta 80 está escutando:"
    echo "$PORT_80"
else
    echo "❌ Porta 80 NÃO está escutando"
fi
echo ""

# 4. Verificar configuração do nginx
echo "4️⃣ Verificando configuração do nginx..."
echo "----------------------------------------"
NGINX_CONF="docker/nginx/nginx.conf"
if [ -f "$NGINX_CONF" ]; then
    echo "✅ Arquivo de configuração encontrado: $NGINX_CONF"
    
    # Verificar se está tentando usar HTTPS sem certificados
    if grep -q "return 301 https" "$NGINX_CONF" && ! grep -q "# return 301 https" "$NGINX_CONF"; then
        echo "⚠️ PROBLEMA DETECTADO: nginx está redirecionando HTTP para HTTPS"
        
        # Verificar se certificados existem
        if [ -d "certs" ] && [ -f "certs/fullchain.pem" ] && [ -f "certs/privkey.pem" ]; then
            echo "✅ Certificados SSL encontrados"
        else
            echo "❌ Certificados SSL NÃO encontrados"
            echo "   Solução: Usar configuração HTTP-only temporariamente"
            
            # Aplicar correção automaticamente
            if [ -f "docker/nginx/nginx.conf.http-only" ]; then
                echo ""
                echo "🔧 APLICANDO CORREÇÃO: Usando nginx.conf.http-only"
                echo "----------------------------------------"
                sudo cp "$NGINX_CONF" "${NGINX_CONF}.backup.$(date +%Y%m%d_%H%M%S)"
                sudo cp docker/nginx/nginx.conf.http-only "$NGINX_CONF"
                echo "✅ Configuração HTTP-only aplicada"
                echo "   Backup salvo em: ${NGINX_CONF}.backup.*"
                
                # Reiniciar proxy
                if [ -n "$PROXY_CONTAINER" ]; then
                    echo ""
                    echo "🔄 Reiniciando container proxy..."
                    sudo docker compose restart proxy || sudo docker restart "$PROXY_CONTAINER"
                    echo "✅ Proxy reiniciado"
                    sleep 5
                fi
            else
                echo "❌ Arquivo nginx.conf.http-only não encontrado"
            fi
        fi
    else
        echo "✅ Configuração parece correta"
    fi
else
    echo "❌ Arquivo de configuração não encontrado: $NGINX_CONF"
fi
echo ""

# 5. Verificar .env
echo "5️⃣ Verificando arquivo .env..."
echo "----------------------------------------"
if [ -f ".env" ]; then
    echo "✅ Arquivo .env existe"
    # Verificar variáveis críticas (sem mostrar valores)
    if grep -q "POSTGRES_PASSWORD" .env && grep -q "REDIS_PASSWORD" .env; then
        echo "✅ Variáveis críticas configuradas"
    else
        echo "⚠️ Algumas variáveis podem estar faltando"
    fi
else
    echo "❌ Arquivo .env NÃO existe"
    if [ -f "env.example" ]; then
        echo "   Existe env.example - copie para .env e configure"
    fi
fi
echo ""

# 6. Verificar logs de erro
echo "6️⃣ Verificando logs de erro recentes..."
echo "----------------------------------------"
if [ -n "$PROXY_CONTAINER" ]; then
    echo "Erros no proxy:"
    sudo docker logs "$PROXY_CONTAINER" 2>&1 | grep -i "error\|fail\|refused" | tail -5 || echo "Nenhum erro encontrado"
fi
echo ""

# 7. Teste de conectividade interna
echo "7️⃣ Testando conectividade interna..."
echo "----------------------------------------"
if [ -n "$PROXY_CONTAINER" ]; then
    echo "Testando se backend está acessível do proxy:"
    sudo docker exec "$PROXY_CONTAINER" wget -q -O- http://backend:8000/health 2>&1 | head -3 || echo "⚠️ Backend não acessível do proxy"
    echo ""
    echo "Testando se frontend está acessível do proxy:"
    sudo docker exec "$PROXY_CONTAINER" wget -q -O- http://frontend:3000 2>&1 | head -3 || echo "⚠️ Frontend não acessível do proxy"
fi
echo ""

# 8. Resumo e recomendações
echo "=========================================="
echo "📋 RESUMO E RECOMENDAÇÕES"
echo "=========================================="
echo ""

# Verificar se tudo está OK
ISSUES=0

if [ -z "$PROXY_CONTAINER" ]; then
    echo "❌ Container proxy não está rodando"
    echo "   Solução: sudo docker compose up -d proxy"
    ISSUES=$((ISSUES + 1))
fi

if [ -z "$PORT_80" ]; then
    echo "❌ Porta 80 não está escutando"
    echo "   Solução: Verificar se proxy está rodando e se NSG permite porta 80"
    ISSUES=$((ISSUES + 1))
fi

if [ ! -f ".env" ]; then
    echo "❌ Arquivo .env não existe"
    echo "   Solução: Copiar env.example para .env e configurar"
    ISSUES=$((ISSUES + 1))
fi

if [ $ISSUES -eq 0 ]; then
    echo "✅ Todos os checks passaram!"
    echo ""
    echo "Se ainda houver problemas de conexão:"
    echo "  1. Verifique o NSG do Azure (porta 80 deve estar aberta)"
    echo "  2. Verifique os logs: sudo docker compose logs"
    echo "  3. Teste localmente: curl http://localhost/health"
else
    echo "⚠️ $ISSUES problema(s) encontrado(s)"
    echo ""
    echo "Próximos passos:"
    echo "  1. Corrija os problemas listados acima"
    echo "  2. Execute novamente este script para verificar"
fi

echo ""
echo "=========================================="
echo "✅ Diagnóstico concluído"
echo "=========================================="

