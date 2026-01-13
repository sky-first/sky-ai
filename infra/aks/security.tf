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

  # RBAC Authorization is recommended over Access Policies for Workload Identity
  enable_rbac_authorization = true

  network_acls {
    default_action = "Deny"
    bypass         = "AzureServices"
  }

  tags = {
    Environment = var.environment
  }
}

# Grant "Key Vault Secrets Officer" to the Current User (Terraform Runner)
# This allows Terraform to create the secrets below.
resource "azurerm_role_assignment" "current_user_kv_officer" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

# --- Workload Identity for External Secrets Operator ---

# 1. User Assigned Identity for ESO
resource "azurerm_user_assigned_identity" "eso" {
  name                = "id-eso-${var.environment}"
  resource_group_name = azurerm_resource_group.aks.name
  location            = azurerm_resource_group.aks.location
}

# 2. Federated Credential (Trust Relationship)
resource "azurerm_federated_identity_credential" "eso" {
  name                = "fed-eso-${var.environment}"
  resource_group_name = azurerm_resource_group.aks.name
  parent_id           = azurerm_user_assigned_identity.eso.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = azurerm_kubernetes_cluster.aks.oidc_issuer_url
  subject             = "system:serviceaccount:external-secrets:external-secrets"
}

# 3. Grant Access to Key Vault (Key Vault Secrets User) - Read Only for ESO
resource "azurerm_role_assignment" "eso_kv_access" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.eso.principal_id
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
  depends_on   = [azurerm_role_assignment.current_user_kv_officer]
}

resource "azurerm_key_vault_secret" "redis_password" {
  name         = "redis-password"
  value        = random_password.redis.result
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [azurerm_role_assignment.current_user_kv_officer]
}

resource "azurerm_key_vault_secret" "database_url" {
  name         = "database-url"
  value        = "postgresql://postgres:${random_password.postgres.result}@postgres:5432/ai_saas_db"
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [azurerm_role_assignment.current_user_kv_officer]
}

resource "azurerm_key_vault_secret" "redis_url" {
  name         = "redis-url"
  value        = "redis://:${random_password.redis.result}@redis:6379/0"
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [azurerm_role_assignment.current_user_kv_officer]
}

resource "random_password" "jwt_secret" {
  length = 64
}

resource "azurerm_key_vault_secret" "jwt_secret_key" {
  name         = "jwt-secret-key"
  value        = random_password.jwt_secret.result
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [azurerm_role_assignment.current_user_kv_officer]
}

resource "random_password" "encryption_key" {
  length = 32
}

resource "azurerm_key_vault_secret" "encryption_key" {
  name         = "encryption-key"
  value        = random_password.encryption_key.result
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [azurerm_role_assignment.current_user_kv_officer]
}

resource "azurerm_key_vault_secret" "openai_api_key" {
  name         = "openai-api-key"
  value        = "sk-placeholder-replace-me" # Placeholder for OpenAI
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [azurerm_role_assignment.current_user_kv_officer]
}

resource "azurerm_key_vault_secret" "qdrant_url" {
  name         = "qdrant-url"
  value        = "http://qdrant:6333" # Internal Qdrant if used, or external
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [azurerm_role_assignment.current_user_kv_officer]
}

# Outputs are now in outputs.tf

