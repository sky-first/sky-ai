module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.13"

  name = "sky-vpc-${var.environment}"
  cidr = var.vpc_cidr

  azs = var.azs

  # /24 each = 256 IPs per AZ. Used by ALB and NAT GW.
  public_subnets = [
    cidrsubnet(var.vpc_cidr, 8, 0), # 10.0.0.0/24
    cidrsubnet(var.vpc_cidr, 8, 1), # 10.0.1.0/24
    cidrsubnet(var.vpc_cidr, 8, 2), # 10.0.2.0/24
  ]

  # /22 each = 1024 IPs per AZ. EKS pods consume IPs (VPC CNI), needs space.
  private_subnets = [
    cidrsubnet(var.vpc_cidr, 6, 4), # 10.0.16.0/22
    cidrsubnet(var.vpc_cidr, 6, 5), # 10.0.20.0/22
    cidrsubnet(var.vpc_cidr, 6, 6), # 10.0.24.0/22
  ]

  # /24 each. RDS + ElastiCache subnet group goes here, isolated from app pods.
  database_subnets = [
    cidrsubnet(var.vpc_cidr, 8, 32), # 10.0.32.0/24
    cidrsubnet(var.vpc_cidr, 8, 33), # 10.0.33.0/24
    cidrsubnet(var.vpc_cidr, 8, 34), # 10.0.34.0/24
  ]

  enable_nat_gateway     = true
  single_nat_gateway     = true # single NAT GW for staging — saves ~$66/month vs HA
  one_nat_gateway_per_az = false

  enable_dns_hostnames = true
  enable_dns_support   = true

  # Tags required by EKS for subnet auto-discovery
  public_subnet_tags = {
    "kubernetes.io/role/elb" = "1"
  }
  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = "1"
  }

  # Enable VPC flow logs for security/troubleshooting
  enable_flow_log                      = true
  create_flow_log_cloudwatch_log_group = true
  create_flow_log_cloudwatch_iam_role  = true
  flow_log_max_aggregation_interval    = 60

  tags = {
    Project = "Sky"
  }
}
