data "azurerm_client_config" "current" {}

resource "random_id" "kv_suffix" {
  byte_length = 4
}

resource "azurerm_key_vault" "main" {
  name                        = "akv-sky-${var.environment}-${random_id.kv_suffix.hex}"
  location                    = azurerm_resource_group.aks.location
  resource_group_name         = azurerm_resource_group.aks.name
  enabled_for_disk_encryption = true
  tenant_id                   = data.azurerm_client_config.current.tenant_id
  soft_delete_retention_days  = 7
  purge_protection_enabled    = true # Azure não permite desabilitar após habilitado (imutável)

  sku_name = "standard"

  # Access Policies are managed via RBAC
  # access_policy {}

  # RBAC Authorization is recommended over Access Policies
  enable_rbac_authorization = true

  network_acls {
    # Hybrid Security Model decision (2026-04-07):
    # - STAGING (this KV): Allow + RBAC. Zero Trust by identity, no network ACL.
    #   Justification: small distributed team, POC stage, no regulated data.
    #   The operational cost of maintaining IP allowlists for every dev laptop
    #   and CI runner outweighs the marginal security benefit at this scale.
    #   Hardening required to make this safe: MFA + Conditional Access + PIM
    #   for elevated roles + audit logs to SIEM.
    # - PRODUCTION (future KV): Deny + RBAC. Defense in depth for real customer
    #   data, compliance posture for audits.
    # See: docs/decisions/2026-04-07-keyvault-network-policy.md (TODO)
    # Original Zero Trust note from PR #374: identity is the security boundary,
    # network firewall is disabled to eliminate runner_ip workaround.
    # tfsec:ignore:azure-keyvault-specify-network-acl Allow-by-default is intentional under the hybrid security model documented above. Staging KV uses RBAC as the single boundary; production KV will use Deny+allowlist when it exists.
    default_action             = "Allow"
    bypass                     = "AzureServices"
    virtual_network_subnet_ids = []
    ip_rules                   = []
  }

  # Allow Terraform to manage network rules
  # No ignore_changes needed since we're not using dynamic IP rules

  tags = {
    Environment = var.environment
    Project     = "Sky-POC"
    ManagedBy   = "Terraform"
    Owner       = "DevOps-Team"
  }
}

# 1. Grant Access to the Current User (Terraform Runner) via RBAC
resource "azurerm_role_assignment" "vault_admin" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Administrator"
  principal_id         = data.azurerm_client_config.current.object_id
}

# 2. Managed Identity for External Secrets Operator (User Assigned Identity)
resource "azurerm_user_assigned_identity" "eso" {
  name                = "id-eso-${var.environment}"
  resource_group_name = azurerm_resource_group.aks.name
  location            = azurerm_resource_group.aks.location
}

# Grant Identity access to Key Vault via RBAC
resource "azurerm_role_assignment" "eso_secrets_user" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.eso.principal_id
}

# 3. Grant Access to GitHub Actions Service Principal (for CI/CD)
resource "azurerm_role_assignment" "github_actions_secrets_user" {
  count                            = var.github_actions_sp_object_id != null ? 1 : 0
  name                             = uuidv5("dns", "${azurerm_key_vault.main.id}-${var.github_actions_sp_object_id}-secrets-user")
  scope                            = azurerm_key_vault.main.id
  role_definition_name             = "Key Vault Secrets User"
  principal_id                     = var.github_actions_sp_object_id
  skip_service_principal_aad_check = true
}



# 4. Federated Credential (Trust Relationship)
resource "azurerm_federated_identity_credential" "eso" {
  name                = "fed-eso-${var.environment}"
  resource_group_name = azurerm_resource_group.aks.name
  parent_id           = azurerm_user_assigned_identity.eso.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = azurerm_kubernetes_cluster.aks.oidc_issuer_url
  subject             = "system:serviceaccount:external-secrets:external-secrets"
}

# 5. Propagation Delay (Best Practice to avoid 403 on first try)
# Azure RBAC propagation typically takes 30-90 seconds
resource "time_sleep" "wait_for_rbac_and_firewall" {
  depends_on = [
    azurerm_key_vault.main,
    azurerm_role_assignment.vault_admin,
    azurerm_role_assignment.eso_secrets_user,
    azurerm_role_assignment.github_actions_secrets_user
  ]

  # Extended wait time to ensure both RBAC and firewall rules are propagated
  create_duration = "90s"
}





# --- Infrastructure Secrets Generation ---
# Generate passwords and secrets (Terraform manages generation, Azure CLI manages Key Vault population)

resource "random_password" "postgres" {
  length  = 16
  special = false
}

resource "random_password" "redis" {
  length  = 24
  special = false
}

resource "random_password" "jwt_secret" {
  length  = 64
  special = false
}

resource "random_password" "encryption_key" {
  length  = 32
  special = false
}

# Secrets can now be created via any authenticated Entra ID principal:
# - Locally via: az keyvault secret set --vault-name <name> ...
# - GitHub Actions via Service Principal (OIDC)
# - Terraform (azurerm_key_vault_secret) — no longer blocked by firewall

# Outputs are now in outputs.tf

