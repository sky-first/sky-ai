# Script para atualizar .env com valores seguros para LOCAL
# Uso: .\scripts\update-env-local.ps1

$ErrorActionPreference = "Stop"

Write-Host "=== Atualizando .env para ambiente LOCAL ===" -ForegroundColor Cyan
Write-Host ""

$envPath = Join-Path (Join-Path $PSScriptRoot "..") ".env"

if (-not (Test-Path $envPath)) {
    Write-Host "❌ Arquivo .env não encontrado em: $envPath" -ForegroundColor Red
    Write-Host "   Crie o arquivo .env primeiro (copie de env.example)" -ForegroundColor Yellow
    exit 1
}

Write-Host "✅ Arquivo .env encontrado" -ForegroundColor Green
Write-Host ""

# Ler conteúdo atual
$content = Get-Content $envPath -Raw

# Gerar valores seguros (simulando geração)
$postgresPassword = "K8mN2pQ9rT5vW7xY0zA3bC6dE1fG4hI7j"
$redisPassword = "L3nM8qR2tV6wX9yZ1aB4cD7eF0gH5iJ8k"
$jwtSecretKey = "a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456"
$encryptionKey = "f9e8d7c6b5a4321098765432109876543210fedcba9876543210fedcba987654"

# Atualizar valores
Write-Host "Atualizando variáveis..." -ForegroundColor Yellow

# POSTGRES_PASSWORD
if ($content -match "POSTGRES_PASSWORD=.*") {
    $content = $content -replace "POSTGRES_PASSWORD=.*", "POSTGRES_PASSWORD=$postgresPassword"
    Write-Host "  ✅ POSTGRES_PASSWORD atualizado" -ForegroundColor Green
} else {
    Write-Host "  ⚠️  POSTGRES_PASSWORD não encontrado" -ForegroundColor Yellow
}

# REDIS_PASSWORD
if ($content -match "REDIS_PASSWORD=.*") {
    $content = $content -replace "REDIS_PASSWORD=.*", "REDIS_PASSWORD=$redisPassword"
    Write-Host "  ✅ REDIS_PASSWORD atualizado" -ForegroundColor Green
} else {
    Write-Host "  ⚠️  REDIS_PASSWORD não encontrado" -ForegroundColor Yellow
}

# JWT_SECRET_KEY
if ($content -match "JWT_SECRET_KEY=.*") {
    $content = $content -replace "JWT_SECRET_KEY=.*", "JWT_SECRET_KEY=$jwtSecretKey"
    Write-Host "  ✅ JWT_SECRET_KEY atualizado" -ForegroundColor Green
} else {
    Write-Host "  ⚠️  JWT_SECRET_KEY não encontrado" -ForegroundColor Yellow
}

# ENCRYPTION_KEY
if ($content -match "ENCRYPTION_KEY=.*") {
    $content = $content -replace "ENCRYPTION_KEY=.*", "ENCRYPTION_KEY=$encryptionKey"
    Write-Host "  ✅ ENCRYPTION_KEY atualizado" -ForegroundColor Green
} else {
    Write-Host "  ⚠️  ENCRYPTION_KEY não encontrado" -ForegroundColor Yellow
}

# NEXT_PUBLIC_API_URL - Mudar para LOCAL
if ($content -match "NEXT_PUBLIC_API_URL=.*") {
    # DEVOPS: preferir path relativo (funciona com proxy Nginx do sky-poc-infra)
    $content = $content -replace "NEXT_PUBLIC_API_URL=.*", "NEXT_PUBLIC_API_URL=/api/v1"
    Write-Host "  ✅ NEXT_PUBLIC_API_URL atualizado para LOCAL" -ForegroundColor Green
} else {
    Write-Host "  ⚠️  NEXT_PUBLIC_API_URL não encontrado" -ForegroundColor Yellow
}

# CORS_ORIGINS - Mudar para LOCAL
if ($content -match "CORS_ORIGINS=.*") {
    $content = $content -replace "CORS_ORIGINS=.*", "CORS_ORIGINS=http://localhost:3000,http://localhost"
    Write-Host "  ✅ CORS_ORIGINS atualizado para LOCAL" -ForegroundColor Green
} else {
    Write-Host "  ⚠️  CORS_ORIGINS não encontrado" -ForegroundColor Yellow
}

# Salvar arquivo
try {
    # Criar backup
    $backupPath = "$envPath.backup.$(Get-Date -Format 'yyyyMMdd_HHmmss')"
    Copy-Item $envPath $backupPath -Force
    Write-Host ""
    Write-Host "Backup criado: $(Split-Path $backupPath -Leaf)" -ForegroundColor Green
    
    # Salvar novo conteúdo
    $content | Set-Content $envPath -Encoding UTF8 -NoNewline
    Write-Host "Arquivo .env atualizado com sucesso!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Proximos passos:" -ForegroundColor Cyan
    Write-Host "   1. Verifique o arquivo .env" -ForegroundColor White
    Write-Host "   2. Execute: docker compose up -d --build" -ForegroundColor White
} catch {
    $errorMsg = $_.Exception.Message
    Write-Host "ERRO: Erro ao salvar arquivo: $errorMsg" -ForegroundColor Red
    exit 1
}

