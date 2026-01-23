terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }
  required_version = ">= 1.2.0"

  # Backend configuration for Azure Storage (passed via command line/CI)
  backend "azurerm" {}
}

provider "azurerm" {
  features {}
}
