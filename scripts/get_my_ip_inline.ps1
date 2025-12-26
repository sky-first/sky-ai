# Comando inline para descobrir IP (copie e cole no PowerShell)
# Não requer mudança de política de execução

(Invoke-WebRequest -Uri "https://api.ipify.org" -UseBasicParsing).Content

