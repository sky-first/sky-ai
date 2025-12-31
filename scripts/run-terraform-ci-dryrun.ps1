# Simula localmente as etapas críticas do GitHub Actions antes do deploy:
# - terraform init (com backend remoto se TF_BACKEND_* estiverem definidos; senão backend=false)
# - terraform workspace select/new
# - terraform validate
# - terraform plan (gera tfplan)
#
# Requisitos:
# - Azure CLI autenticado: az login (ou já logado)
# - (O script baixa automaticamente o terraform.exe se não existir)
#
# Uso:
#   .\scripts\run-terraform-ci-dryrun.ps1 -Environment staging -TerraformVersion 1.9.0
#
param(
    [ValidateSet("staging", "prod", "poc-sky")]
    [string]$Environment = "staging",
    [string]$TerraformVersion = "1.9.0",
    [switch]$UseDocker,
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Comando não encontrado: $Name. Instale/configure e tente novamente."
    }
}

Require-Command "az"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$TfDir = (Join-Path $RepoRoot "infra\azure")
$TfVars = (Join-Path $TfDir ("terraform.tfvars.{0}" -f $Environment))

if (-not (Test-Path $TfVars)) {
    throw "Arquivo tfvars não encontrado: $TfVars"
}

Write-Host "=== Dry-run local (CI-like) Terraform ===" -ForegroundColor Cyan
Write-Host "Repo: $RepoRoot" -ForegroundColor Yellow
Write-Host "Terraform dir: $TfDir" -ForegroundColor Yellow
Write-Host "tfvars: $TfVars" -ForegroundColor Yellow
Write-Host "Terraform version: $TerraformVersion" -ForegroundColor Yellow
Write-Host "Mode: $(if ($UseDocker) { 'docker (azure-cli + terraform)' } else { 'local terraform.exe' })" -ForegroundColor Yellow
Write-Host ""

# Pegar subscription id do contexto do Azure CLI (precisa estar logado)
try {
    $SubId = (az account show --query id -o tsv).Trim()
} catch {
    throw "Falha ao ler subscription via Azure CLI. Rode 'az login' e tente novamente."
}
if (-not $SubId) { throw "ARM_SUBSCRIPTION_ID não pôde ser obtido via Azure CLI." }

# Backend remoto (igual workflow) - opcional
$BackendRg = $env:TF_BACKEND_RESOURCE_GROUP
$BackendSa = $env:TF_BACKEND_STORAGE_ACCOUNT
$BackendContainer = $env:TF_BACKEND_CONTAINER
$BackendKeyPrefix = $env:TF_BACKEND_KEY_PREFIX

$UseRemoteBackend = ($BackendRg -and $BackendSa -and $BackendContainer)

$BackendFile = (Join-Path $TfDir "backend.hcl")
if (Test-Path $BackendFile) {
    Remove-Item -Force $BackendFile
}

try {
    if ($UseRemoteBackend) {
        $Prefix = if ($BackendKeyPrefix) { $BackendKeyPrefix } else { "poc-deploy" }
        $StateKey = ("{0}-{1}.tfstate" -f $Prefix, $Environment)

        # Para inicializar backend azurerm localmente sem depender de OIDC/Managed Identity,
        # usamos ARM_ACCESS_KEY (storage account key) obtida via Azure CLI no host.
        # Não imprimimos a key em logs.
        $ArmAccessKey = ""
        try {
            $ArmAccessKey = (az storage account keys list `
                --resource-group $BackendRg `
                --account-name $BackendSa `
                --query "[0].value" -o tsv).Trim()
        } catch {
            throw "Falha ao obter Storage Account key via Azure CLI (necessario para init do backend remoto local)."
        }
        if (-not $ArmAccessKey) {
            throw "Nao foi possivel obter Storage Account key (ARM_ACCESS_KEY) para o backend remoto."
        }

        # Exportar para a sessão atual (Terraform local usa essa env var); não imprimir em logs
        $env:ARM_ACCESS_KEY = $ArmAccessKey

        @"
resource_group_name  = "$BackendRg"
storage_account_name = "$BackendSa"
container_name       = "$BackendContainer"
key                  = "$StateKey"
"@ | Out-File -FilePath $BackendFile -Encoding ascii

        Write-Host "Backend remoto habilitado (backend.hcl gerado):" -ForegroundColor Green
        Write-Host "  RG: $BackendRg"
        Write-Host "  Storage: $BackendSa"
        Write-Host "  Container: $BackendContainer"
        Write-Host "  Key: $StateKey"
        Write-Host "  Auth: ARM_ACCESS_KEY (usando Storage Account key via Azure CLI)" -ForegroundColor Green
    } else {
        Write-Host "Backend remoto NAO configurado (TF_BACKEND_* ausentes). Usando -backend=false." -ForegroundColor Yellow
        Write-Host "Para testar igual ao GitHub Actions, defina: TF_BACKEND_RESOURCE_GROUP, TF_BACKEND_STORAGE_ACCOUNT, TF_BACKEND_CONTAINER (e opcional TF_BACKEND_KEY_PREFIX)." -ForegroundColor Yellow
    }

function Ensure-TerraformExe([string]$Version) {
    $cmd = Get-Command terraform -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Path }

    $toolsDir = Join-Path $RepoRoot ".tools\\terraform\\$Version"
    $exePath = Join-Path $toolsDir "terraform.exe"
    if (Test-Path $exePath) { return $exePath }

    New-Item -ItemType Directory -Force -Path $toolsDir | Out-Null
    $zipPath = Join-Path $toolsDir "terraform_$Version.zip"
    $url = "https://releases.hashicorp.com/terraform/$Version/terraform_${Version}_windows_amd64.zip"

    Write-Host "Baixando Terraform $Version..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri $url -OutFile $zipPath
    Expand-Archive -Path $zipPath -DestinationPath $toolsDir -Force
    Remove-Item -Force $zipPath

    if (-not (Test-Path $exePath)) {
        throw "Falha ao preparar terraform.exe em $exePath"
    }
    return $exePath
}

function TfLocal([string[]]$TfArgs) {
    $tfExe = Ensure-TerraformExe $TerraformVersion
    # -chdir garante que caminhos relativos (tfvars/keys) funcionem como no CI
    & $tfExe "-chdir=$TfDir" @TfArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao executar: terraform $($TfArgs -join ' ')"
    }
}

function TfDocker([string[]]$TfArgs) {
    # Rodar Terraform dentro de um container que já tem Azure CLI + Terraform,
    # montando o repo e reaproveitando o login do Azure CLI do host via ~/.azure.
    $img = "terraform-azurecli:$TerraformVersion"
    $dockerfileDir = Join-Path $RepoRoot "docker\\terraform-azurecli"

    # Build idempotente (só baixa se não existir localmente)
    $existing = (& docker images -q $img 2>$null)
    if (-not $existing) {
        Write-Host "Construindo imagem Docker: $img" -ForegroundColor Cyan
        & docker build `
            -t $img `
            --build-arg ("TERRAFORM_VERSION={0}" -f $TerraformVersion) `
            $dockerfileDir
        if ($LASTEXITCODE -ne 0) { throw "Falha ao buildar imagem Docker $img" }
    }

    # Auth dentro do container:
    # - Recomendado (não-interativo): Service Principal via env vars (ARM_CLIENT_ID/ARM_TENANT_ID/ARM_CLIENT_SECRET)
    # - Alternativa (interativa): az login DENTRO do container (não suportado por este script).
    $spClientId = $env:ARM_CLIENT_ID
    $spTenantId = $env:ARM_TENANT_ID
    $spClientSecret = $env:ARM_CLIENT_SECRET

    if (-not $spClientId -or -not $spTenantId -or -not $spClientSecret) {
        Write-Host "ERRO: -UseDocker requer autenticação não-interativa no container." -ForegroundColor Red
        Write-Host "Defina no seu ambiente: ARM_CLIENT_ID, ARM_TENANT_ID e ARM_CLIENT_SECRET (Service Principal)." -ForegroundColor Yellow
        Write-Host "Obs: Azure CLI instalado no host não é suficiente dentro do container sem credenciais." -ForegroundColor Yellow
        throw "Credenciais ARM_CLIENT_* ausentes para modo Docker."
    }

    $cmd = @(
        "run", "--rm",
        "-v", ("{0}:/workspace" -f $RepoRoot),
        "-w", "/workspace/infra/azure"
    ) + @(
        # Variáveis úteis para o provider/backends (quando aplicável)
        "-e", ("ARM_SUBSCRIPTION_ID={0}" -f $SubId),
        "-e", ("ARM_TENANT_ID={0}" -f $spTenantId),
        "-e", ("ARM_CLIENT_ID={0}" -f $spClientId),
        "-e", ("ARM_CLIENT_SECRET={0}" -f $spClientSecret),
        "-e", "ARM_USE_OIDC=false",
        # Para backend remoto quando usado via ARM_ACCESS_KEY (o script seta essa env var)
        "-e", ("ARM_ACCESS_KEY={0}" -f (if ($env:ARM_ACCESS_KEY) { $env:ARM_ACCESS_KEY } else { "" })),
        $img
    ) + $TfArgs

    & docker @cmd
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao executar (docker): terraform $($TfArgs -join ' ')"
    }
}

Write-Host ""
Write-Host "== Terraform init ==" -ForegroundColor Cyan
if ($UseRemoteBackend) {
    # Backend remoto + provider AzureRM: usar Terraform local (tem acesso ao Azure CLI).
    if ($UseDocker) {
        TfDocker @("init", "-input=false", "-upgrade", "-backend-config=backend.hcl")
    } else {
        TfLocal @("init", "-input=false", "-upgrade", "-backend-config=backend.hcl")
    }
} else {
    if ($UseDocker) {
        TfDocker @("init", "-input=false", "-upgrade", "-backend=false")
    } else {
        TfLocal @("init", "-input=false", "-upgrade", "-backend=false")
    }
}

if ($UseRemoteBackend) {
    Write-Host ""
    Write-Host "== Workspace ==" -ForegroundColor Cyan
    try {
        if ($UseDocker) {
            TfDocker @("workspace", "select", $Environment)
        } else {
            TfLocal @("workspace", "select", $Environment)
        }
    } catch {
        if ($UseDocker) {
            TfDocker @("workspace", "new", $Environment)
        } else {
            TfLocal @("workspace", "new", $Environment)
        }
    }
} else {
    Write-Host ""
    Write-Host "== Workspace ==" -ForegroundColor Cyan
    Write-Host "INFO: backend=false - pulando workspace (workspaces exigem backend inicializado)." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "== Terraform validate ==" -ForegroundColor Cyan
if ($UseRemoteBackend) {
    if ($UseDocker) {
        TfDocker @("validate", "-no-color")
    } else {
        TfLocal @("validate", "-no-color")
    }
} else {
    if ($UseDocker) {
        TfDocker @("validate", "-no-color")
    } else {
        TfLocal @("validate", "-no-color")
    }
}

Write-Host ""
Write-Host "== Terraform plan ==" -ForegroundColor Cyan
if ($UseRemoteBackend) {
    if ($UseDocker) {
        TfDocker @("plan", "-no-color", "-var-file=terraform.tfvars.$Environment", "-var", "subscription_id=$SubId", "-out=tfplan")
    } else {
        TfLocal @("plan", "-no-color", "-var-file=terraform.tfvars.$Environment", "-var", "subscription_id=$SubId", "-out=tfplan")
    }
} else {
    Write-Host "INFO: Sem backend remoto nao e possivel rodar terraform plan neste projeto (backend azurerm exige init com backend.hcl)." -ForegroundColor Yellow
    Write-Host "Defina TF_BACKEND_RESOURCE_GROUP / TF_BACKEND_STORAGE_ACCOUNT / TF_BACKEND_CONTAINER e rode novamente para executar o plan." -ForegroundColor Yellow
}

Write-Host ""
Write-Host ""
Write-Host "OK: Dry-run concluido. Se quiser aplicar localmente (cuidado), rode no CI ou execute: terraform apply tfplan" -ForegroundColor Green
} finally {
    # Limpar secrets da sessão
    if ($env:ARM_ACCESS_KEY) {
        $env:ARM_ACCESS_KEY = $null
    }

    # Limpar artefatos gerados, a menos que o usuário queira manter (para debug)
    if (-not $KeepArtifacts) {
        try { if (Test-Path $BackendFile) { Remove-Item -Force $BackendFile } } catch {}
        try {
            $PlanFile = (Join-Path $TfDir "tfplan")
            if (Test-Path $PlanFile) { Remove-Item -Force $PlanFile }
        } catch {}
    }
}
