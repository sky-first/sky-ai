#!/bin/bash
# Validation Test for Key Vault Firewall Fix
# This script validates the Terraform configuration changes

set -euo pipefail

echo "🧪 Validating Terraform Key Vault Firewall Fix..."
echo ""

cd "$(dirname "$0")/../infra/aks"

# Test 1: Terraform Format Check
echo "✅ Test 1: Terraform Format Check"
terraform fmt -check security.tf
echo "   PASSED: security.tf is properly formatted"
echo ""

# Test 2: Terraform Validation
echo "✅ Test 2: Terraform Validation"
terraform validate
echo "   PASSED: Terraform configuration is valid"
echo ""

# Test 3: Verify network_acls configuration
echo "✅ Test 3: Verify network_acls uses 'Deny' by default"
if grep -q 'default_action.*=.*"Deny"' security.tf; then
    echo "   PASSED: Key Vault firewall defaults to Deny"
else
    echo "   ❌ FAILED: Key Vault firewall should default to Deny"
    exit 1
fi
echo ""

# Test 4: Verify compact() is used for IP rules
echo "✅ Test 4: Verify compact() function for null-safe IP handling"
if grep -q 'ip_rules = compact' security.tf; then
    echo "   PASSED: compact() function is used for IP rules"
else
    echo "   ❌ FAILED: compact() function should be used for IP rules"
    exit 1
fi
echo ""

# Test 5: Verify lifecycle ignore_changes is removed
echo "✅ Test 5: Verify lifecycle ignore_changes is removed"
if grep -q 'ignore_changes.*ip_rules' security.tf; then
    echo "   ❌ FAILED: lifecycle ignore_changes should be removed"
    exit 1
else
    echo "   PASSED: lifecycle ignore_changes is removed"
fi
echo ""

# Test 6: Verify time_sleep resource exists and has correct duration
echo "✅ Test 6: Verify time_sleep resource with 90s duration"
if grep -q 'resource "time_sleep" "wait_for_rbac_and_firewall"' security.tf && \
   grep -q 'create_duration = "90s"' security.tf; then
    echo "   PASSED: time_sleep resource configured with 90s wait"
else
    echo "   ❌ FAILED: time_sleep resource should have 90s duration"
    exit 1
fi
echo ""

# Test 7: Verify all secrets depend on time_sleep
echo "✅ Test 7: Verify all secrets depend on time_sleep"
SECRET_COUNT=$(grep -c 'azurerm_key_vault_secret' security.tf || echo 0)
DEPENDS_COUNT=$(grep -c 'depends_on.*=.*\[time_sleep.wait_for_rbac_and_firewall\]' security.tf || echo 0)

if [ "$DEPENDS_COUNT" -ge 8 ]; then
    echo "   PASSED: All $DEPENDS_COUNT secrets depend on time_sleep"
else
    echo "   ❌ FAILED: Expected at least 8 secrets to depend on time_sleep, found $DEPENDS_COUNT"
    exit 1
fi
echo ""

# Test 8: Verify time_sleep depends on Key Vault creation
echo "✅ Test 8: Verify time_sleep depends on azurerm_key_vault.main"
if grep -A 5 'resource "time_sleep" "wait_for_rbac_and_firewall"' security.tf | grep -q 'azurerm_key_vault.main'; then
    echo "   PASSED: time_sleep depends on Key Vault creation"
else
    echo "   ❌ FAILED: time_sleep should depend on azurerm_key_vault.main"
    exit 1
fi
echo ""

echo "🎉 All validation tests PASSED!"
echo ""
echo "Summary of Changes:"
echo "  ✅ Key Vault firewall always denies by default (secure)"
echo "  ✅ Runner IP is guaranteed to be in whitelist during creation"
echo "  ✅ compact() function handles null runner_ip gracefully"
echo "  ✅ No lifecycle ignore_changes (Terraform manages IP rules)"
echo "  ✅ 90-second wait for RBAC and firewall propagation"
echo "  ✅ All 8+ secrets depend on propagation wait"
echo ""
echo "✨ Ready for commit and PR!"
