terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
  }
}

# Provider runs with sky-staging credentials. The state bucket (in sky-management)
# has a bucket policy that allows sky-staging principals to read/write their own
# prefixes — set in the foundation module.
provider "aws" {
  region              = var.region
  allowed_account_ids = [var.staging_account_id]

  default_tags {
    tags = {
      Project     = "Sky"
      Environment = "staging"
      ManagedBy   = "terraform"
      Module      = "registry"
      Repo        = "sky-infra"
    }
  }
}
