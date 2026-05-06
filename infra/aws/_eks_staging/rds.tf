# Postgres parameter group with pgvector enabled
resource "aws_db_parameter_group" "postgres" {
  name   = "sky-postgres-${var.environment}-pgvector"
  family = "postgres16"

  # Enable pgvector via shared_preload_libraries.
  # Note: pgvector ships with RDS Postgres 16 — no install step needed.
  # Just `CREATE EXTENSION vector;` after database is up.
  parameter {
    name         = "shared_preload_libraries"
    value        = "pg_stat_statements"
    apply_method = "pending-reboot"
  }
}

resource "aws_db_subnet_group" "postgres" {
  name       = "sky-postgres-${var.environment}"
  subnet_ids = module.vpc.database_subnets
}

resource "aws_security_group" "postgres" {
  name        = "sky-postgres-${var.environment}"
  description = "PostgreSQL access from EKS node security group"
  vpc_id      = module.vpc.vpc_id
}

resource "aws_security_group_rule" "postgres_from_eks" {
  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = module.eks.node_security_group_id
  security_group_id        = aws_security_group.postgres.id
  description              = "Postgres 5432 from EKS nodes"
}

resource "aws_security_group_rule" "postgres_egress" {
  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.postgres.id
}

resource "random_password" "postgres" {
  length  = 32
  special = false # avoid AWS' picky char restrictions
}

resource "aws_db_instance" "postgres" {
  identifier = "sky-postgres-${var.environment}"

  engine         = "postgres"
  engine_version = "16.4"
  instance_class = var.rds_instance_class

  allocated_storage     = var.rds_allocated_storage
  max_allocated_storage = 100 # autoscale ceiling
  storage_encrypted     = true
  storage_type          = "gp3"

  db_name  = "skyaisaas"
  username = "skyadmin"
  password = random_password.postgres.result
  port     = 5432

  parameter_group_name   = aws_db_parameter_group.postgres.name
  db_subnet_group_name   = aws_db_subnet_group.postgres.name
  vpc_security_group_ids = [aws_security_group.postgres.id]

  publicly_accessible = false
  multi_az            = false # staging — single AZ saves ~50%

  backup_retention_period   = 7
  backup_window             = "03:00-04:00" # UTC
  maintenance_window        = "mon:04:00-mon:05:00"
  copy_tags_to_snapshot     = true
  delete_automated_backups  = false
  skip_final_snapshot       = true # staging only — production must NOT skip
  deletion_protection       = false # staging only — production must enable
  performance_insights_enabled = true
  performance_insights_retention_period = 7

  enabled_cloudwatch_logs_exports = ["postgresql"]

  apply_immediately = false

  tags = {
    Name = "sky-postgres-${var.environment}"
  }
}
