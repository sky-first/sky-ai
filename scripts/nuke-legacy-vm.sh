#!/bin/bash
set -euo pipefail

# Legacy Resource Cleanup Script
# CAUTION: This script aggressively deletes resources matching legacy patterns.
# Run this to ensure your environment is clean for a pure Kubernetes setup.

# Legacy Resource Patterns
LEGACY_VM_NAMES=("skyfirstlabs-staging" "poc-sky" "skyfirstlabs-prod")
# If legacy resources are in a specific legacy RG, define it here (or leave empty to search globally/current RG)
# Assuming legacy might be in the SAME RG or a specific 'poc-sky' RG based on history.
TARGET_RGS=("sky-aks-staging-rg" "poc-sky") # Add other RGs if known

echo "🔥 STARTING LEGACY REMEDIATION - Kubernetes Purification Protocol"
echo "----------------------------------------------------------------"

for RG in "${TARGET_RGS[@]}"; do
    echo "🔍 Scanning Resource Group: $RG"
    
    # Check if RG exists first
    if ! az group show --name "$RG" >/dev/null 2>&1; then
        echo "   ℹ️  Resource Group '$RG' not found. Skipping."
        continue
    fi

    for VM_NAME in "${LEGACY_VM_NAMES[@]}"; do
        echo "   🎯 Checking for Legacy VM: $VM_NAME"
        
        # Check if VM exists
        VM_ID=$(az vm show --resource-group "$RG" --name "$VM_NAME" --query id -o tsv 2>/dev/null || echo "")
        
        if [ -n "$VM_ID" ]; then
            echo "      ⚠️  LEGACY VM FOUND: $VM_ID"
            echo "      💣 Destroying Legacy VM..."
            az vm delete --resource-group "$RG" --name "$VM_NAME" --yes
            echo "      ✅ VM destroyed successfully."
            
            # Clean up associated resources (Disks, NICs)
            # Note: 'az vm delete' with flags can do this, but being explicit ensures cleanup
            
            echo "      🧹 Cleaning up OS Disk..."
            DISK_ID=$(az disk list --resource-group "$RG" --query "[?contains(name, '${VM_NAME}')].id" -o tsv)
            if [ -n "$DISK_ID" ]; then
                az disk delete --ids $DISK_ID --yes --no-wait
                echo "      ✅ Deletion triggered for Disks."
            fi
            
            echo "      🧹 Cleaning up Network Interfaces..."
            NIC_ID=$(az network nic list --resource-group "$RG" --query "[?contains(name, '${VM_NAME}')].id" -o tsv)
            if [ -n "$NIC_ID" ]; then
                az network nic delete --ids $NIC_ID --yes --no-wait
                echo "      ✅ Deletion triggered for NICs."
            fi
            
            echo "      🧹 Cleaning up Public IPs..."
            PIP_ID=$(az network public-ip list --resource-group "$RG" --query "[?contains(name, '${VM_NAME}')].id" -o tsv)
            if [ -n "$PIP_ID" ]; then
                az network public-ip delete --ids $PIP_ID --yes --no-wait
                echo "      ✅ Deletion triggered for PIPs."
            fi

        else
            echo "      ✅ No active legacy VM found with name '$VM_NAME'."
        fi
    done
done

echo "----------------------------------------------------------------"
echo "✨ CLEANUP CHECK COMPLETE."
echo "If resources were found, they are being deleted in the background."
echo "Your environment is now optimized for Kubernetes (AKS) workloads."
