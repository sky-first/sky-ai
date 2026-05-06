module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.31"

  cluster_name    = var.cluster_name
  cluster_version = var.kubernetes_version

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  # Public API endpoint with no IP restriction (harden later when ingress is up).
  # Private endpoint also enabled so nodes inside VPC reach it without NAT.
  cluster_endpoint_public_access  = true
  cluster_endpoint_private_access = true

  # Enable IRSA — workload identity for K8s service accounts.
  enable_irsa = true

  # Cluster addons managed by EKS (auto-updated, AWS-managed lifecycle)
  cluster_addons = {
    vpc-cni = {
      most_recent = true
      configuration_values = jsonencode({
        env = {
          # Prefix delegation: assigns /28 chunks to ENIs, more pods per node
          ENABLE_PREFIX_DELEGATION = "true"
          WARM_PREFIX_TARGET       = "1"
        }
      })
    }
    coredns                = { most_recent = true }
    kube-proxy             = { most_recent = true }
    eks-pod-identity-agent = { most_recent = true }
    aws-ebs-csi-driver     = { most_recent = true }
  }

  # The principal applying terraform (AWSAdministratorAccess SSO role) gets
  # cluster-admin in EKS. SSO admin role mappings can be added later via
  # access_entries when needed.
  enable_cluster_creator_admin_permissions = true

  # Managed node groups — AWS handles AMI updates, scaling, drain on update
  eks_managed_node_groups = {
    infra = {
      name           = "infra"
      instance_types = [var.node_instance_type_infra]

      min_size     = 2
      max_size     = 2
      desired_size = 2

      # Keep apps off these nodes via taint
      labels = {
        "sky-pool" = "infra"
      }
      taints = {
        infra = {
          key    = "sky-pool"
          value  = "infra"
          effect = "NO_SCHEDULE"
        }
      }
    }

    apps = {
      name           = "apps"
      instance_types = [var.node_instance_type_apps]

      min_size     = 1
      max_size     = 3
      desired_size = 1

      labels = {
        "sky-pool" = "apps"
      }
      # No taints — default workload pool
    }
  }

  node_security_group_additional_rules = {
    # Pod-to-pod within VPC
    ingress_self_all = {
      description = "Node to node all ports"
      protocol    = "-1"
      from_port   = 0
      to_port     = 0
      type        = "ingress"
      self        = true
    }
    # Egress all — needed for image pulls, AWS API, etc.
    egress_all = {
      description      = "All egress"
      protocol         = "-1"
      from_port        = 0
      to_port          = 0
      type             = "egress"
      cidr_blocks      = ["0.0.0.0/0"]
      ipv6_cidr_blocks = ["::/0"]
    }
  }
}
