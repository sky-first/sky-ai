# WAF Migration Runbook: ModSecurity → Azure Front Door WAF
**Ticket:** DO2025-1044  
**Applies to:** Environments with `enable_geo_dr = true`

---

## Context

When Geo-DR is activated, Azure Front Door (AFD) with WAF sits in front of all traffic.
The existing ModSecurity rules in ingress-nginx must be migrated to AFD WAF rules to avoid
double-WAF overhead and conflicting policies.

**Current state (ModSecurity):**
- OWASP Core Rule Set (CRS) via ingress-nginx annotation `modsecurity-snippet`
- Custom bypasses for SSO callback URIs (`/api/auth/sso/`)
- WAF disabled for AI service (rules 941160, 941100, 942100, 942200, 920420)

**Target state (AFD WAF):**
- Microsoft_DefaultRuleSet 2.1 (equivalent to OWASP CRS)
- Microsoft_BotManagerRuleSet 1.0
- Custom exclusions for SSO and AI prompts

---

## Phase 1 — Detection Mode Validation (Week 1-2)

AFD WAF is deployed in **Detection mode** (logs but does not block). Validate that
all legitimate traffic passes without WAF log errors.

```bash
# Check AFD WAF logs for false positives
az monitor log-analytics query \
  --workspace <WORKSPACE_ID> \
  --analytics-query "
    AzureDiagnostics
    | where ResourceType == 'FRONTDOORS'
    | where Category == 'FrontdoorWebApplicationFirewallLog'
    | where action_s == 'Block'
    | project TimeGenerated, requestUri_s, ruleName_s, action_s
    | order by TimeGenerated desc
    | take 100
  " \
  --timespan P7D
```

---

## Phase 2 — Add Custom Exclusions

Based on Detection mode logs, add exclusions before switching to Prevention.

### SSO Callback (equivalent to current ModSecurity bypass)

In `dr.tf`, add to the WAF policy:

```hcl
# Custom exclusion for SSO callback URIs
# Mirrors: SecRule REQUEST_URI "@beginsWith /api/auth/sso/" "ctl:ruleEngine=Off"
custom_rule {
  name     = "AllowSSOCallback"
  priority = 100
  action   = "Allow"
  type     = "MatchRule"

  match_condition {
    match_variable     = "RequestUri"
    operator           = "BeginsWith"
    match_values       = ["/api/auth/sso/", "/api/v1/auth/sso/"]
    negation_condition = false
    transforms         = []
  }
}
```

### AI Service (equivalent to disabled WAF rules)

```hcl
# Exclusion for AI prompt content
# Mirrors: SecRuleRemoveById 941160 941100 942100 942200 920420
managed_rule {
  action  = "Block"
  version = "2.1"
  type    = "Microsoft_DefaultRuleSet"

  exclusion {
    match_variable = "RequestBodyPostArgNames"
    operator       = "Contains"
    selector       = "prompt"
  }
}
```

---

## Phase 3 — Switch to Prevention Mode

Only after **zero false positives** in Detection mode for 7 consecutive days.

Change in `dr.tf`:

```hcl
# Before:
mode = "Detection"

# After:
mode = "Prevention"
```

Apply:

```bash
cd infra/aks
terraform apply -var-file=environments/client-vip.tfvars \
  -target=azurerm_cdn_frontdoor_firewall_policy.global_waf
```

---

## Phase 4 — Remove ModSecurity from ingress-nginx

After confirming AFD WAF is blocking correctly in Prevention mode for 48h,
remove the ModSecurity annotations from:

- `gitops/bootstrap/staging/backend.yaml`
- `gitops/bootstrap/staging/ai.yaml`

The `nginx.ingress.kubernetes.io/modsecurity-snippet` annotations can be deleted.

---

## Rollback

If AFD WAF blocks legitimate traffic in Prevention mode:

```bash
# Immediate: switch back to Detection
az afd waf-policy update \
  --policy-name skyWafPolicyprod-vip \
  --resource-group sky-aks-vip-rg \
  --mode Detection
```
