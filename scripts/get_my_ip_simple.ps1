# Versão simplificada - pode ser copiada e colada diretamente no PowerShell
# Não requer política de execução

(Invoke-WebRequest -Uri "https://api.ipify.org" -UseBasicParsing).Content

