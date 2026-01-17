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
