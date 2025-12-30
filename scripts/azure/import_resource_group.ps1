# Script para importar Resource Group existente no Terraform
# Uso: .\scripts\azure\import_resource_group.ps1 -Environment staging

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("staging", "prod", "poc-sky")]
    [string]$Environment,
    
    [Parameter(Mandatory=$false)]
    [string]$SubscriptionId = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Import Resource Group - Terraform" -ForegroundColor Cyan
Write-Host "Environment: $Environment" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# Navegar para diretório do Terraform
$TerraformDir = Join-Path $PSScriptRoot "..\..\infra\azure"
if (-not (Test-Path $TerraformDir)) {
    Write-Host "ERRO: Diretório do Terraform não encontrado: $TerraformDir" -ForegroundColor Red
    exit 1
}

Push-Location $TerraformDir
try {
    # Obter Subscription ID
    if ([string]::IsNullOrEmpty($SubscriptionId)) {
        Write-Host "Obtendo Subscription ID do Azure CLI..." -ForegroundColor Yellow
        $SubscriptionId = az account show --query id -o tsv
        if (-not $SubscriptionId) {
            Write-Host "ERRO: Não foi possível obter Subscription ID. Faça login: az login" -ForegroundColor Red
            exit 1
        }
    }
    Write-Host "Subscription ID: $SubscriptionId" -ForegroundColor Green

    # Determinar nome do Resource Group baseado no ambiente
    $ResourceGroupName = switch ($Environment) {
        "staging" { "rg-ai-saas-staging" }
        "prod" { "rg-ai-saas-prod" }
        "poc-sky" { "rg-ai-saas-poc-sky" }
    }

    Write-Host "`nVerificando se Resource Group existe no Azure..." -ForegroundColor Yellow
    $RGInfo = az group show --name $ResourceGroupName --query "{id:id, name:name, location:location}" -o json 2>$null
    if (-not $RGInfo) {
        Write-Host "ERRO: Resource Group não existe no Azure: $ResourceGroupName" -ForegroundColor Red
        Write-Host "Não é necessário importar um Resource Group que não existe." -ForegroundColor Yellow
        exit 1
    }
    
    $RG = $RGInfo | ConvertFrom-Json
    Write-Host "✅ Resource Group encontrado:" -ForegroundColor Green
    Write-Host "   Nome: $($RG.name)" -ForegroundColor White
    Write-Host "   Location: $($RG.location)" -ForegroundColor White
    Write-Host "   ID: $($RG.id)" -ForegroundColor White

    # Verificar se Terraform está instalado
    Write-Host "`nVerificando se Terraform está instalado..." -ForegroundColor Yellow
    $TerraformVersion = terraform version 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERRO: Terraform não está instalado ou não está no PATH" -ForegroundColor Red
        Write-Host "Instale o Terraform: https://www.terraform.io/downloads" -ForegroundColor Yellow
        Write-Host "Ou execute este import via GitHub Actions workflow" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "✅ Terraform encontrado" -ForegroundColor Green
    Write-Host $TerraformVersion -ForegroundColor Gray

    # Verificar arquivo tfvars
    $TfvarsFile = "terraform.tfvars.$Environment"
    if (-not (Test-Path $TfvarsFile)) {
        Write-Host "ERRO: Arquivo tfvars não encontrado: $TfvarsFile" -ForegroundColor Red
        exit 1
    }
    Write-Host "`n✅ Arquivo tfvars encontrado: $TfvarsFile" -ForegroundColor Green

    # Inicializar Terraform
    Write-Host "`nInicializando Terraform..." -ForegroundColor Yellow
    terraform init
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERRO: Falha ao inicializar Terraform" -ForegroundColor Red
        exit 1
    }
    Write-Host "✅ Terraform inicializado" -ForegroundColor Green

    # Selecionar/Criar workspace
    Write-Host "`nSelecionando workspace: $Environment..." -ForegroundColor Yellow
    terraform workspace select $Environment 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Workspace não existe, criando..." -ForegroundColor Yellow
        terraform workspace new $Environment
        if ($LASTEXITCODE -ne 0) {
            Write-Host "ERRO: Falha ao criar workspace" -ForegroundColor Red
            exit 1
        }
    }
    Write-Host "✅ Workspace selecionado: $Environment" -ForegroundColor Green

    # Verificar se Resource Group já está no estado
    Write-Host "`nVerificando se Resource Group já está no estado do Terraform..." -ForegroundColor Yellow
    $StateCheck = terraform state show azurerm_resource_group.main 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "⚠️  Resource Group já está no estado do Terraform!" -ForegroundColor Yellow
        Write-Host "Estado atual:" -ForegroundColor Yellow
        Write-Host $StateCheck -ForegroundColor Gray
        Write-Host "`nDeseja continuar mesmo assim? (S/N)" -ForegroundColor Yellow
        $Response = Read-Host
        if ($Response -ne "S" -and $Response -ne "s") {
            Write-Host "Operação cancelada." -ForegroundColor Yellow
            exit 0
        }
    }

    # Executar import
    Write-Host "`nExecutando import do Resource Group..." -ForegroundColor Yellow
    $ResourceId = "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroupName"
    
    Write-Host "Comando:" -ForegroundColor Cyan
    Write-Host "  terraform import \`" -ForegroundColor Gray
    Write-Host "    -var-file=`"$TfvarsFile`" \`" -ForegroundColor Gray
    Write-Host "    -var=`"subscription_id=$SubscriptionId`" \`" -ForegroundColor Gray
    Write-Host "    azurerm_resource_group.main \`" -ForegroundColor Gray
    Write-Host "    `"$ResourceId`"" -ForegroundColor Gray
    Write-Host ""

    terraform import `
        -var-file="$TfvarsFile" `
        -var="subscription_id=$SubscriptionId" `
        azurerm_resource_group.main `
        $ResourceId

    if ($LASTEXITCODE -ne 0) {
        Write-Host "`n❌ ERRO: Falha ao importar Resource Group" -ForegroundColor Red
        Write-Host "Verifique os logs acima para mais detalhes." -ForegroundColor Yellow
        exit 1
    }

    Write-Host "`n✅ Import realizado com sucesso!" -ForegroundColor Green

    # Verificar estado
    Write-Host "`nVerificando estado após import..." -ForegroundColor Yellow
    terraform state show azurerm_resource_group.main
    if ($LASTEXITCODE -ne 0) {
        Write-Host "⚠️  WARNING: Não foi possível verificar o estado (pode ser normal)" -ForegroundColor Yellow
    }

    # Verificar plan
    Write-Host "`nVerificando plan (não deve tentar criar Resource Group)..." -ForegroundColor Yellow
    terraform plan `
        -var-file="$TfvarsFile" `
        -var="subscription_id=$SubscriptionId" `
        -no-color | Select-String -Pattern "azurerm_resource_group.main" -Context 2,2

    Write-Host "`n========================================" -ForegroundColor Cyan
    Write-Host "✅ Import concluído com sucesso!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "`nPróximos passos:" -ForegroundColor Yellow
    Write-Host "1. Verifique o plan completo: terraform plan -var-file=`"$TfvarsFile`" -var=`"subscription_id=$SubscriptionId`"" -ForegroundColor White
    Write-Host "2. Se tudo estiver correto, o pipeline do GitHub Actions deve funcionar agora" -ForegroundColor White
    Write-Host "3. O Resource Group está agora gerenciado pelo Terraform" -ForegroundColor White

} finally {
    Pop-Location
}

