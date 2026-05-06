output "vpc_id" {
  value = module.vpc.vpc_id
}

output "private_subnet_ids" {
  value = module.vpc.private_subnets
}

output "public_subnet_ids" {
  value = module.vpc.public_subnets
}

output "cluster_name" {
  value = module.eks.cluster_name
}

output "cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "cluster_certificate_authority_data" {
  value     = module.eks.cluster_certificate_authority_data
  sensitive = true
}

output "cluster_oidc_provider_arn" {
  description = "ARN of the EKS cluster OIDC provider — used for IRSA assume role policies"
  value       = module.eks.oidc_provider_arn
}

output "cluster_oidc_provider_url" {
  description = "Issuer URL of the EKS cluster OIDC provider"
  value       = module.eks.cluster_oidc_issuer_url
}

output "node_security_group_id" {
  value = module.eks.node_security_group_id
}

output "postgres_endpoint" {
  value = aws_db_instance.postgres.address
}

output "postgres_secret_arn" {
  value = aws_secretsmanager_secret.postgres.arn
}

output "redis_endpoint" {
  value = aws_elasticache_replication_group.redis.primary_endpoint_address
}

output "redis_secret_arn" {
  value = aws_secretsmanager_secret.redis.arn
}

output "kubectl_config_command" {
  description = "Command to update kubeconfig with this cluster."
  value       = "aws eks update-kubeconfig --name ${module.eks.cluster_name} --region ${var.region} --profile sky-staging"
}
