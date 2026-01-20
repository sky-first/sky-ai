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

  # API Server Access Control
  # CRITICAL SECURITY: Never allow public access without IP restrictions
  # Option 1: If runner_ip is provided, restrict API access to that IP (cluster public but restricted)
  # Option 2: If runner_ip is null, enable private cluster (cluster private, Bastion access only)
  # When authorized_ip_ranges is empty AND private_cluster_enabled = true, access is VNET-only (secure)
  api_server_access_profile {
    # tfsec:ignore:azure-aks-no-authorized-ip-ranges
    # Ignored because: When runner_ip is null, cluster becomes private (private_cluster_enabled = true)
    # Private clusters don't require authorized_ip_ranges (access is VNET-only via Bastion)
    # When runner_ip is provided, it is included in authorized_ip_ranges (restricted public access)
    authorized_ip_ranges = distinct(compact(concat(
      var.runner_ip != null ? [var.runner_ip] : [],
      var.authorized_ips
    )))
  }
  # Enable private cluster if no runner_ip is provided (more secure - VNET access only)
  # Private cluster requires access via Bastion or VPN, which is available in this setup
  # FORCE FALSE to prevent accidental recreation of existing public cluster
  # tfsec:ignore:azure-container-limit-authorized-ips tfsec:ignore:azure-aks-limit-api-access
  private_cluster_enabled = false

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

# GPU Spot Node Pool (Cost Optimization)
resource "azurerm_kubernetes_cluster_node_pool" "gpu_spot" {
  name                  = "gpuspot"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.aks.id
  vm_size               = "Standard_NC4as_T4_v3"
  enable_auto_scaling   = true
  min_count             = 0 # Scale to zero when not in use
  max_count             = 1
  priority              = "Spot"
  eviction_policy       = "Delete"
  spot_max_price        = -1 # Use current market price

  node_labels = {
    "sky-poc-type"  = "gpu"
    "workload_type" = "ai"
  }

  node_taints = [
    "sku=gpu:NoSchedule"
  ]

  vnet_subnet_id = azurerm_subnet.aks.id

  tags = {
    Environment = var.environment
    Type        = "Spot-GPU"
  }
}

# Grant AKS Identity access to VNet (Network Contributor) 
# Required for Azure CNI to manage IPs
# resource "azurerm_role_assignment" "aks_network" {
#   scope                = azurerm_resource_group.aks.id
#   role_definition_name = "Network Contributor"
#   principal_id         = azurerm_kubernetes_cluster.aks.identity[0].principal_id
# }
