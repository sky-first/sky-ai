# scripts/fix-env-permissions.ps1
# Verifica e corrige permissões do .env (Windows)
# Nota: No Windows, permissões são diferentes, mas podemos verificar se arquivo existe

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
$EnvFile = Join-Path $ProjectDir ".env"

Write-Host "╔════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║     Verificar/Corrigir Permissões do .env          ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $EnvFile)) {
    Write-Host ".env não encontrado em $EnvFile" -ForegroundColor Yellow
    Write-Host "Isso é normal se você ainda não criou o arquivo" -ForegroundColor Yellow
    exit 0
}

Write-Host "✅ Arquivo .env encontrado" -ForegroundColor Green
Write-Host ""

# No Windows, permissões são gerenciadas pelo sistema de arquivos
# Verificar se arquivo não está sendo rastreado pelo git
Write-Host "Verificando se .env está no .gitignore..." -ForegroundColor Blue

$GitIgnorePath = Join-Path $ProjectDir ".gitignore"
if (Test-Path $GitIgnorePath) {
    $GitIgnoreContent = Get-Content $GitIgnorePath -Raw
    if ($GitIgnoreContent -match "\.env") {
        Write-Host "✅ .env está no .gitignore" -ForegroundColor Green
    } else {
        Write-Host "⚠️  .env NÃO está no .gitignore" -ForegroundColor Yellow
        Write-Host "Adicionando..." -ForegroundColor Blue
        Add-Content -Path $GitIgnorePath -Value "`n.env"
        Write-Host "✅ .env adicionado ao .gitignore" -ForegroundColor Green
    }
} else {
    Write-Host "⚠️  .gitignore não encontrado" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Nota sobre permissões no Windows:" -ForegroundColor Cyan
Write-Host "  - No Windows, permissões são gerenciadas pelo sistema" -ForegroundColor Gray
Write-Host "  - O arquivo .env deve estar acessível apenas para você" -ForegroundColor Gray
Write-Host "  - Na VM Linux, use: ./scripts/fix-env-permissions.sh" -ForegroundColor Gray
Write-Host ""

# Verificar se está sendo rastreado pelo git
Write-Host "Verificando se .env está sendo rastreado pelo git..." -ForegroundColor Blue
try {
    $null = git ls-files --error-unmatch .env 2>&1
    Write-Host "❌ .env está sendo rastreado pelo git!" -ForegroundColor Red
    Write-Host "Removendo do índice..." -ForegroundColor Yellow
    git rm --cached .env
    Write-Host "✅ .env removido do índice do git" -ForegroundColor Green
} catch {
    Write-Host "✅ .env não está sendo rastreado pelo git" -ForegroundColor Green
}

Write-Host ""
Write-Host "Verificacao concluida!" -ForegroundColor Green
Write-Host ""

