# Resource Group Central
resource "azurerm_resource_group" "core" {
  name     = var.resource_group_name
  location = var.location
  tags = {
    Environment = "core"
    Project     = "SkyFirstLabs-Platform"
    CostCenter  = "CoreInfra"
  }
}

# Zona DNS Pública Central
resource "azurerm_dns_zone" "main" {
  name                = var.dns_zone_name
  resource_group_name = azurerm_resource_group.core.name
  tags = {
    Environment = "core"
  }
}

# Identidade Gerenciada para ExternalDNS (Centralizada)
# O ExternalDNS nos clusters (Staging/Prod/Clients) usará Workload Identity
# para assumir esta identidade e gerenciar registros na zona.
resource "azurerm_user_assigned_identity" "dns_manager" {
  name                = "id-dns-manager"
  resource_group_name = azurerm_resource_group.core.name
  location            = azurerm_resource_group.core.location
}

# Permissão para a identidade gerenciar a Zona DNS
resource "azurerm_role_assignment" "dns_contributor" {
  scope                = azurerm_dns_zone.main.id
  role_definition_name = "DNS Zone Contributor"
  principal_id         = azurerm_user_assigned_identity.dns_manager.principal_id
}

# Output para usar nos outros módulos (AKS)
output "dns_zone_id" {
  value = azurerm_dns_zone.main.id
}

output "dns_manager_id" {
  value = azurerm_user_assigned_identity.dns_manager.id
}

output "dns_manager_client_id" {
  value = azurerm_user_assigned_identity.dns_manager.client_id
}

output "resource_group_name" {
  value = azurerm_resource_group.core.name
}
