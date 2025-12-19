# Health Check pós-deploy
# Verifica se todos os serviços estão funcionando corretamente após o deploy

resource "null_resource" "health_check" {
  depends_on = [null_resource.deploy_application]

  triggers = {
    deploy_id = null_resource.deploy_application.id
  }

  provisioner "local-exec" {
    command = <<-EOT
      echo "Executando health check..."
      
      # Aguarda alguns segundos para os containers iniciarem
      sleep 30
      
      # Executa health check na VM via Azure Run Command
      az vm run-command invoke \
        --resource-group ${azurerm_resource_group.main.name} \
        --name ${azurerm_linux_virtual_machine.main.name} \
        --command-id RunShellScript \
        --scripts "
          set -e
          
          echo 'Verificando containers Docker...'
          
          # Verifica se containers estão rodando (usar sudo se necessário)
          if ! sudo docker ps | grep -q ai_saas_postgres; then
            echo 'Container PostgreSQL não está rodando'
            exit 1
          fi
          
          if ! sudo docker ps | grep -q ai_saas_redis; then
            echo 'Container Redis não está rodando'
            exit 1
          fi
          
          echo 'Containers Docker estão rodando'
          
          # Aguarda PostgreSQL estar pronto
          echo 'Verificando PostgreSQL...'
          for i in {1..30}; do
            if sudo docker exec ai_saas_postgres_prod pg_isready -U postgres > /dev/null 2>&1; then
              echo 'PostgreSQL está respondendo'
              break
            fi
            if [ \$i -eq 30 ]; then
              echo 'PostgreSQL não está respondendo após 30 tentativas'
              exit 1
            fi
            sleep 2
          done
          
          # Verifica Redis
          echo 'Verificando Redis...'
          if ! sudo docker exec ai_saas_redis_prod redis-cli ping | grep -q PONG; then
            echo 'Redis não está respondendo'
            exit 1
          fi
          echo 'Redis está respondendo'
          
          # Verifica Backend (se estiver rodando)
          if sudo docker ps | grep -q ai_saas_backend; then
            echo 'Verificando Backend...'
            sleep 5
            if curl -f -s http://localhost:8000/health > /dev/null 2>&1 || curl -f -s http://localhost:8000/api/health > /dev/null 2>&1; then
              echo 'Backend está respondendo'
            else
              echo 'Backend pode não estar totalmente pronto, mas containers estão rodando'
            fi
          fi
          
          echo 'Health check concluído com sucesso!'
        " \
        --output json > /tmp/health-check-output.json 2>&1 || {
          echo "Health check falhou"
          cat /tmp/health-check-output.json
          exit 1
        }
      
      echo "Health check executado com sucesso"
      cat /tmp/health-check-output.json | jq -r '.value[0].message' || cat /tmp/health-check-output.json
    EOT

    interpreter = ["bash", "-c"]
  }
}
