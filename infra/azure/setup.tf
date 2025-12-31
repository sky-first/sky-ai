# Setup inicial da VM - Instala Docker, Docker Compose e Git
# Este recurso executa automaticamente após a criação da VM

resource "null_resource" "setup_vm" {
  depends_on = [
    azurerm_linux_virtual_machine.main,
    azurerm_network_interface.main
  ]

  triggers = {
    vm_id = azurerm_linux_virtual_machine.main.id
  }

  provisioner "local-exec" {
    command = <<-EOT
      $rg = "${azurerm_resource_group.main.name}"
      $vm = "${azurerm_linux_virtual_machine.main.name}"

      Write-Host "Configurando VM (Docker, Docker Compose, Git)..."

      $vmState = ""
      for ($i = 1; $i -le 20; $i++) {
        $vmState = (az vm show -g $rg -n $vm -d --query powerState -o tsv 2>$null)
        if ($vmState -eq "VM running") {
          Write-Host "OK: VM está rodando"
          break
        }
        Write-Host "Aguardando VM estar pronta... ($i/20) state=[$vmState]"
        Start-Sleep -Seconds 10
      }

      if ($vmState -ne "VM running") {
        throw "ERRO: VM não está rodando. state=[$vmState]"
      }

      # CRÍTICO (Windows): passe o script como ARRAY para --scripts.
      # Se passar como um único texto multiline, o agente pode executar só a 1ª linha.
      $scripts = @(
        'set -eu',
        'echo Atualizando_lista_de_pacotes',
        'sudo apt update -y',
        'echo Instalando_dependencias',
        'sudo apt install -y ca-certificates curl gnupg lsb-release git',
        'echo Instalando_Docker',
        'if ! command -v docker >/dev/null 2>&1; then curl -fsSL https://get.docker.com -o /tmp/get-docker.sh; sudo sh /tmp/get-docker.sh; rm /tmp/get-docker.sh; fi',
        'echo Instalando_Docker_Compose',
        'if ! docker compose version >/dev/null 2>&1; then sudo apt install -y docker-compose-plugin; fi',
        'echo Configurando_grupo_docker',
        'sudo usermod -aG docker ${var.admin_username} || true',
        'echo Versoes',
        'docker --version || true',
        'docker compose version || true',
        'git --version || true'
      )

      # CRÍTICO (Windows): evite executar Azure CLI via az.cmd (cmd.exe quebra facilmente com caracteres especiais).
      # Use o python do Azure CLI diretamente: python.exe -m azure.cli ...
      $azCmd = (Get-Command az).Source
      $azPy = Join-Path (Split-Path $azCmd) "..\\python.exe"
      if (!(Test-Path $azPy)) { throw "ERRO: python.exe do Azure CLI não encontrado em: $azPy" }

      $out = & $azPy -m azure.cli vm run-command invoke -g $rg -n $vm --command-id RunShellScript --scripts $scripts -o json --only-show-errors
      Write-Host "Setup da VM executado. Resultado:"
      Write-Output $out
    EOT

    interpreter = ["powershell", "-NoProfile", "-Command"]
  }
}
