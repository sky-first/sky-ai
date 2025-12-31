# Health Check pós-deploy
# Verifica se todos os serviços estão funcionando corretamente após o deploy

resource "null_resource" "health_check" {
  count = var.enable_app_deploy ? 1 : 0

  depends_on = [null_resource.deploy_application]

  triggers = {
    deploy_id = try(null_resource.deploy_application[0].id, "")
  }

  provisioner "local-exec" {
    command = <<-EOT
      $rg = "${azurerm_resource_group.main.name}"
      $vm = "${azurerm_linux_virtual_machine.main.name}"
      Write-Host "Executando health check..."
      Start-Sleep -Seconds 30

      $azCmd = (Get-Command az).Source
      $azPy = Join-Path (Split-Path $azCmd) "..\\python.exe"
      if (!(Test-Path $azPy)) { throw "ERRO: python.exe do Azure CLI não encontrado em: $azPy" }

      $scripts = @(
        'set -eu',
        'echo Verificando_containers_Docker',
        'PG_CONT=$(sudo docker ps --format \"{{.Names}}\" | grep -Ei postgres | head -n 1 || true)',
        'REDIS_CONT=$(sudo docker ps --format \"{{.Names}}\" | grep -Ei redis | head -n 1 || true)',
        'if [ -z \"$PG_CONT\" ]; then echo ERRO_Postgres_nao_rodando; sudo docker ps -a || true; exit 1; fi',
        'if [ -z \"$REDIS_CONT\" ]; then echo ERRO_Redis_nao_rodando; sudo docker ps -a || true; exit 1; fi',
        'echo Containers_ok PG=$PG_CONT REDIS=$REDIS_CONT',
        'echo Verificando_Postgres',
        'i=1; while [ $i -le 30 ]; do if sudo docker exec \"$PG_CONT\" pg_isready -U postgres >/dev/null 2>&1; then echo Postgres_ok; break; fi; if [ $i -eq 30 ]; then echo ERRO_Postgres_timeout; exit 1; fi; i=$((i+1)); sleep 2; done',
        'echo Verificando_Redis',
        'OUT=$(sudo docker exec \"$REDIS_CONT\" redis-cli ping 2>/dev/null || true); echo redis_ping=$OUT; echo $OUT | grep -Eq \"PONG|NOAUTH\" || { echo ERRO_Redis; exit 1; }',
        'echo Health_check_ok'
      )

      $out = & $azPy -m azure.cli vm run-command invoke -g $rg -n $vm --command-id RunShellScript --scripts $scripts -o json --only-show-errors
      $msg = (ConvertFrom-Json $out).value[0].message
      if ($msg -match '\\[stderr\\]\\s*\\S') { throw "ERRO: health-check na VM retornou stderr. Mensagem: $msg" }
      Write-Host "Health check executado. Resultado:"
      Write-Output $out
    EOT

    interpreter = ["powershell", "-NoProfile", "-Command"]
  }
}
