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
      #!/bin/bash
      set -euo pipefail
      
      RG="${azurerm_resource_group.main.name}"
      VM="${azurerm_linux_virtual_machine.main.name}"
      ADMIN_USER="${var.admin_username}"
      
      echo "Configurando VM (Docker, Docker Compose, Git)..."
      
      # Aguardar VM estar pronta
      VM_STATE=""
      for i in {1..20}; do
        VM_STATE=$(az vm show -g "$RG" -n "$VM" -d --query powerState -o tsv 2>/dev/null || echo "")
        if [ "$VM_STATE" = "VM running" ]; then
          echo "OK: VM está rodando"
          break
        fi
        echo "Aguardando VM estar pronta... ($i/20) state=[$VM_STATE]"
        sleep 10
      done
      
      if [ "$VM_STATE" != "VM running" ]; then
        echo "ERRO: VM não está rodando. state=[$VM_STATE]"
        exit 1
      fi
      
      # Scripts para executar na VM (passar como múltiplos argumentos --scripts)
      echo "Executando setup na VM..."
      OUT=$(az vm run-command invoke \
        -g "$RG" \
        -n "$VM" \
        --command-id RunShellScript \
        --scripts \
          'set -eu' \
          'echo Atualizando_lista_de_pacotes' \
          'sudo apt update -y' \
          'echo Instalando_dependencias' \
          'sudo apt install -y ca-certificates curl gnupg lsb-release git' \
          'echo Instalando_Docker' \
          'if ! command -v docker >/dev/null 2>&1; then curl -fsSL https://get.docker.com -o /tmp/get-docker.sh; sudo sh /tmp/get-docker.sh; rm /tmp/get-docker.sh; fi' \
          'echo Instalando_Docker_Compose' \
          'if ! docker compose version >/dev/null 2>&1; then sudo apt install -y docker-compose-plugin; fi' \
          'echo Configurando_grupo_docker' \
          "sudo usermod -aG docker $ADMIN_USER || true" \
          'echo Versoes' \
          'docker --version || true' \
          'docker compose version || true' \
          'git --version || true' \
        -o json \
        --only-show-errors 2>&1)
      
      echo "Setup da VM executado. Resultado:"
      echo "$OUT"
    EOT

    interpreter = ["/bin/bash", "-c"]
  }
}
