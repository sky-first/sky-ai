variable "github_org" {
  description = "GitHub Organization"
  type        = string
  default     = "sky-first"
}

variable "github_repos" {
  description = "List of repositories to allow OIDC access"
  type        = list(string)
  default     = ["sky-poc-infra", "sky-poc-backend", "sky-poc-frontend", "sky-poc-ai"]
}

# User Assigned Identity for GitHub Actions
resource "azurerm_user_assigned_identity" "gh_actions" {
  name                = "id-gh-actions-${var.environment}"
  resource_group_name = azurerm_resource_group.aks.name
  location            = azurerm_resource_group.aks.location

  tags = {
    Environment = var.environment
  }
}

# Grant AcrPush to the GitHub Actions Identity
# NOTE: The GitHub Actions Service Principal REQUIRES "User Access Administrator" or "Owner" 
# at the scope level to manage these role assignments via Terraform.
# DISABLED TEMPORARILY due to insufficient permissions of the runner.
# resource "azurerm_role_assignment" "gh_actions_acr_push" {
#   scope                = azurerm_container_registry.acr.id
#   role_definition_name = "AcrPush"
#   principal_id         = azurerm_user_assigned_identity.gh_actions.principal_id
# }

# Grant AcrPull (for verification/signing if needed)
# resource "azurerm_role_assignment" "gh_actions_acr_pull" {
#   scope                = azurerm_container_registry.acr.id
#   role_definition_name = "AcrPull"
#   principal_id         = azurerm_user_assigned_identity.gh_actions.principal_id
# }

# Establish Trust (Federated Credentials)
# Loop through each repo and allow 'main' branch
resource "azurerm_federated_identity_credential" "gh_actions_main" {
  for_each            = toset(var.github_repos)
  name                = "gh-actions-${each.key}-main"
  resource_group_name = azurerm_resource_group.aks.name
  parent_id           = azurerm_user_assigned_identity.gh_actions.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = "https://token.actions.githubusercontent.com"
  subject             = "repo:${var.github_org}/${each.key}:ref:refs/heads/main"
}

# Also allow Pull Requests? (Optional, usually for PR checks)
resource "azurerm_federated_identity_credential" "gh_actions_pr" {
  for_each            = toset(var.github_repos)
  name                = "gh-actions-${each.key}-pr"
  resource_group_name = azurerm_resource_group.aks.name
  parent_id           = azurerm_user_assigned_identity.gh_actions.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = "https://token.actions.githubusercontent.com"
  subject             = "repo:${var.github_org}/${each.key}:pull_request"
}

# Allow 'staging' branch
resource "azurerm_federated_identity_credential" "gh_actions_staging" {
  for_each            = toset(var.github_repos)
  name                = "gh-actions-${each.key}-staging"
  resource_group_name = azurerm_resource_group.aks.name
  parent_id           = azurerm_user_assigned_identity.gh_actions.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = "https://token.actions.githubusercontent.com"
  subject             = "repo:${var.github_org}/${each.key}:ref:refs/heads/staging"
}

output "gh_actions_client_id" {
  value = azurerm_user_assigned_identity.gh_actions.client_id
}
