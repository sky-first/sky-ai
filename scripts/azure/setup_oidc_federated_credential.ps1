# Script para configurar Federated Identity Credential no Azure AD para GitHub Actions
# Uso: .\setup_oidc_federated_credential.ps1 -ClientId "YOUR_CLIENT_ID" -TenantId "YOUR_TENANT_ID"

param(
    [Parameter(Mandatory=$true)]
    [string]$ClientId,
    
    [Parameter(Mandatory=$true)]
    [string]$TenantId,
    
    [Parameter(Mandatory=$false)]
    [string]$Organization = "sky-first",
    
    [Parameter(Mandatory=$false)]
    [string]$Repository = "sky-poc-infra",
    
    [Parameter(Mandatory=$false)]
    [string[]]$Branches = @("staging", "main"),
    
    [Parameter(Mandatory=$false)]
    [string[]]$Environments = @("staging", "production", "poc-sky"),
    
    [Parameter(Mandatory=$false)]
    [switch]$IncludePullRequests
)

Write-Host "=== Configuração de Federated Identity Credential para GitHub Actions ===" -ForegroundColor Cyan
Write-Host ""

# Verificar se Azure CLI está instalado
$azVersion = az version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Azure CLI não está instalado. Por favor, instale antes de continuar." -ForegroundColor Red
    Write-Host "   Instale via: winget install -e --id Microsoft.AzureCLI" -ForegroundColor Yellow
    exit 1
}

Write-Host "✅ Azure CLI encontrado" -ForegroundColor Green

# Login no Azure
Write-Host ""
Write-Host "Fazendo login no Azure..." -ForegroundColor Yellow
az login --tenant $TenantId

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Falha ao fazer login no Azure" -ForegroundColor Red
    exit 1
}

Write-Host "✅ Login realizado com sucesso" -ForegroundColor Green

# Verificar se a App Registration existe
Write-Host ""
Write-Host "Verificando se a App Registration existe..." -ForegroundColor Yellow
$appExists = az ad app show --id $ClientId 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ App Registration com Client ID '$ClientId' não encontrada" -ForegroundColor Red
    Write-Host "   Verifique se o Client ID está correto" -ForegroundColor Yellow
    exit 1
}

Write-Host "✅ App Registration encontrada" -ForegroundColor Green

# Listar credentials existentes
Write-Host ""
Write-Host "Credentials existentes:" -ForegroundColor Cyan
az ad app federated-credential list --id $ClientId --query "[].{Name:name, Subject:subject}" -o table

# Criar credentials para cada branch
foreach ($branch in $Branches) {
    Write-Host ""
    Write-Host "=== Configurando credential para branch: $branch ===" -ForegroundColor Cyan
    
    $credentialName = "github-actions-$branch"
    $subject = "repo:${Organization}/${Repository}:ref:refs/heads/${branch}"
    
    $credentialJson = @{
        name = $credentialName
        issuer = "https://token.actions.githubusercontent.com"
        subject = $subject
        audiences = @("api://AzureADTokenExchange")
        description = "GitHub Actions for $branch branch"
    } | ConvertTo-Json -Compress
    
    Write-Host "Criando credential: $credentialName" -ForegroundColor Yellow
    Write-Host "Subject: $subject" -ForegroundColor Gray
    
    # Tentar criar a credential
    $result = az ad app federated-credential create --id $ClientId --parameters $credentialJson 2>&1
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ Credential '$credentialName' criada com sucesso" -ForegroundColor Green
    } else {
        if ($result -match "already exists") {
            Write-Host "⚠️  Credential '$credentialName' já existe. Pulando..." -ForegroundColor Yellow
        } else {
            Write-Host "❌ Erro ao criar credential '$credentialName':" -ForegroundColor Red
            Write-Host $result -ForegroundColor Red
        }
    }
}

# Criar credentials para cada environment
foreach ($environment in $Environments) {
    Write-Host ""
    Write-Host "=== Configurando credential para environment: $environment ===" -ForegroundColor Cyan
    
    $credentialName = "github-actions-env-$environment"
    $subject = "repo:${Organization}/${Repository}:environment:${environment}"
    
    $credentialJson = @{
        name = $credentialName
        issuer = "https://token.actions.githubusercontent.com"
        subject = $subject
        audiences = @("api://AzureADTokenExchange")
        description = "GitHub Actions for $environment environment"
    } | ConvertTo-Json -Compress
    
    Write-Host "Criando credential: $credentialName" -ForegroundColor Yellow
    Write-Host "Subject: $subject" -ForegroundColor Gray
    
    # Tentar criar a credential
    $result = az ad app federated-credential create --id $ClientId --parameters $credentialJson 2>&1
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ Credential '$credentialName' criada com sucesso" -ForegroundColor Green
    } else {
        if ($result -match "already exists") {
            Write-Host "⚠️  Credential '$credentialName' já existe. Pulando..." -ForegroundColor Yellow
        } else {
            Write-Host "❌ Erro ao criar credential '$credentialName':" -ForegroundColor Red
            Write-Host $result -ForegroundColor Red
        }
    }
}

# Criar credential para Pull Requests se solicitado
if ($IncludePullRequests) {
    Write-Host ""
    Write-Host "=== Configurando credential para Pull Requests ===" -ForegroundColor Cyan
    
    $credentialName = "github-actions-pr"
    $subject = "repo:${Organization}/${Repository}:pull_request"
    
    $credentialJson = @{
        name = $credentialName
        issuer = "https://token.actions.githubusercontent.com"
        subject = $subject
        audiences = @("api://AzureADTokenExchange")
        description = "GitHub Actions for pull requests"
    } | ConvertTo-Json -Compress
    
    Write-Host "Criando credential: $credentialName" -ForegroundColor Yellow
    Write-Host "Subject: $subject" -ForegroundColor Gray
    
    $result = az ad app federated-credential create --id $ClientId --parameters $credentialJson 2>&1
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ Credential '$credentialName' criada com sucesso" -ForegroundColor Green
    } else {
        if ($result -match "already exists") {
            Write-Host "⚠️  Credential '$credentialName' já existe. Pulando..." -ForegroundColor Yellow
        } else {
            Write-Host "❌ Erro ao criar credential '$credentialName':" -ForegroundColor Red
            Write-Host $result -ForegroundColor Red
        }
    }
}

# Listar todas as credentials após a configuração
Write-Host ""
Write-Host "=== Credentials configuradas ===" -ForegroundColor Cyan
az ad app federated-credential list --id $ClientId --query "[].{Name:name, Subject:subject, Issuer:issuer}" -o table

Write-Host ""
Write-Host "✅ Configuração concluída!" -ForegroundColor Green
Write-Host ""
Write-Host "Próximos passos:" -ForegroundColor Yellow
Write-Host "1. Verifique se os GitHub Secrets estão configurados:" -ForegroundColor White
Write-Host "   - AZURE_CLIENT_ID: $ClientId" -ForegroundColor Gray
Write-Host "   - AZURE_TENANT_ID: $TenantId" -ForegroundColor Gray
Write-Host "   - AZURE_SUBSCRIPTION_ID: (sua subscription ID)" -ForegroundColor Gray
Write-Host ""
Write-Host "2. Execute o workflow novamente para testar a autenticação" -ForegroundColor White

