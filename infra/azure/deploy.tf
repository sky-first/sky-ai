# Deploy da aplicação via Azure Run Command
# Este recurso executa o deploy da aplicação na VM após a criação/atualização da infraestrutura

resource "null_resource" "deploy_application" {
  count = var.enable_app_deploy ? 1 : 0

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
      $rg = "${azurerm_resource_group.main.name}"
      $vm = "${azurerm_linux_virtual_machine.main.name}"
      Write-Host "Iniciando deploy da aplicação..."

      # Mesma estratégia do setup: use o python do Azure CLI para evitar parsing do az.cmd no Windows.
      $azCmd = (Get-Command az).Source
      $azPy = Join-Path (Split-Path $azCmd) "..\\python.exe"
      if (!(Test-Path $azPy)) { throw "ERRO: python.exe do Azure CLI não encontrado em: $azPy" }

      # CRÍTICO: passe o script como ARRAY para --scripts; no Windows, multiline único pode executar só a 1ª linha.
      $scripts = @(
        'set -eu',
        'BRANCH=${var.git_branch}',
        'INFRA_REPO=${var.github_repo != "" ? var.github_repo : "sky-first/sky-poc-infra"}',
        'OWNER=${split("/", var.github_repo != "" ? var.github_repo : "sky-first/sky-poc-infra")[0]}',
        'PROJ_DIR=/home/${var.admin_username}/projeto',
        'sudo mkdir -p $PROJ_DIR',
        'sudo chown -R ${var.admin_username}:${var.admin_username} $PROJ_DIR || true',
        'cd $PROJ_DIR',
        'clone_or_update() { name=$1; url=$2; if [ -d $name/.git ]; then cd $name; git fetch origin; git checkout -B $BRANCH origin/$BRANCH || true; git pull origin $BRANCH || true; cd $PROJ_DIR; else git clone -b $BRANCH $url $name; fi; }',
        'echo Atualizando_repos branch=$BRANCH',
        'clone_or_update sky-poc-infra https://github.com/$INFRA_REPO.git',
        'clone_or_update sky-poc-backend https://github.com/$OWNER/sky-poc-backend.git',
        'clone_or_update sky-poc-frontend https://github.com/$OWNER/sky-poc-frontend.git',
        'clone_or_update sky-poc-ai https://github.com/$OWNER/sky-poc-ai.git',
        'echo Subindo_containers',
        'cd $PROJ_DIR/sky-poc-infra',
        'if [ ! -f .env ]; then echo ERRO_env_nao_encontrado_crie_o_env_antes_do_deploy; exit 1; fi',
        'echo Validando_env_e_configuracoes_criticas',
        # Garante que NEXT_PUBLIC_API_URL não fique em localhost:8000 (causa comum do erro no login)
        # e completa variáveis ausentes (senhas/keys) de forma segura.
        'sudo bash scripts/azure/ensure-complete-env.sh "$PROJ_DIR/sky-poc-infra"',
        # Garante que nginx.conf esteja em modo HTTP-only se não houver certificados
        'sudo bash scripts/azure/apply-nginx-config.sh "$PROJ_DIR/sky-poc-infra"',
        'sudo docker compose down || true',
        'sudo docker compose up -d --build',
        'echo Prewarm_frontend_routes',
        'sudo bash scripts/azure/prewarm-frontend.sh http://127.0.0.1 || true',
        'sudo docker compose ps || true',
        'sudo docker ps || true'
      )

      $out = & $azPy -m azure.cli vm run-command invoke -g $rg -n $vm --command-id RunShellScript --scripts $scripts -o json --only-show-errors
      $msg = (ConvertFrom-Json $out).value[0].message
      if ($msg -match '\\[stderr\\]\\s*\\S') { throw "ERRO: deploy na VM retornou stderr. Mensagem: $msg" }
      Write-Host "Deploy executado. Resultado:"
      Write-Output $out
    EOT

    interpreter = ["powershell", "-NoProfile", "-Command"]
  }
}
