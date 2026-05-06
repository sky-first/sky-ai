output "state_bucket_name" {
  description = "Name of the S3 bucket for Terraform state. Use in -backend-config of other modules."
  value       = aws_s3_bucket.tf_state.id
}

output "state_bucket_arn" {
  description = "ARN of the state bucket. Use in cross-account IAM policies if other accounts need read access."
  value       = aws_s3_bucket.tf_state.arn
}

output "state_lock_table_name" {
  description = "Name of the DynamoDB table for Terraform state locking. Use in -backend-config of other modules."
  value       = aws_dynamodb_table.tf_locks.id
}

output "region" {
  description = "Region the foundation lives in. All workload modules must use the same region for state."
  value       = var.region
}
