terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
  }
}

provider "aws" {
  region = var.region

  # CRITICAL: assert we're applying against the management account.
  # If a developer accidentally configures the wrong AWS profile, this fails fast.
  allowed_account_ids = [var.management_account_id]

  default_tags {
    tags = {
      Project     = "Sky"
      Environment = "shared"
      ManagedBy   = "terraform"
      Module      = "foundation"
      Repo        = "sky-infra"
    }
  }
}
