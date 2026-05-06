resource "aws_elasticache_subnet_group" "redis" {
  name       = "sky-redis-${var.environment}"
  subnet_ids = module.vpc.database_subnets
}

resource "aws_security_group" "redis" {
  name        = "sky-redis-${var.environment}"
  description = "Redis access from EKS node security group"
  vpc_id      = module.vpc.vpc_id
}

resource "aws_security_group_rule" "redis_from_eks" {
  type                     = "ingress"
  from_port                = 6379
  to_port                  = 6379
  protocol                 = "tcp"
  source_security_group_id = module.eks.node_security_group_id
  security_group_id        = aws_security_group.redis.id
  description              = "Redis 6379 from EKS nodes"
}

resource "aws_security_group_rule" "redis_egress" {
  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.redis.id
}

resource "random_password" "redis_auth" {
  length  = 32
  special = false # AUTH token alphanumeric only for some Redis versions
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id       = "sky-redis-${var.environment}"
  description                = "Sky Redis ${var.environment}"
  engine                     = "redis"
  engine_version             = "7.1"
  node_type                  = var.redis_node_type
  num_cache_clusters         = 1
  parameter_group_name       = "default.redis7"
  port                       = 6379
  subnet_group_name          = aws_elasticache_subnet_group.redis.name
  security_group_ids         = [aws_security_group.redis.id]
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  auth_token                 = random_password.redis_auth.result

  automatic_failover_enabled = false # single node in staging
  multi_az_enabled           = false

  snapshot_retention_limit = 1

  apply_immediately = true

  tags = {
    Name = "sky-redis-${var.environment}"
  }
}
