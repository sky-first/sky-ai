variable "location" {
  description = "Azure Region for Core Infrastructure"
  type        = string
  default     = "eastus2"
}

variable "resource_group_name" {
  description = "Name of the Core Infrastructure Resource Group"
  type        = string
  default     = "rg-core-infra-prd"
}

variable "dns_zone_name" {
  description = "Root domain for the SaaS platform"
  type        = string
  default     = "skyfirstlabs.com"
}
