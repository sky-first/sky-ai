variable "region" {
  description = "AWS region for the foundation. eu-west-1 (Ireland) is our home region."
  type        = string
  default     = "eu-west-1"
}

variable "management_account_id" {
  description = "Account ID of the AWS Organizations management account (lucasventura)."
  type        = string
  default     = "755400488974"
}

variable "state_bucket_name" {
  description = "Name of the S3 bucket holding Terraform state for all sky-* modules."
  type        = string
  default     = "sky-tf-state-eu-west-1"
}

variable "state_lock_table_name" {
  description = "Name of the DynamoDB table used for Terraform state locking."
  type        = string
  default     = "sky-tf-locks"
}

# Member account IDs that need cross-account access to their state prefixes.
# Each account gets read/write access only to its own prefixes (least privilege).
variable "staging_account_id" {
  description = "Account ID of sky-staging."
  type        = string
  default     = "741375879811"
}

variable "production_account_id" {
  description = "Account ID of sky-production."
  type        = string
  default     = "032080729567"
}
