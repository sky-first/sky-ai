resource "azurerm_container_registry" "acr" {
  name                = "skyacr${var.environment}${random_string.storage_suffix.result}" # Must be globally unique, strictly alphanumeric
  resource_group_name = azurerm_resource_group.aks.name
  location            = azurerm_resource_group.aks.location
  sku                 = "Standard"
  admin_enabled       = false

  tags = {
    Environment = var.environment
  }
}

# Grant AKS access to pull images from ACR
resource "azurerm_role_assignment" "aks_acr_pull" {
  scope                = azurerm_container_registry.acr.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_kubernetes_cluster.aks.kubelet_identity[0].object_id
}
