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
          set -euo pipefail
          
          echo 'Configurando ambiente...'
          
          # Criar estrutura de diretórios se não existir
          mkdir -p ~/projeto || { echo 'ERRO: Erro ao criar diretório'; exit 1; }
          cd ~/projeto || { echo 'ERRO: Erro ao entrar no diretório'; exit 1; }
          
          # Detectar estrutura existente (poc-deploy ou sky-poc-infra)
          if [ -d poc-deploy ]; then
            INFRA_DIR="poc-deploy"
            echo 'Estrutura poc-deploy encontrada (legado)'
          elif [ -d sky-poc-infra ]; then
            INFRA_DIR="sky-poc-infra"
            echo 'Estrutura sky-poc-infra encontrada'
          else
            INFRA_DIR="poc-deploy"
            echo 'Criando estrutura poc-deploy'
          fi
          
          # Clonar ou atualizar repositório de infraestrutura
          if [ -d "$INFRA_DIR" ]; then
            echo "Atualizando repositório $INFRA_DIR..."
            cd "$INFRA_DIR"
            git fetch origin || { echo "ERRO: Erro ao fazer fetch do repositório $INFRA_DIR"; exit 1; }
            
            # Validar que a branch existe antes de fazer checkout
            if git ls-remote --heads origin ${var.git_branch} | grep -q ${var.git_branch}; then
              echo "OK: Branch ${var.git_branch} encontrada no repositório remoto"
              git checkout ${var.git_branch} || { echo "ERRO: Erro ao fazer checkout da branch ${var.git_branch}"; exit 1; }
              git pull origin ${var.git_branch} || { echo "ERRO: Erro ao fazer pull da branch ${var.git_branch}"; exit 1; }
            else
              echo "ERRO: Branch ${var.git_branch} não encontrada no repositório remoto"
              echo "Branches disponíveis:"
              git ls-remote --heads origin | sed 's/.*refs\/heads\///' || true
              exit 1
            fi
          else
            echo "Clonando repositório $INFRA_DIR..."
            # Validar que a branch existe antes de clonar
            REPO_URL="https://github.com/${var.github_repo != "" ? var.github_repo : "sky-first/sky-poc-infra"}.git"
            if git ls-remote --heads "$REPO_URL" ${var.git_branch} | grep -q ${var.git_branch}; then
              echo "OK: Branch ${var.git_branch} encontrada, clonando..."
              git clone -b ${var.git_branch} "$REPO_URL" "$INFRA_DIR" || { echo "ERRO: Erro ao clonar repositório com branch ${var.git_branch}"; exit 1; }
            else
              echo "ERRO: Branch ${var.git_branch} não encontrada no repositório $REPO_URL"
              echo "Branches disponíveis:"
              git ls-remote --heads "$REPO_URL" | sed 's/.*refs\/heads\///' || true
              exit 1
            fi
            
            if [ -d "$INFRA_DIR" ]; then
              cd "$INFRA_DIR"
              git checkout ${var.git_branch} || { echo "ERRO: Erro ao fazer checkout da branch ${var.git_branch}"; exit 1; }
            fi
          fi
          
          # Detectar nomes dos repositórios (pode ser backend ou sky-poc-backend)
          cd ~/projeto
          
          # Backend - tentar ambos os nomes
          if [ ! -d backend ] && [ ! -d sky-poc-backend ]; then
            echo 'Clonando repositório backend...'
            BACKEND_REPO=$(echo ${var.github_repo} | sed 's/sky-poc-infra/sky-poc-backend/')
            if [ -z "$BACKEND_REPO" ] || [ "$BACKEND_REPO" = "${var.github_repo}" ]; then
              BACKEND_REPO="sky-first/sky-poc-backend"
            fi
            
            # Validar branch antes de clonar
            BACKEND_REPO_URL="https://github.com/${BACKEND_REPO}.git"
            if git ls-remote --heads "$BACKEND_REPO_URL" ${var.git_branch} 2>/dev/null | grep -q ${var.git_branch}; then
              echo "OK: Branch ${var.git_branch} encontrada no backend, clonando..."
              git clone -b ${var.git_branch} "$BACKEND_REPO_URL" backend || \
              git clone -b ${var.git_branch} "$BACKEND_REPO_URL" sky-poc-backend || \
              { echo "ERRO: Falha ao clonar repositório backend com branch ${var.git_branch}"; exit 1; }
            else
              echo "ERRO: Branch ${var.git_branch} não encontrada no repositório backend"
              echo "URL: $BACKEND_REPO_URL"
              echo "Branches disponíveis:"
              git ls-remote --heads "$BACKEND_REPO_URL" 2>/dev/null | sed 's/.*refs\/heads\///' || true
              exit 1
            fi
          fi
          
          # Frontend - tentar ambos os nomes
          if [ ! -d frontend ] && [ ! -d sky-poc-frontend ]; then
            echo 'Clonando repositório frontend...'
            FRONTEND_REPO=$(echo ${var.github_repo} | sed 's/sky-poc-infra/sky-poc-frontend/')
            if [ -z "$FRONTEND_REPO" ] || [ "$FRONTEND_REPO" = "${var.github_repo}" ]; then
              FRONTEND_REPO="sky-first/sky-poc-frontend"
            fi
            
            # Validar branch antes de clonar
            FRONTEND_REPO_URL="https://github.com/${FRONTEND_REPO}.git"
            if git ls-remote --heads "$FRONTEND_REPO_URL" ${var.git_branch} 2>/dev/null | grep -q ${var.git_branch}; then
              echo "OK: Branch ${var.git_branch} encontrada no frontend, clonando..."
              git clone -b ${var.git_branch} "$FRONTEND_REPO_URL" frontend || \
              git clone -b ${var.git_branch} "$FRONTEND_REPO_URL" sky-poc-frontend || \
              { echo "ERRO: Falha ao clonar repositório frontend com branch ${var.git_branch}"; exit 1; }
            else
              echo "ERRO: Branch ${var.git_branch} não encontrada no repositório frontend"
              echo "URL: $FRONTEND_REPO_URL"
              echo "Branches disponíveis:"
              git ls-remote --heads "$FRONTEND_REPO_URL" 2>/dev/null | sed 's/.*refs\/heads\///' || true
              exit 1
            fi
          fi
          
          # IA - tentar ambos os nomes
          if [ ! -d ia ] && [ ! -d sky-poc-ai ]; then
            echo 'Clonando repositório IA...'
            IA_REPO=$(echo ${var.github_repo} | sed 's/sky-poc-infra/sky-poc-ai/')
            if [ -z "$IA_REPO" ] || [ "$IA_REPO" = "${var.github_repo}" ]; then
              IA_REPO="sky-first/sky-poc-ai"
            fi
            
            # Validar branch antes de clonar
            IA_REPO_URL="https://github.com/${IA_REPO}.git"
            if git ls-remote --heads "$IA_REPO_URL" ${var.git_branch} 2>/dev/null | grep -q ${var.git_branch}; then
              echo "OK: Branch ${var.git_branch} encontrada no IA, clonando..."
              git clone -b ${var.git_branch} "$IA_REPO_URL" ia || \
              git clone -b ${var.git_branch} "$IA_REPO_URL" sky-poc-ai || \
              { echo "ERRO: Falha ao clonar repositório IA com branch ${var.git_branch}"; exit 1; }
            else
              echo "ERRO: Branch ${var.git_branch} não encontrada no repositório IA"
              echo "URL: $IA_REPO_URL"
              echo "Branches disponíveis:"
              git ls-remote --heads "$IA_REPO_URL" 2>/dev/null | sed 's/.*refs\/heads\///' || true
              exit 1
            fi
          fi
          
          echo 'Fazendo deploy com Docker Compose...'
          
          # Navegar para o diretório do projeto (suporta ambos os nomes)
          cd ~/projeto
          if [ -d poc-deploy ]; then
            cd poc-deploy
          elif [ -d sky-poc-infra ]; then
            cd sky-poc-infra
          else
            echo "ERRO: Diretório de infraestrutura não encontrado"
            exit 1
          fi
          
          # Validar que docker-compose.yml existe
          if [ ! -f docker-compose.yml ]; then
            echo "ERRO: docker-compose.yml não encontrado"
            exit 1
          fi
          
          # Usar sudo para Docker (grupo docker será aplicado no próximo login)
          # Parar containers existentes (pode não existir, então não falhar)
          sudo docker compose down || echo "Nenhum container rodando para parar"
          
          # Build e start dos containers (crítico - deve falhar se não funcionar)
          sudo docker compose up -d --build || { 
            echo "ERRO: Falha ao iniciar containers"
            echo "Logs dos containers:"
            sudo docker compose logs --tail=50
            exit 1
          }
          
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
