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

variable "backup_retention_days" {
  description = "Retention period for backups in days per environment"
  type        = map(number)
  default = {
    dev     = 7
    staging = 30
    prod    = 365
  }
}
variable "oidc_issuer_url" {
  description = "The OIDC Issuer URL for the AKS cluster (used for workload identity)"
  type        = string
  default     = "" # If empty, it will fallback to the dynamic cluster output in resources
}
