variable "environment" {
  description = "Environment name (e.g. dev, staging, prod)"
  type        = string
  default     = "staging"
}

variable "location" {
  description = "Azure Region"
  type        = string
  default     = "eastus2"
}

variable "vnet_address_space" {
  description = "Address space for the VNet"
  type        = list(string)
  default     = ["10.1.0.0/16"]
}

variable "resource_group_name" {
  description = "Name of the Resource Group for AKS resources"
  type        = string
  default     = "sky-aks-rg"
}

variable "subscription_id" {
  description = "Azure Subscription ID"
  type        = string
  default     = ""
}

variable "admin_username" {
  description = "Admin username for Bastion and Nodes"
  type        = string
  default     = "azureuser"
}

variable "ssh_public_key" {
  description = "SSH Public Key content or path (optional - set to null to skip Bastion creation)"
  type        = string
  default     = null
  nullable    = true
}

variable "aks_cluster_name" {
  description = "Name of the AKS Cluster"
  type        = string
  default     = "sky-aks-cluster"
}

variable "dns_prefix" {
  description = "DNS prefix for AKS"
  type        = string
  default     = "sky-aks"
}

variable "kubernetes_version" {
  description = "Kubernetes version (leave empty for latest stable)"
  type        = string
  default     = ""
}

variable "allowed_ssh_ips" {
  description = "List of IPs allowed to SSH into Bastion"
  type        = list(string)
  default     = ["0.0.0.0/0"] # WARNING: Change this for production!
}

variable "service_cidr" {
  description = "CIDR for Kubernetes Services (must not overlap with VNet)"
  type        = string
  default     = "10.0.0.0/16"
}

variable "runner_ip" {
  description = "Public IP of the GitHub Actions runner (for Key Vault access)"
  type        = string
  default     = null
}

variable "key_vault_firewall_allow" {
  description = "Temporarily allow all access to Key Vault (managed by pipeline during apply)"
  type        = bool
  default     = false
}

variable "authorized_ips" {
  description = "List of public IPs authorized to access the AKS API server"
  type        = list(string)
  default     = []
}

variable "tailscale_auth_key" {
  description = "Tailscale Auth Key for automatic machine registration"
  type        = string
  sensitive   = true
  default     = ""
}

variable "github_actions_sp_object_id" {
  description = "Object ID do Service Principal do GitHub Actions para acesso ao Key Vault via RBAC"
  type        = string
  default     = null
  nullable    = true
}

# =============================================================================
# Geo-Disaster Recovery (DO2025-1044)
# =============================================================================
# Todas as variáveis abaixo são usadas EXCLUSIVAMENTE pelo dr.tf.
# Não têm efeito nenhum quando enable_geo_dr = false (padrão).
# =============================================================================

variable "enable_geo_dr" {
  description = <<-EOT
    Ativa a infraestrutura de Geo-Disaster Recovery.
    false (padrão): staging e prod não são afetados. Custo: $0.
    true:           provisiona todos os recursos de DR na região secundária.
                    Usar apenas em ambientes de clientes VIP.
  EOT
  type    = bool
  default = false
}

variable "dr_location" {
  description = "Região Azure secundária para o DR (deve ser par da região primária)"
  type        = string
  default     = "centralus"
}

variable "dr_resource_group_name" {
  description = "Nome do Resource Group de DR. Se vazio, usa '{resource_group_name}-dr'"
  type        = string
  default     = ""
}

variable "dr_vnet_address_space" {
  description = "CIDR do VNet secundário. Não deve sobrepor com vnet_address_space da região primária"
  type        = string
  default     = "10.3.0.0/16"
}

variable "dr_postgres_sku" {
  description = "SKU do PostgreSQL Flexible Server (primary + replica)"
  type        = string
  default     = "GP_Standard_D2s_v3" # 2 vCPUs, 8GB RAM — ajustar conforme carga do cliente
}

variable "dr_redis_capacity" {
  description = "Capacidade do Redis Premium (1=6GB, 2=13GB, 3=26GB)"
  type        = number
  default     = 1
}

variable "dr_primary_origin_hostname" {
  description = "Hostname do ingress primário (eastus2) para o Azure Front Door. Ex: workspace-api.skyfirstlabs.com"
  type        = string
  default     = ""
}

variable "dr_secondary_origin_hostname" {
  description = "Hostname do ingress secundário (centralus) para o Azure Front Door. Ex: workspace-dr-api.skyfirstlabs.com"
  type        = string
  default     = ""
}
