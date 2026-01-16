resource "azurerm_kubernetes_cluster" "aks" {
  name                = var.aks_cluster_name
  location            = azurerm_resource_group.aks.location
  resource_group_name = azurerm_resource_group.aks.name
  dns_prefix          = var.dns_prefix
  kubernetes_version  = var.kubernetes_version != "" ? var.kubernetes_version : null

  default_node_pool {
    name                        = "system"
    node_count                  = 2
    vm_size                     = "Standard_D2s_v3"
    temporary_name_for_rotation = "tempnodepool"

    # System nodes are not for general application workloads, but we allow management tools
    only_critical_addons_enabled = false

    vnet_subnet_id = azurerm_subnet.aks.id
  }

  identity {
    type = "SystemAssigned"
  }

  role_based_access_control_enabled = true

  network_profile {
    network_plugin    = "azure"
    network_policy    = "azure"
    load_balancer_sku = "standard"
    service_cidr      = var.service_cidr
    dns_service_ip    = cidrhost(var.service_cidr, 10)
    # azure-cni needs careful IP planning, or use 'overlay' mode (preview in some regions, standard in newer provider versions)
    # Using basic azure CNI here. Subnet is large enough (/22 = 1022 IPs).
  }

  # Private Cluster: API Server internal accessible only within VNet
  # For this specific setup user asked for "API Server privado".
  # BUT enabling private_cluster_enabled requires DNS setup or Bastion access to resolve API server.
  # Since we have Bastion, this is viable.
  private_cluster_enabled = true

  # Workload Identity (Required for External Secrets / Key Vault)
  workload_identity_enabled = true
  oidc_issuer_enabled       = true

  tags = {
    Environment = var.environment
  }
}

# User Node Pool - Standard Instances
resource "azurerm_kubernetes_cluster_node_pool" "user_pool" {
  name                  = "userapps"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.aks.id
  vm_size               = "Standard_D2s_v3"
  enable_auto_scaling   = true
  min_count             = 1
  max_count             = 3
  priority              = "Regular"

  node_labels = {
    "workload_type" = "application"
  }

  vnet_subnet_id = azurerm_subnet.aks.id

  tags = {
    Environment = var.environment
  }
}

# Grant AKS Identity access to VNet (Network Contributor) 
# Required for Azure CNI to manage IPs
# resource "azurerm_role_assignment" "aks_network" {
#   scope                = azurerm_resource_group.aks.id
#   role_definition_name = "Network Contributor"
#   principal_id         = azurerm_kubernetes_cluster.aks.identity[0].principal_id
# }
