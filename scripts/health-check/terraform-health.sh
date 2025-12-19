#!/bin/bash

set -euo pipefail

ENVIRONMENT="${1:-dev}"
WORKING_DIR="${2:-infra/azure}"
TIMEOUT="${3:-300}"

cd "${WORKING_DIR}" || exit 1

if [ ! -d ".terraform" ]; then
    echo "Terraform not initialized"
    exit 1
fi

CURRENT_WORKSPACE=$(terraform workspace show)
if [ "${CURRENT_WORKSPACE}" != "${ENVIRONMENT}" ]; then
    echo "Warning: Current workspace (${CURRENT_WORKSPACE}) doesn't match environment (${ENVIRONMENT})"
fi

terraform state list > /dev/null 2>&1 || {
    echo "Failed to list Terraform state"
    exit 1
}

terraform plan -detailed-exitcode -refresh=true > /dev/null 2>&1
DRIFT_CODE=$?

if [ $DRIFT_CODE -eq 2 ]; then
    echo "State drift detected! Infrastructure differs from state file"
    exit 1
elif [ $DRIFT_CODE -eq 1 ]; then
    echo "Error checking state drift"
    exit 1
fi

VM_IP=$(terraform output -raw vm_public_ip 2>/dev/null || echo "")

if [ -n "${VM_IP}" ]; then
    START_TIME=$(date +%s)
    while [ $(($(date +%s) - START_TIME)) -lt ${TIMEOUT} ]; do
        if ping -c 1 -W 2 "${VM_IP}" > /dev/null 2>&1; then
            break
        fi
        sleep 5
    done
    
    if ! ping -c 1 -W 2 "${VM_IP}" > /dev/null 2>&1; then
        echo "VM is not reachable after ${TIMEOUT}s"
        exit 1
    fi
fi
