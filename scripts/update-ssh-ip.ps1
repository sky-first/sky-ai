# scripts/update-ssh-ip.ps1
# Atualiza automaticamente o IP SSH no terraform.tfvars.prod
# Útil quando seu IP público muda

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
$TfvarsFile = Join-Path $ProjectDir "infra\azure\terraform.tfvars.prod"

Write-Host "╔════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║     Atualizar IP SSH no Terraform                 ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# Descobrir IP atual
Write-Host "Descobrindo seu IP público..." -ForegroundColor Blue

$ip = $null
$services = @(
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://icanhazip.com"
)

foreach ($service in $services) {
    try {
        $response = Invoke-WebRequest -Uri $service -UseBasicParsing -TimeoutSec 5
        $ip = $response.Content.Trim()
        
        if ($ip -match '^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$') {
            Write-Host "✅ IP encontrado: $ip" -ForegroundColor Green
            break
        }
    } catch {
        continue
    }
}

if (-not $ip) {
    Write-Host "❌ Erro: Não foi possível descobrir o IP público" -ForegroundColor Red
    exit 1
}

Write-Host ""

# Verificar IP atual no arquivo
$content = Get-Content $TfvarsFile -Raw
$currentIpMatch = [regex]::Match($content, '"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})/32"')

if ($currentIpMatch.Success) {
    $currentIp = $currentIpMatch.Groups[1].Value
    if ($currentIp -eq $ip) {
        Write-Host "✅ IP já está atualizado: $ip/32" -ForegroundColor Green
        exit 0
    }
    Write-Host "IP atual no arquivo: $currentIp/32" -ForegroundColor Yellow
    Write-Host "Novo IP: $ip/32" -ForegroundColor Yellow
    Write-Host ""
    $confirm = Read-Host "Deseja atualizar? (yes/no)"
    if ($confirm -ne "yes") {
        Write-Host "Atualização cancelada" -ForegroundColor Yellow
        exit 0
    }
}

# Backup do arquivo
$backupFile = "$TfvarsFile.backup.$(Get-Date -Format 'yyyyMMdd_HHmmss')"
Copy-Item $TfvarsFile $backupFile
Write-Host "Backup criado: $backupFile" -ForegroundColor Blue

# Atualizar IP no arquivo
$newContent = $content -replace '"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})/32"', "`"$ip/32`""
Set-Content -Path $TfvarsFile -Value $newContent -NoNewline

Write-Host "✅ IP atualizado para: $ip/32" -ForegroundColor Green
Write-Host ""
Write-Host "Próximos passos:" -ForegroundColor Cyan
Write-Host "  1. Revisar mudanças: git diff $TfvarsFile" -ForegroundColor Yellow
Write-Host "  2. Aplicar Terraform: cd infra\azure && terraform apply -var-file=terraform.tfvars.prod" -ForegroundColor Yellow
Write-Host ""

