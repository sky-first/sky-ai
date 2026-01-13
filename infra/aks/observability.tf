resource "random_string" "storage_suffix" {
  length  = 6
  special = false
  upper   = false
}

resource "azurerm_storage_account" "loki" {
  name                     = "skyloki${var.environment}${random_string.storage_suffix.result}"
  resource_group_name      = azurerm_resource_group.aks.name
  location                 = azurerm_resource_group.aks.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"
  access_tier              = "Cool" # Cheaper for logs

  tags = {
    Environment = var.environment
  }
}

resource "azurerm_storage_container" "loki_chunks" {
  name                  = "loki-chunks"
  storage_account_name  = azurerm_storage_account.loki.name
  container_access_type = "private"
}

resource "azurerm_storage_container" "loki_ruler" {
  name                  = "loki-ruler"
  storage_account_name  = azurerm_storage_account.loki.name
  container_access_type = "private"
}

# Output the keys so we can use them in the k8s secret (manually or via sealing)
output "loki_storage_account_name" {
  value = azurerm_storage_account.loki.name
}

output "loki_storage_account_key" {
  value     = azurerm_storage_account.loki.primary_access_key
  sensitive = true
}
