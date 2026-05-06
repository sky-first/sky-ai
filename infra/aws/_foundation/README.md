# Foundation Module

> Runs **once**, against the AWS Organization **management account** (`lucasventura`, `755400488974`).
> Provisions the org-wide foundation that every other module depends on.

## What this creates

- **S3 bucket** for Terraform remote state — `sky-tf-state-eu-west-1`
  - Versioning enabled (recover from bad applies)
  - Encryption at rest (AES-256)
  - Public access blocked
  - Lifecycle: noncurrent versions expire after 90 days
- **DynamoDB table** for Terraform state locking — `sky-tf-locks`
  - PAY_PER_REQUEST billing (negligible cost at our scale)

## Bootstrap procedure (chicken-and-egg)

The state bucket is itself a Terraform-managed resource, so the **first** apply must use local state, then migrate.

```bash
# 1. Authenticate to sky-management profile
aws sso login --profile sky-mgmt

# 2. First-time init — local state (backend.tf comment block left commented)
cd infra/aws/_foundation
terraform init

# 3. Plan & apply — creates the bucket and table
terraform plan -var-file=variables.tfvars
terraform apply -var-file=variables.tfvars

# 4. Uncomment the `backend "s3" {}` block in backend.tf
#    Then migrate state to S3
terraform init -migrate-state -backend-config="bucket=sky-tf-state-eu-west-1" \
                              -backend-config="key=foundation/terraform.tfstate" \
                              -backend-config="region=eu-west-1" \
                              -backend-config="dynamodb_table=sky-tf-locks" \
                              -backend-config="encrypt=true"
# When prompted "yes" — state moves to S3.

# 5. Re-run plan to confirm no drift
terraform plan
# Should show "No changes."
```

## Outputs

After apply, these outputs are consumed by other modules:

| Output | Used by |
|---|---|
| `state_bucket_name` | All other modules' backend config |
| `state_lock_table_name` | All other modules' backend config |

## Cost

- S3: ~$0.05/month (10MB state, infrequent access)
- DynamoDB: ~$0.01/month (PAY_PER_REQUEST, very low ops)
- **Total: ~$0.10/month**

## Re-run

This module is **idempotent** — re-running `terraform apply` after the first apply is a no-op unless variables change.
