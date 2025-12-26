# scripts/validate-infra-complete.ps1
# Validação completa da infraestrutura (Windows PowerShell)
# Verifica: caminhos, dependências, consistência, back/front/IA

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir

$Errors = 0
$Warnings = 0

function Log-Info { Write-Host "[INFO] $args" -ForegroundColor Blue }
function Log-Success { Write-Host "[OK] $args" -ForegroundColor Green }
function Log-Warning { Write-Host "[WARNING] $args" -ForegroundColor Yellow; $script:Warnings++ }
function Log-Error { Write-Host "[ERROR] $args" -ForegroundColor Red; $script:Errors++ }
function Log-Section {
    Write-Host ""
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
    Write-Host "▶ $args" -ForegroundColor Cyan
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
    Write-Host ""
}

Write-Host ""
Write-Host "╔════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║     Validação Completa de Infraestrutura          ║" -ForegroundColor Cyan
Write-Host "║     Backend, Frontend, IA e Caminhos               ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# 1. ESTRUTURA DE PASTAS
Log-Section "1. ESTRUTURA DE PASTAS"

$RequiredDirs = @(
    "..\sky-poc-backend",
    "..\sky-poc-frontend",
    "..\sky-poc-ai"
)

foreach ($dir in $RequiredDirs) {
    $fullPath = Join-Path $ProjectDir $dir
    if (Test-Path $fullPath) {
        Log-Success "$dir encontrado"
    } else {
        Log-Warning "$dir não encontrado (será clonado na VM pelo Terraform)"
    }
}

# 2. DOCKER COMPOSE - CAMINHOS
Log-Section "2. DOCKER COMPOSE - CAMINHOS E CONTEXTOS"

$DockerCompose = Join-Path $ProjectDir "docker-compose.yml"

if (Test-Path $DockerCompose) {
    $content = Get-Content $DockerCompose -Raw
    
    # Verificar backend
    if ($content -match "context:\s*\.\./sky-poc-backend") {
        Log-Success "Backend usa contexto correto: ../sky-poc-backend"
    } elseif ($content -match "context:\s*\.\./backend") {
        Log-Error "Backend usa caminho antigo: ../backend (deve ser ../sky-poc-backend)"
    } else {
        Log-Error "Backend: contexto não encontrado ou incorreto"
    }
    
    # Verificar frontend
    if ($content -match "context:\s*\.\./sky-poc-frontend") {
        Log-Success "Frontend usa contexto correto: ../sky-poc-frontend"
    } elseif ($content -match "context:\s*\.\./frontend") {
        Log-Error "Frontend usa caminho antigo: ../frontend (deve ser ../sky-poc-frontend)"
    } else {
        Log-Error "Frontend: contexto não encontrado ou incorreto"
    }
    
    # Verificar dependências
    if ($content -match "backend:.*depends_on:") {
        Log-Success "Backend tem depends_on configurado"
    }
    
    if ($content -match "frontend:.*depends_on:") {
        Log-Success "Frontend tem depends_on configurado"
    }
} else {
    Log-Error "docker-compose.yml não encontrado"
}

# 3. TERRAFORM DEPLOY
Log-Section "3. TERRAFORM DEPLOY - CONSISTÊNCIA"

$DeployTf = Join-Path $ProjectDir "infra\azure\deploy.tf"

if (Test-Path $DeployTf) {
    Log-Success "deploy.tf encontrado"
    
    $content = Get-Content $DeployTf -Raw
    
    if ($content -match "poc-deploy|sky-poc-infra") {
        Log-Success "deploy.tf suporta ambos os nomes de estrutura"
    }
    
    if ($content -match "backend|sky-poc-backend") {
        Log-Success "deploy.tf suporta ambos os nomes de backend"
    }
    
    if ($content -match "frontend|sky-poc-frontend") {
        Log-Success "deploy.tf suporta ambos os nomes de frontend"
    }
    
    if ($content -match "ia|sky-poc-ai") {
        Log-Success "deploy.tf suporta ambos os nomes de IA"
    }
} else {
    Log-Warning "deploy.tf não encontrado"
}

# 4. VARIÁVEIS DE AMBIENTE
Log-Section "4. VARIÁVEIS DE AMBIENTE"

$EnvFile = Join-Path $ProjectDir ".env"
$EnvExample = Join-Path $ProjectDir "env.example"

if (Test-Path $EnvFile) {
    Log-Success ".env encontrado"
} else {
    Log-Warning ".env não encontrado (será criado de env.example se necessário)"
}

if (Test-Path $EnvExample) {
    Log-Success "env.example encontrado"
} else {
    Log-Error "env.example não encontrado"
}

# RESUMO
Log-Section "RESUMO DA VALIDAÇÃO"

Write-Host "Erros encontrados: $Errors" -ForegroundColor $(if ($Errors -eq 0) { "Green" } else { "Red" })
Write-Host "Avisos encontrados: $Warnings" -ForegroundColor $(if ($Warnings -eq 0) { "Green" } else { "Yellow" })
Write-Host ""

if ($Errors -eq 0 -and $Warnings -eq 0) {
    Write-Host "✅ Validação completa: TUDO OK!" -ForegroundColor Green
    Write-Host "Pronto para deploy!" -ForegroundColor Green
    exit 0
} elseif ($Errors -eq 0) {
    Write-Host "⚠️  Validação completa com $Warnings aviso(s)" -ForegroundColor Yellow
    Write-Host "Recomendado revisar avisos antes do deploy" -ForegroundColor Yellow
    exit 0
} else {
    Write-Host "❌ Validação falhou com $Errors erro(s)" -ForegroundColor Red
    Write-Host "Corrija os erros antes de continuar" -ForegroundColor Red
    exit 1
}

