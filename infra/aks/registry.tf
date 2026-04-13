resource "azurerm_container_registry" "acr" {
  name                = "skyacr${var.environment}${random_string.storage_suffix.result}" # Must be globally unique, strictly alphanumeric
  resource_group_name = azurerm_resource_group.aks.name
  location            = azurerm_resource_group.aks.location
  # Premium SKU is required for geo-replication (enable_geo_dr = true).
  # Upgrading Standard → Premium is non-destructive; downgrading back requires
  # removing geo-replicas first. Cost delta is ~$150/month per geo-replica.
  sku           = var.enable_geo_dr ? "Premium" : "Standard"
  admin_enabled = false

  lifecycle {
    # Prevent accidental destruction — ACR holds all customer images.
    prevent_destroy = true
  }

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
