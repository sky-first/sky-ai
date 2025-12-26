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
      echo "Configurando VM (Docker, Docker Compose, Git)..."
      
      # Aguardar VM estar pronta com retry loop
      MAX_RETRIES=10
      RETRY_COUNT=0
      VM_STATE="unknown"
      
      while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
        VM_STATE=$(az vm show \
          --resource-group ${azurerm_resource_group.main.name} \
          --name ${azurerm_linux_virtual_machine.main.name} \
          --query "powerState" -o tsv 2>/dev/null || echo "unknown")
        
        if [ "$VM_STATE" == "VM running" ]; then
          echo "OK: VM está rodando"
          break
        fi
        
        RETRY_COUNT=$((RETRY_COUNT + 1))
        echo "Aguardando VM estar pronta... ($RETRY_COUNT/$MAX_RETRIES)"
        sleep 10
      done
      
      if [ "$VM_STATE" != "VM running" ]; then
        echo "ERRO: VM não está rodando após $MAX_RETRIES tentativas"
        exit 1
      fi
      
      # Executa setup via Azure Run Command
      az vm run-command invoke \
        --resource-group ${azurerm_resource_group.main.name} \
        --name ${azurerm_linux_virtual_machine.main.name} \
        --command-id RunShellScript \
        --scripts "
          set -euo pipefail
          
          echo 'Atualizando lista de pacotes...'
          sudo apt update -y
          
          echo 'Instalando dependências...'
          sudo apt install -y ca-certificates curl gnupg lsb-release git
          
          echo 'Instalando Docker...'
          if ! command -v docker &> /dev/null; then
            curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
            sudo sh /tmp/get-docker.sh
            rm /tmp/get-docker.sh
            echo 'Docker instalado'
          else
            echo 'Docker já está instalado'
          fi
          
          echo 'Configurando permissões Docker...'
          sudo usermod -aG docker ${var.admin_username}
          
          echo 'Instalando Docker Compose...'
          if ! docker compose version &> /dev/null; then
            sudo apt install -y docker-compose-plugin
            echo 'Docker Compose instalado'
          else
            echo 'Docker Compose já está instalado'
          fi
          
          echo 'Verificando instalações...'
          docker --version || { echo 'ERRO: Docker não disponível'; exit 1; }
          docker compose version || { echo 'ERRO: Docker Compose não disponível'; exit 1; }
          git --version || { echo 'ERRO: Git não disponível'; exit 1; }
          
          echo 'Setup concluído!'
        " \
        --output json > /tmp/setup-output.json 2>&1 || {
          echo "Erro no setup da VM"
          cat /tmp/setup-output.json
          exit 1
        }
      
      echo "Setup da VM executado com sucesso"
      cat /tmp/setup-output.json | jq -r '.value[0].message' || cat /tmp/setup-output.json
    EOT

    interpreter = ["bash", "-c"]
  }
}
