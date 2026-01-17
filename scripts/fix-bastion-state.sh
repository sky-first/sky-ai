#!/bin/bash
set -euo pipefail

# Configuration
SUBSCRIPTION_ID="${AZURE_SUBSCRIPTION_ID:-}"
RESOURCE_GROUP="${TF_VAR_resource_group_name:-sky-aks-staging-rg}"
BASTION_VM_NAME="bastion-vm-staging"
BASTION_TF_ADDR="azurerm_linux_virtual_machine.bastion[0]"

if [ -z "$SUBSCRIPTION_ID" ]; then
  echo "Error: AZURE_SUBSCRIPTION_ID is not set."
  exit 1
fi

echo "Checking if Bastion VM '$BASTION_VM_NAME' exists in Azure..."
if az vm show --resource-group "$RESOURCE_GROUP" --name "$BASTION_VM_NAME" &>/dev/null; then
  echo "✅ VM exists in Azure."
  
  echo "Checking if VM is already in Terraform state..."
  if terraform state show "$BASTION_TF_ADDR" &>/dev/null; then
    echo "✅ VM is already in state. No action needed."
  else
    echo "⚠️ VM is missing from state. Importing..."
    VM_ID="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Compute/virtualMachines/$BASTION_VM_NAME"
    
    terraform import "$BASTION_TF_ADDR" "$VM_ID"
    echo "✅ Import complete."
  fi
else
  echo "ℹ️  VM does not exist in Azure. Terraform will create it."
fi
