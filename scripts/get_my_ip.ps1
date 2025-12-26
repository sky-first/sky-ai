# scripts/get_my_ip.ps1
# Script PowerShell para descobrir o IP público atual
# Útil para configurar allowed_ssh_ips no terraform.tfvars.prod
#
# SE DER ERRO DE POLÍTICA DE EXECUÇÃO:
# Execute: powershell -ExecutionPolicy Bypass -File .\scripts\get_my_ip.ps1
# Ou use o comando direto: (Invoke-WebRequest -Uri "https://api.ipify.org" -UseBasicParsing).Content

Write-Host "Descobrindo seu IP público..." -ForegroundColor Cyan
Write-Host ""

# Tentar múltiplos serviços caso um falhe
$ip = $null
$services = @(
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://icanhazip.com"
)

foreach ($service in $services) {
    try {
        Write-Host "Tentando: $service..." -ForegroundColor Gray
        $response = Invoke-WebRequest -Uri $service -UseBasicParsing -TimeoutSec 5
        $ip = $response.Content.Trim()
        
        # Validar se é um IP válido
        if ($ip -match '^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$') {
            Write-Host "✅ IP encontrado via $service" -ForegroundColor Green
            break
        }
    } catch {
        Write-Host "  Falhou, tentando próximo..." -ForegroundColor Yellow
        continue
    }
}

if ($ip) {
    Write-Host ""
    Write-Host "✅ Seu IP público é: $ip" -ForegroundColor Green
    Write-Host ""
    Write-Host "Adicione este IP ao arquivo infra/azure/terraform.tfvars.prod:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  allowed_ssh_ips = [`"$ip/32`"]" -ForegroundColor Green
    Write-Host ""
    Write-Host "Ou para múltiplos IPs:" -ForegroundColor Yellow
    Write-Host "  allowed_ssh_ips = [`"$ip/32`", `"OUTRO_IP/32`"]" -ForegroundColor White
    Write-Host ""
    Write-Host "Copie o IP acima e cole no arquivo terraform.tfvars.prod" -ForegroundColor Cyan
} else {
    Write-Host ""
    Write-Host "❌ Erro: Não foi possível descobrir o IP público" -ForegroundColor Red
    Write-Host ""
    Write-Host "Tente manualmente:" -ForegroundColor Yellow
    Write-Host "  (Invoke-WebRequest -Uri https://api.ipify.org -UseBasicParsing).Content" -ForegroundColor White
    Write-Host ""
    Write-Host "Ou use um navegador:" -ForegroundColor Yellow
    Write-Host "  https://api.ipify.org" -ForegroundColor White
    Write-Host ""
    exit 1
}
