# Script para executar diagnóstico na VM via Azure CLI Run Command
# Não requer SSH direto - usa Azure Run Command

param(
    [string]$ResourceGroup = "POC-SKY",
    [string]$VMName = "poc-sky",
    [string]$VMIP = "172.172.134.36"
)

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "🔍 Executando Diagnóstico Remoto na VM" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Resource Group: $ResourceGroup" -ForegroundColor Yellow
Write-Host "VM Name: $VMName" -ForegroundColor Yellow
Write-Host "VM IP: $VMIP" -ForegroundColor Yellow
Write-Host ""

# Verificar se Azure CLI está instalado
if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Host "❌ ERRO: Azure CLI não está instalado" -ForegroundColor Red
    Write-Host "   Instale em: https://aka.ms/installazurecliwindows" -ForegroundColor Yellow
    exit 1
}

# Verificar se está logado
Write-Host "Verificando autenticação Azure..." -ForegroundColor Cyan
$account = az account show 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Não está autenticado no Azure CLI" -ForegroundColor Red
    Write-Host "   Execute: az login" -ForegroundColor Yellow
    exit 1
}
Write-Host "✅ Autenticado no Azure" -ForegroundColor Green
Write-Host ""

# Script a ser executado na VM
$scriptContent = @'
set -eu
PROJECT_DIR="/home/azureuser/projeto/sky-poc-infra"
if [ ! -d "$PROJECT_DIR" ]; then
    if [ -d ~/projeto/poc-deploy ]; then
        PROJECT_DIR=~/projeto/poc-deploy
    else
        echo "❌ Diretório do projeto não encontrado"
        exit 1
    fi
fi
cd "$PROJECT_DIR"

# Baixar script de diagnóstico se não existir
if [ ! -f scripts/azure/fix-connection-issue.sh ]; then
    echo "Script de diagnóstico não encontrado localmente"
    echo "Executando diagnóstico básico..."
    
    echo "=== Status dos Containers ==="
    sudo docker compose ps || sudo docker-compose ps || sudo docker ps
    
    echo ""
    echo "=== Container Proxy ==="
    PROXY=$(sudo docker ps --format "{{.Names}}" | grep -E "proxy|nginx" | head -1)
    if [ -n "$PROXY" ]; then
        echo "Container: $PROXY"
        sudo docker logs --tail=20 "$PROXY" 2>&1 | tail -10
    else
        echo "❌ Proxy não está rodando"
    fi
    
    echo ""
    echo "=== Porta 80 ==="
    sudo ss -tlnp | grep ":80 " || sudo netstat -tlnp | grep ":80 " || echo "Porta 80 não está escutando"
    
    echo ""
    echo "=== Configuração Nginx ==="
    if [ -f docker/nginx/nginx.conf ]; then
        if grep -q "return 301 https" docker/nginx/nginx.conf && ! grep -q "# return 301 https" docker/nginx/nginx.conf; then
            echo "⚠️ PROBLEMA: nginx redirecionando para HTTPS sem certificados"
            if [ -f docker/nginx/nginx.conf.http-only ]; then
                echo "🔧 Aplicando correção..."
                sudo cp docker/nginx/nginx.conf docker/nginx/nginx.conf.backup
                sudo cp docker/nginx/nginx.conf.http-only docker/nginx/nginx.conf
                sudo docker compose restart proxy || sudo docker restart "$PROXY" 2>/dev/null || true
                echo "✅ Correção aplicada"
            fi
        fi
    fi
else
    bash scripts/azure/fix-connection-issue.sh
fi
'@

# Converter para array (necessário para Azure CLI no Windows)
$scripts = $scriptContent -split "`n"

Write-Host "Executando diagnóstico na VM..." -ForegroundColor Cyan
Write-Host ""

try {
    $output = az vm run-command invoke `
        --resource-group $ResourceGroup `
        --name $VMName `
        --command-id RunShellScript `
        --scripts $scripts `
        --output json 2>&1
    
    if ($LASTEXITCODE -eq 0) {
        $result = $output | ConvertFrom-Json
        $message = $result.value[0].message
        
        Write-Host "==========================================" -ForegroundColor Green
        Write-Host "✅ Comando executado com sucesso" -ForegroundColor Green
        Write-Host "==========================================" -ForegroundColor Green
        Write-Host ""
        
        # Extrair stdout e stderr
        if ($message -match '\[stdout\]\s*(.*?)(?=\[stderr\]|$)') {
            $stdout = $matches[1]
            Write-Host $stdout -ForegroundColor White
        }
        
        if ($message -match '\[stderr\]\s*(.*?)$') {
            $stderr = $matches[1]
            if ($stderr.Trim() -ne "") {
                Write-Host "STDERR:" -ForegroundColor Yellow
                Write-Host $stderr -ForegroundColor Red
            }
        } else {
            # Tentar extrair mensagem completa
            Write-Host $message -ForegroundColor White
        }
        
        Write-Host ""
        Write-Host "==========================================" -ForegroundColor Cyan
        Write-Host "📋 Próximos Passos" -ForegroundColor Cyan
        Write-Host "==========================================" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "1. Se o problema foi corrigido, teste a conexão:" -ForegroundColor Yellow
        Write-Host "   curl http://$VMIP/health" -ForegroundColor White
        Write-Host ""
        Write-Host "2. Se ainda houver problemas, verifique:" -ForegroundColor Yellow
        Write-Host "   - NSG permite porta 80: az network nsg rule list -g $ResourceGroup --nsg-name ai-saas-nsg-poc-sky" -ForegroundColor White
        Write-Host "   - Containers estão rodando: az vm run-command invoke -g $ResourceGroup -n $VMName --command-id RunShellScript --scripts 'sudo docker ps'" -ForegroundColor White
        Write-Host ""
        
    } else {
        Write-Host "❌ ERRO ao executar comando na VM" -ForegroundColor Red
        Write-Host $output -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "❌ ERRO: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

