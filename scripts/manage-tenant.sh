#!/bin/bash
set -e

# Usage: ./manage-tenant.sh <action> <client-id>
# Actions: plan, apply, destroy
# Client ID: corresponds to filename in infra/aks/environments/<client-id>.tfvars

ACTION=$1
CLIENT_ID=$2
INFRA_DIR="./infra/aks"
ENV_FILE="environments/$CLIENT_ID.tfvars"

if [ -z "$ACTION" ] || [ -z "$CLIENT_ID" ]; then
  echo "Usage: $0 <plan|apply|destroy> <client-id>"
  echo "Example: $0 apply client-vip"
  exit 1
fi

cd "$INFRA_DIR"

if [ ! -f "$ENV_FILE" ]; then
  echo "Error: Configuration file $ENV_FILE not found!"
  exit 1
fi

echo "========================================"
echo " MANAGING TENANT: $CLIENT_ID"
echo " ACTION: $ACTION"
echo "========================================"

# Select or Create Workspace
# This isolates the Terraform State for this client
if terraform workspace select "$CLIENT_ID" > /dev/null 2>&1; then
  echo "Selected workspace: $CLIENT_ID"
else
  echo "Workspace $CLIENT_ID does not exist. Creating..."
  terraform workspace new "$CLIENT_ID"
fi

# Auto-detect SSH Key
SSH_KEY_PATH="../../keys/azure/id_rsa.pub"
if [ ! -f "$SSH_KEY_PATH" ]; then
  SSH_KEY_PATH="$HOME/.ssh/id_rsa.pub"
fi

if [ -f "$SSH_KEY_PATH" ]; then
  echo "SSH Key found: $SSH_KEY_PATH"
  SSH_VAR="-var=ssh_public_key=$(cat $SSH_KEY_PATH)"
else
  echo "WARNING: SSH Key not found automatically. Terraform will ask for input."
  SSH_VAR=""
fi

if [ "$ACTION" == "plan" ]; then
  terraform plan -var-file="$ENV_FILE" $SSH_VAR -out "$CLIENT_ID.tfplan"
elif [ "$ACTION" == "apply" ]; then
  terraform apply -var-file="$ENV_FILE" $SSH_VAR
elif [ "$ACTION" == "destroy" ]; then
  echo "WARNING: DESTROYING ARCHITECTURE FOR $CLIENT_ID"
  terraform destroy -var-file="$ENV_FILE"
else
  echo "Unknown action: $ACTION"
  exit 1
fi
