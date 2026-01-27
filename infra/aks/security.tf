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
  purge_protection_enabled    = false

  sku_name = "standard"

  # Access Policies are managed via RBAC
  # access_policy {}

  # RBAC Authorization is recommended over Access Policies
  # DISABLED temporarily because the current user lacks 'Microsoft.Authorization/roleAssignments/write'
  enable_rbac_authorization = false

  network_acls {
    # Restricted access to AKS Subnet and Azure Services only
    default_action             = var.key_vault_firewall_allow ? "Allow" : "Deny"
    bypass                     = "AzureServices"
    virtual_network_subnet_ids = [azurerm_subnet.aks.id]
    ip_rules                   = var.runner_ip != null ? (length(regexall("/[0-9]+$", var.runner_ip)) > 0 ? [var.runner_ip] : ["${var.runner_ip}/32"]) : []
  }

  lifecycle {
    ignore_changes = [
      network_acls[0].ip_rules
    ]
  }

  tags = {
    Environment = var.environment
    Project     = "Sky-POC"
    ManagedBy   = "Terraform"
    Owner       = "DevOps-Team"
  }
}

# 1. Grant Access to the Current User (Terraform Runner)
resource "azurerm_key_vault_access_policy" "current" {
  key_vault_id = azurerm_key_vault.main.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = data.azurerm_client_config.current.object_id

  secret_permissions = [
    "Get", "List", "Set", "Delete", "Purge", "Recover"
  ]
}

# 2. Managed Identity for External Secrets Operator (User Assigned Identity)
resource "azurerm_user_assigned_identity" "eso" {
  name                = "id-eso-${var.environment}"
  resource_group_name = azurerm_resource_group.aks.name
  location            = azurerm_resource_group.aks.location
}

# Grant Identity access to Key Vault via Access Policy
resource "azurerm_key_vault_access_policy" "eso" {
  key_vault_id = azurerm_key_vault.main.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = azurerm_user_assigned_identity.eso.principal_id

  secret_permissions = [
    "Get", "List"
  ]
}

# Grant Access via RBAC (Optional/Future, but keep to avoid recreation if permission exists)
# resource "azurerm_role_assignment" "vault_admin" {
#   scope                = azurerm_key_vault.main.id
#   role_definition_name = "Key Vault Secrets Officer"
#   principal_id         = data.azurerm_client_config.current.object_id
# }

# 3. Federated Credential (Trust Relationship)
resource "azurerm_federated_identity_credential" "eso" {
  name                = "fed-eso-${var.environment}"
  resource_group_name = azurerm_resource_group.aks.name
  parent_id           = azurerm_user_assigned_identity.eso.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = azurerm_kubernetes_cluster.aks.oidc_issuer_url
  subject             = "system:serviceaccount:external-secrets:external-secrets"
}

# 4. Propagation Delay (Best Practice to avoid 403 on first try)
resource "time_sleep" "wait_for_rbac" {
  depends_on = [
    azurerm_key_vault_access_policy.current,
    azurerm_key_vault_access_policy.eso
  ]
  create_duration = "30s"
}



# --- Infrastructure Secrets Injection ---
# Save the generated passwords and connection strings to Key Vault

resource "random_password" "postgres" {
  length  = 16
  special = false
}

resource "random_password" "redis" {
  length  = 24
  special = false
}

resource "azurerm_key_vault_secret" "postgres_password" {
  name         = "postgres-password"
  value        = random_password.postgres.result
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [time_sleep.wait_for_rbac]
}

resource "azurerm_key_vault_secret" "redis_password" {
  name         = "redis-password"
  value        = random_password.redis.result
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [time_sleep.wait_for_rbac]
}

resource "azurerm_key_vault_secret" "database_url" {
  name         = "database-url"
  value        = "postgresql://postgres:${random_password.postgres.result}@postgres:5432/ai_saas_db"
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [time_sleep.wait_for_rbac]
}

resource "azurerm_key_vault_secret" "redis_url" {
  name         = "redis-url"
  value        = "redis://:${random_password.redis.result}@redis:6379/0"
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [time_sleep.wait_for_rbac]
}

resource "random_password" "jwt_secret" {
  length = 64
}

resource "azurerm_key_vault_secret" "jwt_secret_key" {
  name         = "jwt-secret-key"
  value        = random_password.jwt_secret.result
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [time_sleep.wait_for_rbac]
}

resource "random_password" "encryption_key" {
  length = 32
}

resource "azurerm_key_vault_secret" "encryption_key" {
  name         = "encryption-key"
  value        = random_password.encryption_key.result
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [time_sleep.wait_for_rbac]
}

resource "azurerm_key_vault_secret" "openai_api_key" {
  name         = "openai-api-key"
  value        = "sk-placeholder-replace-me" # Placeholder for OpenAI
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [time_sleep.wait_for_rbac]
}

resource "azurerm_key_vault_secret" "qdrant_url" {
  name         = "qdrant-url"
  value        = "http://qdrant:6333" # Internal Qdrant if used, or external
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [time_sleep.wait_for_rbac]
}

# Outputs are now in outputs.tf

