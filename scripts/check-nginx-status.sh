#!/bin/bash
# Script para verificar status completo do nginx e portas expostas

set -eu

RESOURCE_GROUP="${1:-skyfirstlabs-poc}"
VM_NAME="${2:-skyfirstlabs-staging}"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}   🔍 Verificação Completa do Nginx/Proxy${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Função para executar comando na VM
run_vm_command() {
    az vm run-command invoke \
        --resource-group "$RESOURCE_GROUP" \
        --name "$VM_NAME" \
        --command-id RunShellScript \
        --scripts "$@" \
        --output json 2>&1 | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if 'value' in data and len(data['value']) > 0:
        msg = data['value'][0].get('message', '')
        msg = msg.replace('[stdout]', '').replace('[stderr]', '')
        print(msg)
except:
    pass
" 2>/dev/null || echo ""
}

echo -e "${MAGENTA}1️⃣ STATUS DO CONTAINER NGINX${NC}"
echo ""
NGINX_STATUS=$(run_vm_command 'docker ps --filter "name=ai_saas_proxy" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"')
if [ -n "$NGINX_STATUS" ]; then
    echo "$NGINX_STATUS"
    echo -e "${GREEN}✅ Container nginx está rodando${NC}"
else
    echo -e "${RED}❌ Container nginx NÃO está rodando!${NC}"
    echo ""
    echo -e "${YELLOW}💡 Tentando iniciar...${NC}"
    run_vm_command 'docker start ai_saas_proxy && sleep 5 && docker ps --filter "name=ai_saas_proxy" --format "{{.Names}}: {{.Status}}"'
fi
echo ""

echo -e "${MAGENTA}2️⃣ PORTAS EXPOSTAS DO CONTAINER${NC}"
echo ""
PORTS=$(run_vm_command 'docker ps --filter "name=ai_saas_proxy" --format "{{.Ports}}"')
if [ -n "$PORTS" ]; then
    echo "Portas mapeadas: $PORTS"
    if echo "$PORTS" | grep -q "0.0.0.0:80"; then
        echo -e "${GREEN}✅ Porta 80 está mapeada para 0.0.0.0 (acessível externamente)${NC}"
    else
        echo -e "${RED}❌ Porta 80 NÃO está mapeada para 0.0.0.0${NC}"
    fi
    if echo "$PORTS" | grep -q "0.0.0.0:443"; then
        echo -e "${GREEN}✅ Porta 443 está mapeada para 0.0.0.0${NC}"
    else
        echo -e "${YELLOW}⚠️  Porta 443 não está mapeada (pode ser normal se não usar HTTPS)${NC}"
    fi
else
    echo -e "${RED}❌ Nenhuma porta encontrada${NC}"
fi
echo ""

echo -e "${MAGENTA}3️⃣ PROCESSOS DENTRO DO CONTAINER NGINX${NC}"
echo ""
NGINX_PROCESSES=$(run_vm_command 'docker exec ai_saas_proxy ps aux | head -10')
if [ -n "$NGINX_PROCESSES" ]; then
    echo "$NGINX_PROCESSES"
    if echo "$NGINX_PROCESSES" | grep -q "nginx"; then
        echo -e "${GREEN}✅ Processo nginx está rodando${NC}"
    else
        echo -e "${RED}❌ Processo nginx NÃO encontrado${NC}"
    fi
else
    echo -e "${RED}❌ Não foi possível verificar processos${NC}"
fi
echo ""

echo -e "${MAGENTA}4️⃣ PORTAS ESCUTANDO DENTRO DO CONTAINER${NC}"
echo ""
NGINX_LISTEN=$(run_vm_command 'docker exec ai_saas_proxy netstat -tlnp 2>/dev/null | grep -E ":(80|443)" || docker exec ai_saas_proxy ss -tlnp 2>/dev/null | grep -E ":(80|443)" || echo "COMANDO_NAO_DISPONIVEL"')
if [ -n "$NGINX_LISTEN" ] && ! echo "$NGINX_LISTEN" | grep -q "COMANDO_NAO_DISPONIVEL"; then
    echo "$NGINX_LISTEN"
    if echo "$NGINX_LISTEN" | grep -q ":80"; then
        echo -e "${GREEN}✅ Nginx está escutando na porta 80${NC}"
    else
        echo -e "${RED}❌ Nginx NÃO está escutando na porta 80${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  Comandos netstat/ss não disponíveis no container${NC}"
    echo -e "${BLUE}💡 Verificando de outra forma...${NC}"
    # Tentar verificar via curl
    NGINX_CURL=$(run_vm_command 'docker exec ai_saas_proxy curl -s -o /dev/null -w "%{http_code}" http://localhost 2>&1 || echo "ERRO"')
    if echo "$NGINX_CURL" | grep -qE "200|301|302|404"; then
        echo -e "${GREEN}✅ Nginx está respondendo (HTTP $NGINX_CURL)${NC}"
    else
        echo -e "${RED}❌ Nginx não está respondendo: $NGINX_CURL${NC}"
    fi
fi
echo ""

echo -e "${MAGENTA}5️⃣ CONFIGURAÇÃO DO NGINX${NC}"
echo ""
NGINX_CONFIG=$(run_vm_command 'docker exec ai_saas_proxy nginx -t 2>&1')
if echo "$NGINX_CONFIG" | grep -q "successful"; then
    echo -e "${GREEN}✅ Configuração do nginx está válida${NC}"
    echo "$NGINX_CONFIG" | grep -E "(test|successful|syntax)"
else
    echo -e "${RED}❌ Configuração do nginx tem erros:${NC}"
    echo "$NGINX_CONFIG"
fi
echo ""

echo -e "${MAGENTA}6️⃣ TESTE DE CONECTIVIDADE INTERNA (dentro da VM)${NC}"
echo ""
echo -n "  Teste localhost:80: "
LOCAL_TEST=$(run_vm_command 'curl -s -o /dev/null -w "HTTP %{http_code}" http://localhost 2>&1 || echo "ERRO"')
if echo "$LOCAL_TEST" | grep -qE "200|301|302|404"; then
    echo -e "${GREEN}✅ $LOCAL_TEST${NC}"
else
    echo -e "${RED}❌ $LOCAL_TEST${NC}"
fi

echo -n "  Teste 127.0.0.1:80: "
LOCALHOST_TEST=$(run_vm_command 'curl -s -o /dev/null -w "HTTP %{http_code}" http://127.0.0.1 2>&1 || echo "ERRO"')
if echo "$LOCALHOST_TEST" | grep -qE "200|301|302|404"; then
    echo -e "${GREEN}✅ $LOCALHOST_TEST${NC}"
else
    echo -e "${RED}❌ $LOCALHOST_TEST${NC}"
fi

echo -n "  Teste IP da VM (20.185.60.67:80): "
IP_TEST=$(run_vm_command 'curl -s -o /dev/null -w "HTTP %{http_code}" http://20.185.60.67 2>&1 || echo "ERRO"')
if echo "$IP_TEST" | grep -qE "200|301|302|404"; then
    echo -e "${GREEN}✅ $IP_TEST${NC}"
else
    echo -e "${RED}❌ $IP_TEST${NC}"
fi
echo ""

echo -e "${MAGENTA}7️⃣ VERIFICAÇÃO DE FIREWALL NA VM${NC}"
echo ""
FIREWALL=$(run_vm_command 'sudo iptables -L -n 2>/dev/null | grep -E "(80|443|ACCEPT|REJECT)" | head -10 || echo "IPTABLES_NAO_DISPONIVEL"')
if [ -n "$FIREWALL" ] && ! echo "$FIREWALL" | grep -q "IPTABLES_NAO_DISPONIVEL"; then
    echo "$FIREWALL"
else
    echo -e "${YELLOW}⚠️  Não foi possível verificar iptables${NC}"
    echo -e "${BLUE}💡 Verificando se há firewall ativo...${NC}"
    UFW_STATUS=$(run_vm_command 'sudo ufw status 2>/dev/null || echo "UFW_NAO_DISPONIVEL"')
    if [ -n "$UFW_STATUS" ] && ! echo "$UFW_STATUS" | grep -q "UFW_NAO_DISPONIVEL"; then
        echo "$UFW_STATUS"
    else
        echo -e "${YELLOW}⚠️  UFW não disponível ou não configurado${NC}"
    fi
fi
echo ""

echo -e "${MAGENTA}8️⃣ LOGS DO NGINX (últimas 20 linhas)${NC}"
echo ""
NGINX_LOGS=$(run_vm_command 'docker logs ai_saas_proxy --tail 20 2>&1')
echo "$NGINX_LOGS" | tail -20
echo ""

echo -e "${MAGENTA}9️⃣ VERIFICAÇÃO DE PORTAS NA VM${NC}"
echo ""
VM_PORTS=$(run_vm_command 'sudo netstat -tlnp 2>/dev/null | grep -E ":(80|443)" || sudo ss -tlnp 2>/dev/null | grep -E ":(80|443)" || echo "COMANDO_NAO_DISPONIVEL"')
if [ -n "$VM_PORTS" ] && ! echo "$VM_PORTS" | grep -q "COMANDO_NAO_DISPONIVEL"; then
    echo "$VM_PORTS"
    if echo "$VM_PORTS" | grep -q ":80"; then
        echo -e "${GREEN}✅ Porta 80 está escutando na VM${NC}"
    else
        echo -e "${RED}❌ Porta 80 NÃO está escutando na VM${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  Não foi possível verificar portas na VM${NC}"
fi
echo ""

echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}   📊 RESUMO E DIAGNÓSTICO${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Análise dos resultados
ISSUES=0

if ! echo "$NGINX_STATUS" | grep -q "ai_saas_proxy"; then
    echo -e "${RED}❌ PROBLEMA CRÍTICO: Container nginx não está rodando${NC}"
    ISSUES=$((ISSUES + 1))
fi

if ! echo "$PORTS" | grep -q "0.0.0.0:80"; then
    echo -e "${RED}❌ PROBLEMA CRÍTICO: Porta 80 não está mapeada para 0.0.0.0${NC}"
    ISSUES=$((ISSUES + 1))
fi

if ! echo "$LOCAL_TEST" | grep -qE "200|301|302|404"; then
    echo -e "${RED}❌ PROBLEMA: Nginx não responde em localhost:80${NC}"
    ISSUES=$((ISSUES + 1))
fi

if ! echo "$IP_TEST" | grep -qE "200|301|302|404"; then
    echo -e "${YELLOW}⚠️  PROBLEMA: Nginx não responde no IP externo${NC}"
    echo -e "${BLUE}💡 Isso pode ser:${NC}"
    echo "   1. NSG (Network Security Group) bloqueando portas 80/443"
    echo "   2. Firewall do Azure bloqueando"
    echo "   3. Nginx não está escutando corretamente"
    ISSUES=$((ISSUES + 1))
fi

if [ $ISSUES -eq 0 ]; then
    echo -e "${GREEN}✅ Tudo parece estar funcionando corretamente!${NC}"
    echo ""
    echo -e "${BLUE}💡 Se ainda houver ERR_CONNECTION_REFUSED:${NC}"
    echo "   1. Verifique NSG no Azure Portal"
    echo "   2. Verifique se há firewall adicional"
    echo "   3. Aguarde alguns minutos para propagação"
else
    echo ""
    echo -e "${YELLOW}💡 Soluções recomendadas:${NC}"
    if ! echo "$NGINX_STATUS" | grep -q "ai_saas_proxy"; then
        echo "   1. Iniciar nginx: docker start ai_saas_proxy"
    fi
    if ! echo "$PORTS" | grep -q "0.0.0.0:80"; then
        echo "   2. Verificar docker-compose.yml - porta 80 deve estar mapeada"
        echo "   3. Reiniciar: docker compose up -d proxy"
    fi
    if ! echo "$IP_TEST" | grep -qE "200|301|302|404"; then
        echo "   4. Verificar NSG no Azure Portal:"
        echo "      - Regra de entrada para porta 80 (HTTP)"
        echo "      - Regra de entrada para porta 443 (HTTPS)"
        echo "      - Source: Any ou Internet"
    fi
fi

echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"

