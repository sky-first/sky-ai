# Backend configuration.
#
# After the bucket and lock table exist (created by the very first apply with
# local state), state is stored in S3. New `terraform init` runs use this backend.
#
# Bootstrap procedure (one-time, already done):
#   1. Comment out the backend block, run `terraform apply` (creates bucket + table).
#   2. Uncomment the block (current state).
#   3. Run:
#        terraform init -migrate-state \
#          -backend-config="bucket=sky-tf-state-eu-west-1" \
#          -backend-config="key=foundation/terraform.tfstate" \
#          -backend-config="region=eu-west-1" \
#          -backend-config="dynamodb_table=sky-tf-locks" \
#          -backend-config="encrypt=true"
#   4. Confirm with `yes` when prompted to copy local state to S3.
#
# After migration, future `terraform init` runs need the same -backend-config flags
# (or use the backend.hcl pattern).

terraform {
  backend "s3" {
    # Values are passed via -backend-config flags or backend.hcl file.
    # Hardcoding here is intentionally avoided so the same code can target
    # different state buckets in different environments if needed.
  }
}
