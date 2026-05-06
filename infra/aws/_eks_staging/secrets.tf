resource "aws_secretsmanager_secret" "postgres" {
  name        = "sky/${var.environment}/postgres"
  description = "Sky ${var.environment} PostgreSQL connection details"
  recovery_window_in_days = 0 # staging — fast recreation; production should use 7+
}

resource "aws_secretsmanager_secret_version" "postgres" {
  secret_id = aws_secretsmanager_secret.postgres.id

  secret_string = jsonencode({
    host     = aws_db_instance.postgres.address
    port     = aws_db_instance.postgres.port
    username = aws_db_instance.postgres.username
    password = random_password.postgres.result
    dbname   = aws_db_instance.postgres.db_name
    url      = "postgresql://${aws_db_instance.postgres.username}:${random_password.postgres.result}@${aws_db_instance.postgres.address}:${aws_db_instance.postgres.port}/${aws_db_instance.postgres.db_name}"
  })
}

resource "aws_secretsmanager_secret" "redis" {
  name        = "sky/${var.environment}/redis"
  description = "Sky ${var.environment} Redis connection details"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "redis" {
  secret_id = aws_secretsmanager_secret.redis.id

  secret_string = jsonencode({
    host       = aws_elasticache_replication_group.redis.primary_endpoint_address
    port       = aws_elasticache_replication_group.redis.port
    auth_token = random_password.redis_auth.result
    url        = "rediss://default:${random_password.redis_auth.result}@${aws_elasticache_replication_group.redis.primary_endpoint_address}:${aws_elasticache_replication_group.redis.port}"
  })
}
