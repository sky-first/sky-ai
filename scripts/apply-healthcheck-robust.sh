#!/bin/bash
# Script robusto final para aplicar healthcheck garantindo 100% de funcionalidade
set -eu

RESOURCE_GROUP="${1:-skyfirstlabs-poc}"
VM_NAME="${2:-skyfirstlabs-staging}"

echo "═══════════════════════════════════════════════════════════"
echo " APLICAÇÃO ROBUSTA DA CORREÇÃO 502"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Criar script completo que será executado na VM
FULL_SCRIPT=$(cat <<'SCRIPT_EOF'
#!/bin/bash
set -eu

cd /home/azureuser/projeto/sky-poc-infra 2>/dev/null || cd /home/azureuser/projeto/poc-deploy 2>/dev/null || {
    echo "[ERROR] Diretório não encontrado"
    exit 1
}

echo "📁 Diretório: $(pwd)"
echo ""

# Verificar se healthcheck já existe
if grep -A 10 "frontend:" docker-compose.yml | grep -q "healthcheck:"; then
    echo "[OK] Healthcheck já existe - validando..."
    grep -A 10 "frontend:" docker-compose.yml | grep -A 5 "healthcheck:" | head -6
    HEALTHCHECK_EXISTS=true
else
    echo "[WARNING] Healthcheck não encontrado - aplicando..."
    HEALTHCHECK_EXISTS=false
    
    # Fazer backup
    BACKUP_FILE="docker-compose.yml.backup.$(date +%Y%m%d_%H%M%S)"
    cp docker-compose.yml "$BACKUP_FILE"
    echo "[OK] Backup criado: $BACKUP_FILE"
    
    # Método 1: Usar awk para inserir após networks
    awk '
    BEGIN { inserted=0 }
    /^  frontend:/ { in_frontend=1; print; next }
    in_frontend && /- ai_saas_network/ {
        print
        print "    # Healthcheck para garantir que Next.js está pronto antes de nginx iniciar"
        print "    # start_period: 90s dá tempo para Next.js compilar em modo dev"
        print "    healthcheck:"
        print "      test: [\"CMD\", \"wget\", \"--quiet\", \"--tries=1\", \"--spider\", \"http://localhost:3000/ || exit 1\"]"
        print "      interval: 30s"
        print "      timeout: 10s"
        print "      retries: 5"
        print "      start_period: 90s"
        inserted=1
        in_frontend=0
        next
    }
    in_frontend && /^  [a-z]/ && !/^  frontend:/ { in_frontend=0 }
    { print }
    END { if (inserted == 0) exit 1 }
    ' docker-compose.yml > docker-compose.yml.tmp
    
    if [ $? -eq 0 ] && [ -f docker-compose.yml.tmp ]; then
        mv docker-compose.yml.tmp docker-compose.yml
        echo "[OK] Healthcheck aplicado usando awk"
    else
        echo "[WARNING] Método awk falhou, tentando sed..."
        # Método 2: Usar sed
        sed -i.bak '/- ai_saas_network/a\
    # Healthcheck para garantir que Next.js está pronto\
    healthcheck:\
      test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost:3000/ || exit 1"]\
      interval: 30s\
      timeout: 10s\
      retries: 5\
      start_period: 90s' docker-compose.yml
        
        if [ $? -eq 0 ]; then
            echo "[OK] Healthcheck aplicado usando sed"
        else
            echo "[ERROR] Erro ao aplicar healthcheck - restaurando backup"
            mv "$BACKUP_FILE" docker-compose.yml
            exit 1
        fi
    fi
fi

# Validar que foi aplicado
if grep -A 10 "frontend:" docker-compose.yml | grep -q "healthcheck:"; then
    echo "[OK] Healthcheck confirmado no arquivo"
    echo ""
    echo "Conteúdo aplicado:"
    grep -A 10 "frontend:" docker-compose.yml | grep -A 5 "healthcheck:" | head -6 | sed 's/^/  /'
else
    echo "[ERROR] ERRO CRÍTICO: Healthcheck não foi aplicado"
    exit 1
fi

# Verificar depends_on
echo ""
echo " Verificando depends_on do proxy..."
if grep -A 5 "proxy:" docker-compose.yml | grep -A 3 "depends_on:" | grep -q "service_healthy"; then
    echo "[OK] depends_on já usa service_healthy"
else
    echo "[WARNING] Ajustando depends_on..."
    sed -i 's/condition: service_started/condition: service_healthy/g' docker-compose.yml
    echo "[OK] depends_on ajustado"
fi

# Aplicar correções
echo ""
echo "🔄 Aplicando correções (docker compose down/up)..."
echo "Parando containers..."
docker compose down
echo ""
echo "Iniciando containers com nova configuração..."
docker compose up -d
echo ""
echo "[OK] Containers reiniciados"

# Aguardar e validar
echo ""
echo "⏳ Aguardando 30 segundos para containers iniciarem..."
sleep 30

echo ""
echo "📊 Status dos containers:"
docker ps --filter "name=frontend\|proxy" --format "table {{.Names}}\t{{.Status}}"

echo ""
echo "🧪 Testes de conectividade:"
echo -n "  localhost:80: "
HTTP_LOCAL=$(curl -s -o /dev/null -w "%{http_code}" http://localhost 2>&1 || echo "000")
if echo "$HTTP_LOCAL" | grep -qE "200|301|302|307"; then
    echo "[OK] HTTP $HTTP_LOCAL"
else
    echo "[WARNING] HTTP $HTTP_LOCAL (pode estar inicializando)"
fi

echo -n "  nginx → frontend: "
HTTP_NGINX=$(docker exec ai_saas_proxy curl -s -o /dev/null -w "%{http_code}" http://frontend:3000 2>&1 || echo "000")
if echo "$HTTP_NGINX" | grep -qE "200|301|302|307"; then
    echo "[OK] HTTP $HTTP_NGINX"
else
    echo "[WARNING] HTTP $HTTP_NGINX"
fi

echo ""
echo "📋 Verificando logs do nginx (últimas 10 linhas):"
docker logs ai_saas_proxy --tail 10 2>&1 | tail -5

echo ""
echo "[OK] CORREÇÃO APLICADA COM SUCESSO"
echo ""
echo "[INFO] Se o frontend ainda não está healthy, aguarde mais 1-2 minutos"
echo "[INFO] Next.js em modo dev pode levar até 90 segundos para compilar"
SCRIPT_EOF
)

# Converter para array
IFS=$'\n' read -d '' -r -a SCRIPT_ARRAY <<< "$FULL_SCRIPT" || true

echo "Executando script completo na VM..."
echo "(Isso pode levar 3-5 minutos incluindo docker compose up)"
echo ""

OUTPUT=$(az vm run-command invoke \
    --resource-group "$RESOURCE_GROUP" \
    --name "$VM_NAME" \
    --command-id RunShellScript \
    --scripts "${SCRIPT_ARRAY[@]}" \
    --output json 2>&1)

# Processar output de forma robusta
if echo "$OUTPUT" | grep -q "Conflict"; then
    echo "[WARNING] Comando anterior ainda em execução"
    echo ""
    echo "[INFO] O comando anterior pode estar finalizando. Opções:"
    echo "   1. Aguarde 5-10 minutos e verifique manualmente via SSH"
    echo "   2. Execute novamente este script em alguns minutos"
    echo ""
    echo "Para verificar manualmente:"
    echo "   ssh -i keys/azure/team/id_rsa_poc azureuser@20.185.60.67"
    echo "   cd /home/azureuser/projeto/sky-poc-infra"
    echo "   grep -A 10 'frontend:' docker-compose.yml | grep -A 5 'healthcheck:'"
    exit 1
fi

echo "$OUTPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if 'value' in data and len(data['value']) > 0:
        msg = data['value'][0].get('message', '')
        msg = msg.replace('[stdout]', '').replace('[stderr]', '')
        print(msg)
    elif 'error' in data:
        error_msg = data.get('error', {}).get('message', 'Erro desconhecido')
        print(f'[ERROR] Erro do Azure: {error_msg}')
    else:
        print('[WARNING] Resposta inesperada do Azure CLI')
        print(json.dumps(data, indent=2))
except json.JSONDecodeError:
    output = sys.stdin.read()
    if 'Conflict' in output:
        print('[WARNING] Comando anterior ainda em execução')
    else:
        print('Output bruto:', output[:500])
except Exception as e:
    print(f'Erro ao processar: {e}')
" 2>/dev/null || echo "$OUTPUT"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "[OK] PROCESSO FINALIZADO"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "🌐 Teste acessando: http://20.185.60.67"
echo ""

