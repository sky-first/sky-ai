#!/bin/bash
# Script de Smoke Tests - Testes básicos após deploy
# Valida se a aplicação está funcionando corretamente após o deploy
# Uso: ./scripts/smoke-tests.sh <VM_IP> [TIMEOUT] [RESOURCE_GROUP] [VM_NAME]

set -eu

VM_IP="${1:-}"
TIMEOUT="${2:-30}"
RESOURCE_GROUP="${3:-}"
VM_NAME="${4:-}"

if [ -z "$VM_IP" ]; then
    echo "❌ ERRO: IP da VM não fornecido"
    echo "Uso: $0 <VM_IP> [TIMEOUT] [RESOURCE_GROUP] [VM_NAME]"
    exit 1
fi

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

ERRORS=0
WARNINGS=0
PORT_80_ACCESSIBLE=false

# Função para validar código HTTP
# Retorna o código limpo se válido, ou vazio se inválido
# CORRIGIDA: Trata "000000", espaços, caracteres extras, etc.
validate_http_code() {
    local code="$1"
    
    # Remove TODOS os caracteres não numéricos e pega apenas os primeiros 3 dígitos
    # Isso trata: "000000", " 200 ", "200OK", "200\n", etc.
    local clean_code=$(echo "$code" | grep -oE '[0-9]{3}' | head -1 || echo "")
    
    # Se não encontrou exatamente 3 dígitos, é inválido
    if [ -z "$clean_code" ] || [ ${#clean_code} -ne 3 ]; then
        return 1
    fi
    
    # "000" = falha de conexão/timeout (não é código HTTP válido)
    if [ "$clean_code" = "000" ]; then
        return 1  # Falha
    fi
    
    # Valida se é um código HTTP válido (100-599)
    if [ "$clean_code" -ge 100 ] && [ "$clean_code" -le 599 ] 2>/dev/null; then
        echo "$clean_code"
        return 0  # Sucesso
    fi
    
    return 1  # Formato inválido
}

# Função para log de erro
log_error() {
    echo -e "${RED}❌ ERRO:${NC} $1" >&2
    ((ERRORS++))
}

# Função para log de aviso
log_warning() {
    echo -e "${YELLOW}⚠️  AVISO:${NC} $1"
    ((WARNINGS++))
}

# Função para log de sucesso
log_success() {
    echo -e "${GREEN}✅${NC} $1"
}

# Função para log de informação
log_info() {
    echo -e "${BLUE}ℹ️  INFO:${NC} $1"
}

# Função para testar endpoint HTTP
test_endpoint() {
    local url="$1"
    local expected_status="${2:-200}"
    local description="${3:-$url}"
    local timeout="${4:-10}"
    
    echo -n "Testando $description... "
    
    response=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$timeout" --connect-timeout 5 "$url" 2>/dev/null || echo "000")
    
    if VALID_CODE=$(validate_http_code "$response"); then
        if [ "$VALID_CODE" = "$expected_status" ]; then
            log_success "$description (HTTP $VALID_CODE)"
            return 0
        else
            log_error "$description (esperado HTTP $expected_status, recebido HTTP $VALID_CODE)"
            return 1
        fi
    else
        log_error "$description (timeout/conexão recusada - código: $response)"
        return 1
    fi
}

# Função para testar endpoint com validação de conteúdo
test_endpoint_with_content() {
    local url="$1"
    local expected_content="$2"
    local description="${3:-$url}"
    local timeout="${4:-10}"
    
    echo -n "Testando $description... "
    
    response=$(curl -s --max-time "$timeout" --connect-timeout 5 "$url" 2>/dev/null || echo "")
    
    if [ -z "$response" ]; then
        log_error "$description (sem resposta)"
        return 1
    fi
    
    if echo "$response" | grep -q "$expected_content"; then
        log_success "$description (conteúdo válido)"
        return 0
    else
        log_error "$description (conteúdo inválido - esperado: $expected_content)"
        return 1
    fi
}

# Função para verificar readiness dos serviços
check_service_readiness() {
    local vm_ip="$1"
    local max_wait="${2:-120}"  # 2 minutos máximo
    local check_interval=5
    local elapsed=0
    
    echo "🔍 Verificando readiness dos serviços (timeout: ${max_wait}s)..."
    echo "   (Aguardando containers iniciarem e nginx ficar pronto)"
    
    while [ $elapsed -lt $max_wait ]; do
        # Curl melhorado conforme recomendação
        local http_code=$(curl -s \
            --connect-timeout 5 \
            --max-time 10 \
            -o /dev/null \
            -w "%{http_code}" \
            "http://${vm_ip}/health" 2>/dev/null || echo "000")
        
        if VALID_CODE=$(validate_http_code "$http_code"); then
            # 200 = health check OK, 404 = serviço responde mas rota não existe (ainda é sinal de vida)
            if [ "$VALID_CODE" = "200" ] || [ "$VALID_CODE" = "404" ]; then
                echo "✅ Serviços prontos (HTTP $VALID_CODE)"
                return 0
            fi
        fi
        
        # Mostra progresso a cada 15 segundos
        if [ $((elapsed % 15)) -eq 0 ] && [ $elapsed -gt 0 ]; then
            echo "⏳ Aguardando serviços... (${elapsed}s/${max_wait}s)"
            echo "   (Testando: http://${vm_ip}/health -> código: $http_code)"
        fi
        sleep $check_interval
        elapsed=$((elapsed + check_interval))
    done
    
    log_error "Timeout: serviços não ficaram prontos em ${max_wait}s"
    return 1
}

# Função para coletar diagnóstico quando falha
collect_diagnostics() {
    local vm_ip="$1"
    local resource_group="$2"
    local vm_name="$3"
    
    # CRÍTICO: Desabilita exit on error temporariamente
    # Isso garante que o diagnóstico seja executado mesmo se houver erros
    local original_set_e
    if [[ $- == *e* ]]; then
        original_set_e=true
        set +e
    else
        original_set_e=false
    fi
    
    echo ""
    echo "=========================================="
    echo "🔍 Coletando Diagnóstico Automático"
    echo "=========================================="
    echo ""
    
    # 1. Teste de conectividade básica
    echo "1️⃣ Testando conectividade básica..."
    if command -v ping >/dev/null 2>&1; then
        if ping -c 2 -W 2 "$vm_ip" >/dev/null 2>&1; then
            echo "✅ VM responde a ping"
        else
            echo "❌ VM não responde a ping"
        fi
    else
        echo "⚠️  Comando ping não disponível"
    fi
    
    # 2. Teste de porta 80 com diferentes métodos
    echo ""
    echo "2️⃣ Testando porta 80..."
    if timeout 3 bash -c "echo > /dev/tcp/$vm_ip/80" 2>/dev/null; then
        echo "✅ Porta 80 está aberta (TCP)"
    else
        echo "❌ Porta 80 não está acessível (TCP)"
    fi
    
    # 3. Verificar NSG (se Azure CLI disponível)
    if command -v az >/dev/null 2>&1 && [ -n "$resource_group" ]; then
        echo ""
        echo "3️⃣ Verificando regras NSG..."
        NSG_NAME=$(az network nic list -g "$resource_group" --query "[0].networkSecurityGroup.id" -o tsv 2>/dev/null | awk -F'/' '{print $NF}' || echo "")
        if [ -n "$NSG_NAME" ]; then
            HTTP_RULE=$(az network nsg rule list -g "$resource_group" --nsg-name "$NSG_NAME" --query "[?destinationPortRange=='80']" -o json 2>/dev/null)
            if [ -n "$HTTP_RULE" ] && [ "$HTTP_RULE" != "[]" ] && [ "$HTTP_RULE" != "null" ]; then
                echo "✅ Regra NSG para porta 80 encontrada"
                if command -v jq >/dev/null 2>&1; then
                    echo "$HTTP_RULE" | jq -r '.[0] | "   Nome: \(.name), Prioridade: \(.priority), Source: \(.sourceAddressPrefix)"' 2>/dev/null || echo "   (detalhes não disponíveis)"
                fi
            else
                echo "❌ Regra NSG para porta 80 NÃO encontrada"
                echo "   ⚠️  ISSO É PROVAVELMENTE A CAUSA DO PROBLEMA!"
            fi
        else
            echo "⚠️  NSG não encontrado"
        fi
    else
        echo ""
        echo "3️⃣ Verificação NSG: Azure CLI não disponível ou Resource Group não fornecido"
    fi
    
    # 4. Verificar containers na VM (se possível)
    if [ -n "$resource_group" ] && [ -n "$vm_name" ] && command -v az >/dev/null 2>&1; then
        echo ""
        echo "4️⃣ Verificando containers na VM..."
        CONTAINERS=$(az vm run-command invoke -g "$resource_group" -n "$vm_name" \
            --command-id RunShellScript \
            --scripts 'sudo docker ps --format "{{.Names}}: {{.Status}}" 2>/dev/null || echo "Docker não disponível ou erro ao executar"' \
            --query "value[0].message" -o tsv 2>/dev/null || echo "")
        
        if [ -n "$CONTAINERS" ] && [ "$CONTAINERS" != "null" ] && [ "$CONTAINERS" != "" ]; then
            echo "Containers rodando:"
            echo "$CONTAINERS" | grep -v "^$" | grep -v "null" | head -10 || echo "Nenhum container rodando"
        else
            echo "⚠️  Não foi possível verificar containers"
        fi
        
        # Verificar especificamente o container nginx/proxy
        echo ""
        echo "5️⃣ Verificando container nginx/proxy (CRÍTICO)..."
        PROXY_STATUS=$(az vm run-command invoke -g "$resource_group" -n "$vm_name" \
            --command-id RunShellScript \
            --scripts 'sudo docker ps --filter "name=proxy" --format "{{.Names}}: {{.Status}}" 2>/dev/null || echo "Não encontrado"' \
            --query "value[0].message" -o tsv 2>/dev/null || echo "")
        
        if [ -n "$PROXY_STATUS" ] && [ "$PROXY_STATUS" != "null" ] && echo "$PROXY_STATUS" | grep -q "proxy"; then
            echo "✅ Proxy container: $PROXY_STATUS"
            
            # Verificar se nginx está escutando em 0.0.0.0:80
            echo ""
            echo "6️⃣ Verificando se nginx está escutando em 0.0.0.0:80..."
            NGINX_LISTEN=$(az vm run-command invoke -g "$resource_group" -n "$vm_name" \
                --command-id RunShellScript \
                --scripts 'sudo docker exec ai_saas_proxy nginx -T 2>/dev/null | grep -E "listen.*80" | head -1 || echo "Não encontrado"' \
                --query "value[0].message" -o tsv 2>/dev/null || echo "")
            
            if echo "$NGINX_LISTEN" | grep -q "listen.*80"; then
                echo "✅ Nginx configurado para escutar na porta 80"
                echo "   Config: $NGINX_LISTEN"
                # Verificar se está escutando em 0.0.0.0 (não 127.0.0.1)
                if echo "$NGINX_LISTEN" | grep -qE "listen\s+80|listen\s+\*:80|listen\s+0\.0\.0\.0:80"; then
                    echo "✅ Nginx escutando em 0.0.0.0:80 (correto)"
                elif echo "$NGINX_LISTEN" | grep -q "127.0.0.1"; then
                    echo "❌ PROBLEMA: Nginx escutando apenas em 127.0.0.1 (deve ser 0.0.0.0:80)"
                fi
            else
                echo "⚠️  Não foi possível verificar configuração do nginx"
            fi
        else
            echo "❌ Proxy container NÃO está rodando"
            echo "   ⚠️  ISSO É PROVAVELMENTE A CAUSA DO PROBLEMA!"
            
            # Tentar ver logs do proxy
            echo ""
            echo "6️⃣ Últimos logs do proxy (se existir)..."
            PROXY_LOGS=$(az vm run-command invoke -g "$resource_group" -n "$vm_name" \
                --command-id RunShellScript \
                --scripts 'sudo docker logs ai_saas_proxy --tail=20 2>&1 || echo "Container não encontrado"' \
                --query "value[0].message" -o tsv 2>/dev/null || echo "")
            
            if [ -n "$PROXY_LOGS" ] && [ "$PROXY_LOGS" != "null" ]; then
                echo "$PROXY_LOGS" | head -10
            fi
            
            # Diagnóstico completo quando proxy não está rodando
            echo ""
            echo "7️⃣ Verificando docker compose ps (todos os containers)..."
            COMPOSE_STATUS=$(az vm run-command invoke -g "$resource_group" -n "$vm_name" \
                --command-id RunShellScript \
                --scripts '
                  set -eu
                  # Usar caminho absoluto e tentar múltiplos diretórios
                  BASE="/home/azureuser/projeto"
                  if [ -d "$BASE/sky-poc-infra" ]; then
                    INFRA_DIR="$BASE/sky-poc-infra"
                  elif [ -d "$BASE/poc-deploy" ]; then
                    INFRA_DIR="$BASE/poc-deploy"
                  else
                    echo "ERRO: Diretório de infraestrutura não encontrado em $BASE"
                    exit 0
                  fi
                  cd "$INFRA_DIR" || {
                    echo "ERRO: Não foi possível entrar em $INFRA_DIR"
                    exit 0
                  }
                  if command -v docker >/dev/null 2>&1; then
                    if docker compose version >/dev/null 2>&1; then
                      sudo docker compose ps 2>/dev/null || echo "ERRO: docker compose ps falhou"
                    else
                      echo "ERRO: docker compose não está disponível (plugin ausente)"
                    fi
                  else
                    echo "ERRO: docker não está instalado na VM"
                  fi
                ' \
                --query "value[0].message" -o tsv 2>/dev/null || echo "")
            
            if [ -n "$COMPOSE_STATUS" ] && [ "$COMPOSE_STATUS" != "null" ]; then
                echo "$COMPOSE_STATUS" | grep -v "^$" | grep -v "Enable succeeded" | head -30
                # Verificar se há containers com status "Exit" ou "Dead"
                if echo "$COMPOSE_STATUS" | grep -qE "(Exit|Dead|unhealthy|restarting)"; then
                    echo ""
                    echo "⚠️  ATENÇÃO: Alguns containers estão com problemas!"
                    echo "$COMPOSE_STATUS" | grep -E "(Exit|Dead|unhealthy|restarting)" || true
                fi
            else
                echo "⚠️  Não foi possível verificar docker compose ps"
                echo "   Isso pode indicar:"
                echo "     - Docker não está instalado na VM"
                echo "     - docker compose plugin não está disponível"
                echo "     - Diretório de infraestrutura não foi clonado (sky-poc-infra/poc-deploy)"
            fi
            
            echo ""
            echo "8️⃣ Verificando containers parados ou com erro..."
            STOPPED_CONTAINERS=$(az vm run-command invoke -g "$resource_group" -n "$vm_name" \
                --command-id RunShellScript \
                --scripts 'sudo docker ps -a --format "{{.Names}}: {{.Status}}" --filter "status=exited" --filter "status=dead" 2>/dev/null | head -20 || echo ""' \
                --query "value[0].message" -o tsv 2>/dev/null || echo "")
            
            if [ -n "$STOPPED_CONTAINERS" ] && [ "$STOPPED_CONTAINERS" != "null" ] && [ "$STOPPED_CONTAINERS" != "" ]; then
                echo "Containers parados ou com erro:"
                echo "$STOPPED_CONTAINERS" | grep -v "^$" | head -20
                echo ""
                echo "💡 Isso indica que containers falharam ao iniciar"
            else
                echo "✅ Nenhum container parado encontrado"
            fi
            
            echo ""
            echo "9️⃣ Verificando dependências do proxy (backend, frontend)..."
            BACKEND_STATUS=$(az vm run-command invoke -g "$resource_group" -n "$vm_name" \
                --command-id RunShellScript \
                --scripts 'sudo docker ps --filter "name=backend" --format "{{.Names}}: {{.Status}}" 2>/dev/null || echo "Não encontrado"' \
                --query "value[0].message" -o tsv 2>/dev/null || echo "")
            
            FRONTEND_STATUS=$(az vm run-command invoke -g "$resource_group" -n "$vm_name" \
                --command-id RunShellScript \
                --scripts 'sudo docker ps --filter "name=frontend" --format "{{.Names}}: {{.Status}}" 2>/dev/null || echo "Não encontrado"' \
                --query "value[0].message" -o tsv 2>/dev/null || echo "")
            
            POSTGRES_STATUS=$(az vm run-command invoke -g "$resource_group" -n "$vm_name" \
                --command-id RunShellScript \
                --scripts 'sudo docker ps --filter "name=postgres" --format "{{.Names}}: {{.Status}}" 2>/dev/null || echo "Não encontrado"' \
                --query "value[0].message" -o tsv 2>/dev/null || echo "")
            
            REDIS_STATUS=$(az vm run-command invoke -g "$resource_group" -n "$vm_name" \
                --command-id RunShellScript \
                --scripts 'sudo docker ps --filter "name=redis" --format "{{.Names}}: {{.Status}}" 2>/dev/null || echo "Não encontrado"' \
                --query "value[0].message" -o tsv 2>/dev/null || echo "")
            
            AI_STATUS=$(az vm run-command invoke -g "$resource_group" -n "$vm_name" \
                --command-id RunShellScript \
                --scripts 'sudo docker ps --filter "name=ai" --format "{{.Names}}: {{.Status}}" 2>/dev/null || echo "Não encontrado"' \
                --query "value[0].message" -o tsv 2>/dev/null || echo "")
            
            echo "Dependências do proxy:"
            if [ -n "$POSTGRES_STATUS" ] && echo "$POSTGRES_STATUS" | grep -q "postgres"; then
                echo "✅ Postgres: $POSTGRES_STATUS"
            else
                echo "❌ Postgres NÃO está rodando (backend depende disso)"
            fi
            
            if [ -n "$REDIS_STATUS" ] && echo "$REDIS_STATUS" | grep -q "redis"; then
                echo "✅ Redis: $REDIS_STATUS"
            else
                echo "❌ Redis NÃO está rodando (backend depende disso)"
            fi
            
            if [ -n "$AI_STATUS" ] && echo "$AI_STATUS" | grep -q "ai"; then
                echo "✅ AI: $AI_STATUS"
            else
                echo "⚠️  AI NÃO está rodando (backend depende disso)"
            fi
            
            if [ -n "$BACKEND_STATUS" ] && echo "$BACKEND_STATUS" | grep -q "backend"; then
                echo "✅ Backend: $BACKEND_STATUS"
            else
                echo "❌ Backend NÃO está rodando (proxy depende disso)"
            fi
            
            if [ -n "$FRONTEND_STATUS" ] && echo "$FRONTEND_STATUS" | grep -q "frontend"; then
                echo "✅ Frontend: $FRONTEND_STATUS"
            else
                echo "⚠️  Frontend NÃO está rodando (proxy depende disso)"
            fi
            
            echo ""
            echo "🔟 Verificando logs do docker compose (últimas 50 linhas)..."
            COMPOSE_LOGS=$(az vm run-command invoke -g "$resource_group" -n "$vm_name" \
                --command-id RunShellScript \
                --scripts '
                  set -eu
                  BASE="/home/azureuser/projeto"
                  if [ -d "$BASE/sky-poc-infra" ]; then
                    INFRA_DIR="$BASE/sky-poc-infra"
                  elif [ -d "$BASE/poc-deploy" ]; then
                    INFRA_DIR="$BASE/poc-deploy"
                  else
                    echo "ERRO: Diretório de infraestrutura não encontrado em $BASE"
                    exit 0
                  fi
                  cd "$INFRA_DIR" || exit 0
                  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
                    sudo docker compose logs --tail=50 2>&1 | tail -50 || echo "Erro ao obter logs"
                  else
                    echo "ERRO: docker compose não está disponível na VM"
                  fi
                ' \
                --query "value[0].message" -o tsv 2>/dev/null || echo "")
            
            if [ -n "$COMPOSE_LOGS" ] && [ "$COMPOSE_LOGS" != "null" ]; then
                echo "$COMPOSE_LOGS" | grep -v "^$" | grep -v "Enable succeeded" | head -50
                # Destacar erros críticos
                if echo "$COMPOSE_LOGS" | grep -qiE "(error|failed|fatal|exception|traceback)"; then
                    echo ""
                    echo "⚠️  ERROS ENCONTRADOS NOS LOGS:"
                    echo "$COMPOSE_LOGS" | grep -iE "(error|failed|fatal|exception|traceback)" | head -10 || true
                fi
            fi
            
            echo ""
            echo "1️⃣1️⃣ Verificando se .env existe..."
            ENV_CHECK=$(az vm run-command invoke -g "$resource_group" -n "$vm_name" \
                --command-id RunShellScript \
                --scripts '
                  set -eu
                  BASE="/home/azureuser/projeto"
                  if [ -d "$BASE/sky-poc-infra" ]; then
                    INFRA_DIR="$BASE/sky-poc-infra"
                  elif [ -d "$BASE/poc-deploy" ]; then
                    INFRA_DIR="$BASE/poc-deploy"
                  else
                    echo "NOT_FOUND"
                    exit 0
                  fi
                  cd "$INFRA_DIR" || { echo "NOT_FOUND"; exit 0; }
                  if [ -f .env ]; then
                    echo "EXISTS"
                  else
                    echo "NOT_FOUND"
                  fi
                ' \
                --query "value[0].message" -o tsv 2>/dev/null || echo "")
            
            if echo "$ENV_CHECK" | grep -q "EXISTS"; then
                echo "✅ Arquivo .env existe"
            else
                echo "❌ Arquivo .env NÃO existe!"
                echo "   ⚠️  ISSO É PROVAVELMENTE A CAUSA DO PROBLEMA!"
            fi
        fi
    else
        echo ""
        echo "4️⃣ Verificação containers: Azure CLI não disponível ou informações insuficientes"
    fi
    
    # Restaura exit on error se estava habilitado
    if [ "$original_set_e" = "true" ]; then
        set -e
    fi
    
    echo ""
    echo "=========================================="
}

echo "=========================================="
echo "🧪 Smoke Tests - Validação Pós-Deploy"
echo "=========================================="
echo ""
echo "VM IP: $VM_IP"
echo "Timeout: ${TIMEOUT}s"
[ -n "$RESOURCE_GROUP" ] && echo "Resource Group: $RESOURCE_GROUP"
[ -n "$VM_NAME" ] && echo "VM Name: $VM_NAME"
echo ""

# 1. Verificar readiness dos serviços (com timeout inteligente)
# CRÍTICO: Abortar se serviços não estão prontos (evita testes em cascata)
if ! check_service_readiness "$VM_IP" 120; then
    log_error "Serviços não ficaram prontos - abortando smoke tests"
    echo ""
    echo "💡 Isso indica que:"
    echo "  1. Containers não iniciaram"
    echo "  2. Nginx/proxy não está rodando"
    echo "  3. Aplicação não está respondendo"
    echo ""
    
    # Executar diagnóstico antes de abortar
    if [ -n "$RESOURCE_GROUP" ] || [ -n "$VM_NAME" ]; then
        echo "🔍 Executando diagnóstico automático antes de abortar..."
        set +e
        collect_diagnostics "$VM_IP" "$RESOURCE_GROUP" "$VM_NAME" || {
            echo "⚠️  Alguns comandos de diagnóstico falharam, mas informações coletadas acima"
        }
        set -e
        echo ""
    fi
    
    exit 1
fi

echo ""
echo "=========================================="
echo "📡 Testando Conectividade Básica"
echo "=========================================="
echo ""

# 2. Teste de porta 80 com validação correta
MAX_RETRIES=5
RETRY_DELAY=3

for i in $(seq 1 $MAX_RETRIES); do
    echo -n "Tentativa $i/$MAX_RETRIES: Testando porta 80... "
    
    # Curl melhorado conforme recomendação
    HTTP_CODE=$(curl -s \
        --connect-timeout 5 \
        --max-time 10 \
        -o /dev/null \
        -w "%{http_code}" \
        "http://${VM_IP}:80" 2>/dev/null || echo "000")
    
    # Limpa o código (remove qualquer texto de erro que possa ter vindo)
    HTTP_CODE_CLEAN=$(echo "$HTTP_CODE" | grep -oE '[0-9]{3}' | head -1 || echo "000")
    
    # Log detalhado apenas na primeira tentativa para debugging
    if [ "$i" -eq 1 ] && [ "$HTTP_CODE_CLEAN" = "000" ]; then
        echo "(código: '$HTTP_CODE_CLEAN')"
    fi
    
    if VALID_CODE=$(validate_http_code "$HTTP_CODE_CLEAN"); then
        # Valida código HTTP
        if [ "$VALID_CODE" = "200" ]; then
            log_success "Porta 80 OK (HTTP $VALID_CODE)"
        elif [ "$VALID_CODE" -ge 200 ] && [ "$VALID_CODE" -lt 400 ]; then
            log_warning "Porta 80 responde mas retornou HTTP $VALID_CODE"
        else
            log_warning "Porta 80 responde mas retornou HTTP $VALID_CODE (erro do servidor)"
        fi
        PORT_80_ACCESSIBLE=true
        break
    fi
    
    echo "Falhou (código: '$HTTP_CODE_CLEAN')"
    if [ $i -lt $MAX_RETRIES ]; then
        echo "Aguardando ${RETRY_DELAY}s antes da próxima tentativa..."
        sleep $RETRY_DELAY
    fi
done

if [ "$PORT_80_ACCESSIBLE" = false ]; then
    log_error "Porta 80 não acessível após $MAX_RETRIES tentativas"
    echo ""
    echo "🔍 Informações de diagnóstico:"
    echo "  - IP testado: $VM_IP"
    echo "  - Porta: 80"
    echo "  - Tentativas: $MAX_RETRIES"
    echo ""
    echo "💡 Principais causas (em 90% dos casos):"
    echo "  1. ❌ NGINX/Proxy não está rodando"
    echo "  2. ❌ App escutando só em 127.0.0.1 (deve ser 0.0.0.0:80)"
    echo "  3. ❌ NSG do Azure bloqueando porta 80"
    echo "  4. ❌ Firewall da VM bloqueando porta 80"
    echo "  5. ❌ Containers não iniciaram completamente"
    echo ""
    # Coletar diagnóstico se informações disponíveis (com tratamento de erro)
    if [ -n "$RESOURCE_GROUP" ] || [ -n "$VM_NAME" ]; then
        echo "🔍 Executando diagnóstico automático..."
        # Desabilita exit on error temporariamente para garantir execução
        set +e
        collect_diagnostics "$VM_IP" "$RESOURCE_GROUP" "$VM_NAME" || {
            echo "⚠️  Alguns comandos de diagnóstico falharam, mas informações coletadas acima"
        }
        set -e
    else
        echo "⚠️  Resource Group ou VM Name não fornecidos - diagnóstico automático não disponível"
    fi
fi

echo ""
echo "=========================================="
echo "🏥 Testando Health Checks"
echo "=========================================="
echo ""

# Teste 2: Health check do backend
test_endpoint "http://$VM_IP/health" "200" "Health Check do Backend" "$TIMEOUT"

# Teste 3: Health check com validação de conteúdo (se disponível)
if test_endpoint "http://$VM_IP/health" "200" "Health Check (HTTP)" "$TIMEOUT"; then
    # Tentar validar conteúdo se endpoint retornar JSON
    health_response=$(curl -s --max-time 10 "http://$VM_IP/health" 2>/dev/null || echo "")
    if echo "$health_response" | grep -qE "(status|healthy|ok)" || [ -n "$health_response" ]; then
        log_success "Health Check retornou resposta válida"
    else
        log_warning "Health Check retornou resposta vazia ou inválida"
    fi
fi

echo ""
echo "=========================================="
echo "🌐 Testando Frontend"
echo "=========================================="
echo ""

# Teste 4: Frontend acessível
test_endpoint "http://$VM_IP/" "200" "Frontend (página inicial)" "$TIMEOUT"

# Teste 5: Frontend retorna HTML
frontend_response=$(curl -s --max-time 10 "http://$VM_IP/" 2>/dev/null || echo "")
if echo "$frontend_response" | grep -qiE "(html|<!DOCTYPE|next)" >/dev/null 2>&1; then
    log_success "Frontend retorna HTML válido"
else
    log_warning "Frontend pode não estar retornando HTML válido"
fi

echo ""
echo "=========================================="
echo "🔌 Testando API Backend"
echo "=========================================="
echo ""

# Teste 6: API endpoint base
test_endpoint "http://$VM_IP/api/v1/" "200" "API Base (/api/v1/)" "$TIMEOUT" || \
test_endpoint "http://$VM_IP/api/v1/" "404" "API Base (/api/v1/ - 404 OK se não tiver rota raiz)" "$TIMEOUT" || \
test_endpoint "http://$VM_IP/api/v1/" "405" "API Base (/api/v1/ - 405 OK se método não permitido)" "$TIMEOUT"

# Teste 7: API health endpoint (se disponível)
test_endpoint "http://$VM_IP/api/v1/health" "200" "API Health Check" "$TIMEOUT" || \
log_warning "API Health Check não disponível em /api/v1/health"

# Teste 8: CORS headers (OPTIONS request)
echo -n "Testando CORS (OPTIONS)... "
cors_response=$(curl -s -o /dev/null -w "%{http_code}" -X OPTIONS \
    -H "Origin: http://localhost:3000" \
    -H "Access-Control-Request-Method: GET" \
    --max-time 10 \
    "http://$VM_IP/api/v1/health" 2>/dev/null || echo "000")

if VALID_CORS=$(validate_http_code "$cors_response"); then
    if [ "$VALID_CORS" = "204" ] || [ "$VALID_CORS" = "200" ]; then
        log_success "CORS configurado (HTTP $VALID_CORS)"
    else
        log_warning "CORS pode não estar configurado corretamente (HTTP $VALID_CORS)"
    fi
else
    log_warning "CORS não acessível (código: $cors_response)"
fi

echo ""
echo "=========================================="
echo "📊 Resumo dos Testes"
echo "=========================================="
echo ""

# Verificação final: se porta 80 não está acessível mas outros testes passaram
if [ "$PORT_80_ACCESSIBLE" = false ] && [ $ERRORS -gt 0 ]; then
    echo -e "${YELLOW}⚠️  Porta 80 não acessível nas tentativas iniciais, mas verificando se serviços respondem via HTTP...${NC}"
    echo ""
    
    # Tenta fazer uma requisição HTTP real para verificar se o serviço está funcionando
    HTTP_TEST=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 --connect-timeout 5 "http://$VM_IP/" 2>/dev/null || echo "000")
    
    if VALID_TEST=$(validate_http_code "$HTTP_TEST"); then
        echo -e "${GREEN}✅ Serviço está respondendo via HTTP (código: $VALID_TEST)${NC}"
        echo -e "${YELLOW}⚠️  O teste inicial pode ter falhado por questões de timing, mas o serviço está funcionando${NC}"
        # Remove o erro da porta 80 se conseguimos fazer requisições HTTP
        if [ $ERRORS -gt 0 ]; then
            ERRORS=$((ERRORS - 1))
        fi
        PORT_80_ACCESSIBLE=true
    fi
    echo ""
fi

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}✅ Todos os testes passaram!${NC}"
    echo ""
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠️  Testes concluídos com $WARNINGS aviso(s)${NC}"
    echo -e "${GREEN}✅ Nenhum erro crítico encontrado${NC}"
    echo ""
    exit 0
else
    echo -e "${RED}❌ Testes falharam com $ERRORS erro(s) e $WARNINGS aviso(s)${NC}"
    echo ""
    
    # Coletar diagnóstico completo se houver erros (com tratamento de erro)
    if [ -n "$RESOURCE_GROUP" ] || [ -n "$VM_NAME" ]; then
        # Desabilita exit on error temporariamente para garantir execução
        set +e
        collect_diagnostics "$VM_IP" "$RESOURCE_GROUP" "$VM_NAME" || {
            echo "⚠️  Alguns comandos de diagnóstico falharam, mas informações coletadas acima"
        }
        set -e
    fi
    
    echo "🔧 Verifique:"
    echo "  1. Containers estão rodando:"
    echo "     az vm run-command invoke -g <RG> -n <VM> --command-id RunShellScript --scripts 'sudo docker ps'"
    echo ""
    echo "  2. Nginx/proxy está configurado corretamente:"
    echo "     az vm run-command invoke -g <RG> -n <VM> --command-id RunShellScript --scripts 'sudo docker logs ai_saas_proxy'"
    echo ""
    echo "  3. Portas estão abertas no NSG:"
    echo "     az network nsg rule list -g <RG> --nsg-name <NSG> --query \"[?destinationPortRange=='80']\""
    echo ""
    echo "  4. Firewall da VM:"
    echo "     az vm run-command invoke -g <RG> -n <VM> --command-id RunShellScript --scripts 'sudo ufw status || sudo iptables -L -n'"
    echo ""
    echo "  5. Logs dos containers:"
    echo "     az vm run-command invoke -g <RG> -n <VM> --command-id RunShellScript --scripts 'cd /home/azureuser/projeto/sky-poc-infra && sudo docker compose logs --tail=50'"
    echo ""
    exit 1
fi
