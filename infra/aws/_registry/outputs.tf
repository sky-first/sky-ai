output "ecr_registry_url" {
  description = "ECR registry hostname for docker login. Use in CI: $ECR_REGISTRY/sky-<repo>:<tag>"
  value       = "${var.staging_account_id}.dkr.ecr.${var.region}.amazonaws.com"
}

output "ecr_repository_urls" {
  description = "Full URL of each ECR repository. Map: repo_name -> URL."
  value = {
    for name, repo in aws_ecr_repository.app : name => repo.repository_url
  }
}

output "ecr_repository_arns" {
  description = "ARN of each ECR repository."
  value = {
    for name, repo in aws_ecr_repository.app : name => repo.arn
  }
}

output "github_actions_role_arns" {
  description = "ARN of each GitHub Actions IAM role. Use in workflow's role-to-assume."
  value = {
    for name, role in aws_iam_role.gha_push : name => role.arn
  }
}

output "github_oidc_provider_arn" {
  description = "ARN of the GitHub OIDC provider in this account."
  value       = aws_iam_openid_connect_provider.github.arn
}
