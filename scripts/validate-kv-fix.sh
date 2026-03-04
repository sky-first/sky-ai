#!/bin/bash
# Validation Test for Key Vault Firewall Fix (v2 - Azure Services Bypass)
# This script validates the Terraform configuration changes

set -euo pipefail

echo " Validating Terraform Key Vault Firewall Fix (Azure Services Bypass)..."
echo ""

cd "$(dirname "$0")/../infra/aks"

# Test 1: Terraform Format Check
echo "[OK] Test 1: Terraform Format Check"
terraform fmt -check security.tf
echo "   PASSED: security.tf is properly formatted"
echo ""

# Test 2: Terraform Validation
echo "[OK] Test 2: Terraform Validation"
terraform validate
echo "   PASSED: Terraform configuration is valid"
echo ""

# Test 3: Verify network_acls uses 'Deny' by default
echo "[OK] Test 3: Verify network_acls uses 'Deny' by default"
if grep -q 'default_action.*=.*"Deny"' security.tf; then
    echo "   PASSED: Key Vault firewall defaults to Deny"
else
    echo "   [ERROR] FAILED: Key Vault firewall should default to Deny"
    exit 1
fi
echo ""

# Test 4: Verify ip_rules is empty (no IP-based firewall)
echo "[OK] Test 4: Verify ip_rules is empty (relying on AzureServices bypass)"
if grep -q 'ip_rules = \[\]' security.tf; then
    echo "   PASSED: ip_rules is empty (no IP-based firewall)"
else
    echo "   [ERROR] FAILED: ip_rules should be empty to avoid dynamic IP issues"
    exit 1
fi
echo ""

# Test 5: Verify AzureServices bypass is enabled
echo "[OK] Test 5: Verify AzureServices bypass is enabled"
if grep -q 'bypass.*=.*"AzureServices"' security.tf; then
    echo "   PASSED: AzureServices bypass is enabled"
else
    echo "   [ERROR] FAILED: AzureServices bypass should be enabled for Managed Identity"
    exit 1
fi
echo ""

# Test 6: Verify time_sleep resource exists and has correct duration
echo "[OK] Test 6: Verify time_sleep resource with 90s duration"
if grep -q 'resource "time_sleep" "wait_for_rbac_and_firewall"' security.tf && \
   grep -q 'create_duration = "90s"' security.tf; then
    echo "   PASSED: time_sleep resource configured with 90s wait"
else
    echo "   [ERROR] FAILED: time_sleep resource should have 90s duration"
    exit 1
fi
echo ""

# Test 7: Verify all secrets depend on time_sleep
echo "[OK] Test 7: Verify all secrets depend on time_sleep"
DEPENDS_COUNT=$(grep -c 'depends_on.*=.*\[time_sleep.wait_for_rbac_and_firewall\]' security.tf || echo 0)

if [ "$DEPENDS_COUNT" -ge 8 ]; then
    echo "   PASSED: All $DEPENDS_COUNT secrets depend on time_sleep"
else
    echo "   [ERROR] FAILED: Expected at least 8 secrets to depend on time_sleep, found $DEPENDS_COUNT"
    exit 1
fi
echo ""

# Test 8: Verify time_sleep depends on Key Vault creation
echo "[OK] Test 8: Verify time_sleep depends on azurerm_key_vault.main"
if grep -A 5 'resource "time_sleep" "wait_for_rbac_and_firewall"' security.tf | grep -q 'azurerm_key_vault.main'; then
    echo "   PASSED: time_sleep depends on Key Vault creation"
else
    echo "   [ERROR] FAILED: time_sleep should depend on azurerm_key_vault.main"
    exit 1
fi
echo ""

echo " All validation tests PASSED!"
echo ""
echo "Summary of Changes (v2 - Azure Services Bypass):"
echo "  [OK] Key Vault firewall always denies by default (secure)"
echo "  [OK] No IP-based rules (avoids dynamic IP issues)"
echo "  [OK] AzureServices bypass enabled (allows GitHub Actions Managed Identity)"
echo "  [OK] RBAC controls access (WHO can access)"
echo "  [OK] VNet integration for AKS pods"
echo "  [OK] 90-second wait for RBAC propagation"
echo "  [OK] All 8+ secrets depend on propagation wait"
echo ""
echo " Ready for commit and deployment!"
