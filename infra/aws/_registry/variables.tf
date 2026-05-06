variable "region" {
  description = "AWS region. eu-west-1 (Ireland) is our home region."
  type        = string
  default     = "eu-west-1"
}

variable "staging_account_id" {
  description = "Account ID of sky-staging (where the registry lives temporarily)."
  type        = string
  default     = "741375879811"
}

variable "production_account_id" {
  description = "Account ID of sky-production (granted cross-account ECR pull)."
  type        = string
  default     = "032080729567"
}

variable "github_org" {
  description = "GitHub organization that hosts our repos."
  type        = string
  default     = "sky-first"
}

variable "image_repos" {
  description = "List of ECR repository names. One IAM role per repo for GitHub Actions push."
  type        = list(string)
  default     = ["sky-frontend", "sky-backend", "sky-ai"]
}

variable "additional_pull_account_ids" {
  description = "Extra AWS account IDs allowed to pull images (e.g., future client accounts). Defaults empty."
  type        = list(string)
  default     = []
}
