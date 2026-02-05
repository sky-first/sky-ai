# 1. Random suffix for globally unique storage account names
resource "random_string" "backup_suffix" {
  length  = 6
  special = false
  upper   = false
}

# 2. Storage Account for Off-site Backups
# Features: GRS (Regional Redundancy), Encryption, HSTS
resource "azurerm_storage_account" "db_backup" {
  name                     = "skybkp${var.environment}${random_string.backup_suffix.result}"
  resource_group_name      = var.resource_group_name
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = "GRS" # Geo-Redundant for Production resilience
  min_tls_version          = "TLS1_2"

  # Immutability & Protection
  blob_properties {
    versioning_enabled       = true
    change_feed_enabled      = true
    last_access_time_enabled = true

    container_delete_retention_policy {
      days = 7
    }
    delete_retention_policy {
      days = 7
    }
  }

  tags = {
    Environment = var.environment
    Component   = "Backup-Platform"
    Criticality = "Tier-1"
  }
}

# 3. Dedicated Container for SQL Backups
# Immutable WORM (Write Once, Read Many) will be enabled via policy
resource "azurerm_storage_container" "sql_backups" {
  name                  = "sql-backups"
  storage_account_name  = azurerm_storage_account.db_backup.name
  container_access_type = "private"
}

# 4. Lifecycle Management Policy
# Auto-tiering to Cool and Archive to optimize costs
resource "azurerm_storage_management_policy" "backup_lifecycle" {
  storage_account_id = azurerm_storage_account.db_backup.id

  rule {
    name    = "ArchiveOldBackups"
    enabled = true
    filters {
      prefix_match = ["sql-backups/"]
      blob_types   = ["blockBlob"]
    }
    actions {
      base_blob {
        tier_to_cool_after_days_since_modification_greater_than    = 30
        tier_to_archive_after_days_since_modification_greater_than = 60
        delete_after_days_since_modification_greater_than          = 90
      }
      snapshot {
        delete_after_days_since_creation_greater_than = 30
      }
    }
  }
}

# 5. Workload Identity for Backup Jobs
# Creates the identity that the K8s Pod will assume
resource "azurerm_user_assigned_identity" "db_backup" {
  name                = "id-sky-db-backup-${var.environment}"
  resource_group_name = var.resource_group_name
  location            = var.location
}

# 6. RBAC: Assign permissions to the Storage Account
resource "azurerm_role_assignment" "db_backup_storage" {
  scope                = azurerm_storage_account.db_backup.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.db_backup.principal_id
}

# 7. Federated Identity: Link AKS OIDC with Managed Identity
# This is what enables the "Zero Password" authentication
resource "azurerm_federated_identity_credential" "db_backup" {
  name                = "fed-sky-db-backup-${var.environment}"
  resource_group_name = var.resource_group_name
  audience            = ["api://AzureADTokenExchange"]
  # Use the production issuer URL discovered via CLI
  issuer    = var.environment == "prod" ? "https://eastus2.oic.prod-aks.azure.com/a1b3ce06-b7ba-4d99-8a26-3347ab865f36/a0bef504-bd1f-4c4f-91f7-4e40cc6782fd/" : "https://eastus2.oic.prod-aks.azure.com/a1b3ce06-b7ba-4d99-8a26-3347ab865f36/04bef504-bd1f-4c4f-91f7-4e40cc6782fd/"
  parent_id = azurerm_user_assigned_identity.db_backup.id

  # Links to the ServiceAccount in K8s
  subject = "system:serviceaccount:${var.environment}:sky-db-backup"
}

# Outputs for use in Kubernetes manifests
output "backup_storage_account_name" {
  value = azurerm_storage_account.db_backup.name
}

output "backup_storage_container_name" {
  value = azurerm_storage_container.sql_backups.name
}

output "backup_identity_client_id" {
  value = azurerm_user_assigned_identity.db_backup.client_id
}
