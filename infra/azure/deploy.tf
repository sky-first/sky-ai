# Deploy da aplicação via Azure Run Command
# Este recurso executa o deploy da aplicação na VM após a criação/atualização da infraestrutura

resource "null_resource" "deploy_application" {
  triggers = {
    vm_id      = azurerm_linux_virtual_machine.main.id
    git_branch = var.git_branch
    timestamp  = timestamp()
  }

  depends_on = [
    azurerm_linux_virtual_machine.main,
    azurerm_network_interface.main,
    null_resource.setup_vm
  ]

  provisioner "local-exec" {
    command = <<-EOT
      echo "Iniciando deploy da aplicação..."
      
      # Executa comandos na VM via Azure Run Command
      az vm run-command invoke \
        --resource-group ${azurerm_resource_group.main.name} \
        --name ${azurerm_linux_virtual_machine.main.name} \
        --command-id RunShellScript \
        --scripts "
          set -e
          
          echo 'Configurando ambiente...'
          
          # Criar estrutura de diretórios se não existir
          mkdir -p ~/projeto
          cd ~/projeto
          
          # Clonar ou atualizar repositório poc-deploy
          if [ -d poc-deploy ]; then
            echo 'Atualizando repositório poc-deploy...'
            cd poc-deploy
            git fetch origin
            git checkout ${var.git_branch}
            git pull origin ${var.git_branch} || true
          else
            echo 'Clonando repositório poc-deploy...'
            git clone -b ${var.git_branch} https://github.com/${var.github_repo != "" ? var.github_repo : "sky-first/sky-poc-infra"}.git poc-deploy
            cd poc-deploy
          fi
          
          # Clonar ou atualizar repositório backend
          if [ ! -d ../backend ]; then
            echo 'Clonando repositório backend...'
            cd ..
            git clone -b ${var.git_branch} https://github.com/${var.github_repo != "" ? replace(var.github_repo, "sky-poc-infra", "backend") : "sky-first/backend"}.git backend || echo 'Backend repo não encontrado, continuando...'
            cd poc-deploy
          fi
          
          # Clonar ou atualizar repositório frontend
          if [ ! -d ../frontend ]; then
            echo 'Clonando repositório frontend...'
            cd ..
            git clone -b ${var.git_branch} https://github.com/${var.github_repo != "" ? replace(var.github_repo, "sky-poc-infra", "frontend") : "sky-first/frontend"}.git frontend || echo 'Frontend repo não encontrado, continuando...'
            cd poc-deploy
          fi
          
          # Clonar ou atualizar repositório IA
          if [ ! -d ../ia ]; then
            echo 'Clonando repositório IA...'
            cd ..
            git clone -b ${var.git_branch} https://github.com/${var.github_repo != "" ? replace(var.github_repo, "sky-poc-infra", "ia") : "sky-first/ia"}.git ia || echo 'IA repo não encontrado, continuando...'
            cd poc-deploy
          fi
          
          echo 'Fazendo deploy com Docker Compose...'
          
          # Navegar para o diretório do projeto
          cd ~/projeto/poc-deploy
          
          # Usar sudo para Docker (grupo docker será aplicado no próximo login)
          # Parar containers existentes (se houver)
          sudo docker compose down || true
          
          # Build e start dos containers
          sudo docker compose up -d --build
          
          echo 'Deploy concluído!'
        " \
        --output json > /tmp/deploy-output.json 2>&1 || {
          echo "Erro no deploy"
          cat /tmp/deploy-output.json
          exit 1
        }
      
      echo "Deploy executado com sucesso"
      cat /tmp/deploy-output.json | jq -r '.value[0].message' || cat /tmp/deploy-output.json
    EOT

    interpreter = ["bash", "-c"]
  }
}
