data "azurerm_client_config" "current" {}

resource "random_id" "kv_suffix" {
  byte_length = 4
}

# tfsec:ignore:azure-keyvault-specify-network-acl
# trivy:ignore:AVD-AZU-0013
resource "azurerm_key_vault" "main" {
  name                        = "akv-sky-${var.environment}-${random_id.kv_suffix.hex}"
  location                    = azurerm_resource_group.aks.location
  resource_group_name         = azurerm_resource_group.aks.name
  enabled_for_disk_encryption = true
  tenant_id                   = data.azurerm_client_config.current.tenant_id
  soft_delete_retention_days  = 7
  purge_protection_enabled    = true

  sku_name = "standard"

  # Access Policies are managed via RBAC
  rbac_authorization_enabled = true

  network_acls {
    # trivy:ignore:AVD-AZU-0013 (KeyVault ACLs managed via Runner temporarily)
    # tfsec:ignore:azure-keyvault-specify-network-acl
    # Restricted access: AKS Subnet + Runner IP (temporary for secret population)
    default_action             = "Deny"
    bypass                     = "AzureServices" # Required when enabled_for_disk_encryption is true
    virtual_network_subnet_ids = [azurerm_subnet.aks.id]
    ip_rules                   = var.runner_ip != null && var.runner_ip != "" ? [var.runner_ip] : []
  }

  tags = {
    Environment = var.environment
    Project     = "Sky-POC"
    ManagedBy   = "Terraform"
    Owner       = "DevOps-Team"
  }
}

# --- Private Link Hardening ---

resource "azurerm_private_endpoint" "kv_pe" {
  name                = "pe-akv-${var.environment}"
  location            = azurerm_resource_group.aks.location
  resource_group_name = azurerm_resource_group.aks.name
  subnet_id           = azurerm_subnet.aks.id

  private_service_connection {
    name                           = "psc-akv-${var.environment}"
    private_connection_resource_id = azurerm_key_vault.main.id
    is_manual_connection           = false
    subresource_names              = ["vault"]
  }

  private_dns_zone_group {
    name                 = "pdzg-akv-${var.environment}"
    private_dns_zone_ids = [azurerm_private_dns_zone.kv_dns.id]
  }
}

resource "azurerm_private_dns_zone" "kv_dns" {
  name                = "privatelink.vaultcore.azure.net"
  resource_group_name = azurerm_resource_group.aks.name
}

resource "azurerm_private_dns_zone_virtual_network_link" "kv_dns_link" {
  name                  = "pdzvl-akv-${var.environment}"
  resource_group_name   = azurerm_resource_group.aks.name
  private_dns_zone_name = azurerm_private_dns_zone.kv_dns.name
  virtual_network_id    = azurerm_virtual_network.aks.id
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

# NOTE: Secrets are NOT created via Terraform due to firewall limitations
# Instead, they are populated via Azure CLI in the GitHub Actions workflow
# See: .github/workflows/deploy.yml (populate-key-vault-secrets step)
# This approach works because Azure CLI is recognized as a trusted service

# Outputs are now in outputs.tf


# 5. Diagnostic Settings for Audit Logs
# Sends Key Vault logs to the storage account mentioned in the DevOps Questionnaire
resource "azurerm_monitor_diagnostic_setting" "kv_logs" {
  name               = "diag-akv-${var.environment}"
  target_resource_id = azurerm_key_vault.main.id
  storage_account_id = azurerm_storage_account.db_backup.id

  enabled_log {
    category = "AuditEvent"
  }

  metric {
    category = "AllMetrics"
    enabled  = false
  }
}
