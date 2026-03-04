variable "external_dns_identity_resource_group" {
  description = "Resource Group where the ExternalDNS User Assigned Identity resides"
  type        = string
}

variable "external_dns_identity_name" {
  description = "Name of the ExternalDNS User Assigned Identity"
  type        = string
  default     = "id-dns-manager"
}

# Fetch the existing Identity created by Core module
data "azurerm_user_assigned_identity" "dns" {
  name                = var.external_dns_identity_name
  resource_group_name = var.external_dns_identity_resource_group
}

# Create Federated Credential for the AKS Cluster to use this Identity
# This allows the ExternalDNS pod (ServiceAccount) to assume the Identity
resource "azurerm_federated_identity_credential" "external_dns" {
  name                = "fed-external-dns-${var.environment}-${terraform.workspace}"
  resource_group_name = var.external_dns_identity_resource_group
  parent_id           = data.azurerm_user_assigned_identity.dns.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = azurerm_kubernetes_cluster.aks.oidc_issuer_url
  subject             = "system:serviceaccount:external-dns:external-dns"
}

output "external_dns_client_id" {
  value = data.azurerm_user_assigned_identity.dns.client_id
}
