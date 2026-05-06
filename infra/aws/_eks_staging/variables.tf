variable "region" {
  type    = string
  default = "eu-west-1"
}

variable "account_id" {
  type    = string
  default = "741375879811" # sky-staging
}

variable "environment" {
  type    = string
  default = "staging"
}

variable "cluster_name" {
  type    = string
  default = "sky-eks-staging"
}

variable "kubernetes_version" {
  type    = string
  default = "1.31"
}

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "azs" {
  type    = list(string)
  default = ["eu-west-1a", "eu-west-1b", "eu-west-1c"]
}

variable "node_instance_type_infra" {
  type    = string
  default = "t3.large" # 2 vCPU, 8GB RAM — for ArgoCD, ESO, monitoring, ingress
}

variable "node_instance_type_apps" {
  type    = string
  default = "t3.large" # 2 vCPU, 8GB RAM — for sky-frontend/backend/ai
}

variable "rds_instance_class" {
  type    = string
  default = "db.t3.small"
}

variable "rds_allocated_storage" {
  type    = number
  default = 20
}

variable "redis_node_type" {
  type    = string
  default = "cache.t3.micro"
}
