# Backend remoto do Terraform
# Este arquivo documenta a estrutura esperada do backend remoto
# O backend será configurado dinamicamente no CI/CD via -backend-config=backend.hcl

terraform {
  # Backend explicitamente definido para evitar warning do Terraform quando
  # usamos -backend-config=backend.hcl no CI/CD.
  # As configurações (RG/Storage/Container/Key) são fornecidas via backend.hcl.
  backend "azurerm" {}

  # Backend será configurado dinamicamente no CI/CD através do arquivo backend.hcl
  # que é gerado automaticamente pelo workflow do GitHub Actions
  #
  # Para uso local, você pode descomentar e configurar:
  # backend "azurerm" {
  #   resource_group_name  = "tfstate-rg"
  #   storage_account_name = "tfstatestorage"
  #   container_name       = "tfstate"
  #   key                  = "poc-deploy-${terraform.workspace}.tfstate"
  #   use_azuread_auth     = true
  # }
  #
  # Ou usar o backend.hcl gerado pelo CI/CD:
  # terraform init -backend-config=backend.hcl
}


