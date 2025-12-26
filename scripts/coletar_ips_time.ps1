# scripts/coletar_ips_time.ps1
# Script para coletar IPs de todos os membros do time
# Cada membro executa e envia o resultado

Write-Host "=== Coletor de IPs do Time ===" -ForegroundColor Cyan
Write-Host ""

# Descobrir IP
try {
    $ip = (Invoke-WebRequest -Uri "https://api.ipify.org" -UseBasicParsing).Content.Trim()
    
    if ($ip -match '^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$') {
        $username = $env:USERNAME
        $date = Get-Date -Format "yyyyMMdd"
        $outputFile = "meu_ip_${username}_${date}.txt"
        
        $content = @"
=== IP Público para SSH ===
Nome: $username
Data: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
IP: $ip/32

Adicione ao terraform.tfvars.prod:
  "$ip/32",  # $username

"@
        
        $content | Out-File -FilePath $outputFile -Encoding UTF8
        
        Write-Host "✅ Arquivo criado: $outputFile" -ForegroundColor Green
        Write-Host ""
        Write-Host "Conteúdo:" -ForegroundColor Yellow
        Get-Content $outputFile
        Write-Host ""
        Write-Host "📧 Compartilhe este arquivo com o time DevOps" -ForegroundColor Cyan
        Write-Host "   (via Slack, email, ou repositório privado)" -ForegroundColor Gray
    } else {
        Write-Host "❌ Erro ao descobrir IP válido" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "❌ Erro: $_" -ForegroundColor Red
    exit 1
}

