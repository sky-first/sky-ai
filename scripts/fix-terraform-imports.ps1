# Script PowerShell para importar recursos existentes no Azure para o Terraform
# Resolve os problemas de import faltante (Action Group) e conflito de IP público

param(
    [string]$Environment = "staging"
)

$ErrorActionPreference = "Stop"

Write-Host "=== Script de Correção de Imports do Terraform ===" -ForegroundColor Cyan
Write-Host ""

# Variáveis
$SubscriptionId = if ($env:ARM_SUBSCRIPTION_ID) { $env:ARM_SUBSCRIPTION_ID } else { (az account show --query id -o tsv) }
$ResourceGroupName = "rg-ai-saas-$Environment"

Write-Host "Ambiente: $Environment" -ForegroundColor Yellow
Write-Host "Subscription ID: $SubscriptionId" -ForegroundColor Yellow
Write-Host "Resource Group: $ResourceGroupName" -ForegroundColor Yellow
Write-Host ""

# Verificar se está no diretório correto
if (-not (Test-Path "main.tf") -and -not (Test-Path "../main.tf")) {
    Write-Host "ERRO: Execute este script do diretório infra/azure ou da raiz do projeto" -ForegroundColor Red
    exit 1
}

# Navegar para o diretório do Terraform se necessário
if (Test-Path "../main.tf") {
    Set-Location ..
}

$TfVarsFile = "terraform.tfvars.$Environment"

if (-not (Test-Path $TfVarsFile)) {
    Write-Host "ERRO: Arquivo $TfVarsFile não encontrado" -ForegroundColor Red
    exit 1
}

# Nomes dos recursos
$ActionGroupName = "ai-saas-alerts-$Environment"
$NicNameExpected = "ai-saas-nic-$Environment"
$NicNameLegacy = "ai-saas-nic"
$PipName = "ai-saas-public-ip-$Environment"

# IDs ARM
$ActionGroupId = "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroupName/providers/Microsoft.Insights/actionGroups/$ActionGroupName"

Write-Host "=== 1. Importando Action Group ===" -ForegroundColor Cyan
$actionGroupExists = az monitor action-group show --resource-group $ResourceGroupName --name $ActionGroupName --query id -o tsv 2>$null

if ($actionGroupExists) {
    Write-Host "Action Group existe no Azure: $ActionGroupName" -ForegroundColor Green
    
    $stateCheck = terraform state show azurerm_monitor_action_group.main 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ Action Group já está no estado do Terraform" -ForegroundColor Green
    } else {
        Write-Host "Importando Action Group..." -ForegroundColor Yellow
        terraform import `
            -var-file="$TfVarsFile" `
            -var="subscription_id=$SubscriptionId" `
            azurerm_monitor_action_group.main "$ActionGroupId"
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✅ Action Group importado com sucesso" -ForegroundColor Green
        } else {
            Write-Host "❌ Erro ao importar Action Group" -ForegroundColor Red
        }
    }
} else {
    Write-Host "ℹ️  Action Group não existe no Azure: $ActionGroupName" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== 2. Verificando conflito de IP público com NIC antiga ===" -ForegroundColor Cyan

# Verificar se IP público existe
$pipExists = az network public-ip show --resource-group $ResourceGroupName --name $PipName --query id -o tsv 2>$null

if ($pipExists) {
    Write-Host "IP público existe: $PipName" -ForegroundColor Green
    
    # Obter ID da configuração de IP associada
    $ipConfigId = az network public-ip show --resource-group $ResourceGroupName --name $PipName --query "ipConfiguration.id" -o tsv 2>$null
    
    if ($ipConfigId) {
        # Extrair nome da NIC do ID (formato: .../networkInterfaces/NIC_NAME/ipConfigurations/...)
        if ($ipConfigId -match '/networkInterfaces/([^/]+)/ipConfigurations/') {
            $currentNicName = $matches[1]
            
            # Antes de tentar desanexar, tente importar a NIC que já existe (isso evita o apply tentar criar outra NIC)
            if ($currentNicName) {
                Write-Host ""
                Write-Host "=== 2.1. Importando NIC existente (se necessário) ===" -ForegroundColor Cyan
                $nicId = az network nic show --resource-group $ResourceGroupName --name $currentNicName --query id -o tsv 2>$null
                if ($nicId) {
                    $nicStateCheck = terraform state show azurerm_network_interface.main 2>$null
                    if ($LASTEXITCODE -eq 0) {
                        Write-Host "✅ NIC já está no estado do Terraform" -ForegroundColor Green
                    } else {
                        Write-Host "Importando NIC existente: $currentNicName" -ForegroundColor Yellow
                        terraform import `
                            -var-file="$TfVarsFile" `
                            -var="subscription_id=$SubscriptionId" `
                            azurerm_network_interface.main "$nicId"
                        if ($LASTEXITCODE -eq 0) {
                            Write-Host "✅ NIC importada com sucesso" -ForegroundColor Green
                        } else {
                            Write-Host "⚠️  Aviso: Erro ao importar NIC (seguindo com diagnóstico)" -ForegroundColor Yellow
                        }
                    }
                }
            }

            $expectedNicForEnv = $NicNameExpected
            # Se o ambiente usa NIC legada (sem sufixo), considere isso como esperado também
            if ($Environment -eq "staging" -and $currentNicName -eq $NicNameLegacy) {
                $expectedNicForEnv = $NicNameLegacy
            }

            if ($currentNicName -and $currentNicName -ne $expectedNicForEnv) {
                Write-Host "⚠️  IP público está associado à NIC: $currentNicName (esperado: $expectedNicForEnv)" -ForegroundColor Yellow
                Write-Host "➡️  Desanexando IP público da NIC antiga..." -ForegroundColor Yellow
                
                # Tentar desanexar
                az network nic ip-config update `
                    --resource-group $ResourceGroupName `
                    --nic-name $currentNicName `
                    --name "internal" `
                    --remove public-ip-address 2>&1 | Out-Null
                
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "✅ IP público desanexado da NIC antiga: $currentNicName" -ForegroundColor Green
                } else {
                    Write-Host "⚠️  Aviso: Não foi possível desanexar IP público" -ForegroundColor Yellow
                    Write-Host "   A NIC antiga pode estar em uso ou não existir mais"
                }
            } else {
                Write-Host "✅ IP público está associado à NIC correta ou não está associado" -ForegroundColor Green
            }
        }
    } else {
        Write-Host "✅ IP público não está associado a nenhuma NIC" -ForegroundColor Green
    }
} else {
    Write-Host "ℹ️  IP público não existe no Azure: $PipName" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== 3. Verificando estado do Terraform ===" -ForegroundColor Cyan
terraform state list | Select-String -Pattern "(azurerm_monitor_action_group.main|azurerm_network_interface.main)"

Write-Host ""
Write-Host "✅ Script de correção concluído!" -ForegroundColor Green
Write-Host ""
Write-Host "Próximos passos:" -ForegroundColor Cyan
Write-Host "1. Execute: terraform plan -var-file=`"$TfVarsFile`" -var=`"subscription_id=$SubscriptionId`""
Write-Host "2. Verifique se não há mais erros de import"
Write-Host "3. Execute: terraform apply (se o plan estiver OK)"

