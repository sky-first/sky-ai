# EKS Staging Module

> Runs against **`sky-staging`** account (`741375879811`).
> Provisions VPC, EKS cluster, RDS Postgres, ElastiCache Redis, and Secrets Manager entries.

## What this creates

### Network
- **VPC** `10.0.0.0/16` in eu-west-1
- **3 public subnets** (one per AZ) — for ALB / NAT GW
- **3 private subnets** (one per AZ) — for EKS nodes, RDS, ElastiCache
- **1 NAT Gateway** (single AZ for staging — saves ~$66/month vs 3 NAT GWs)
- **Internet Gateway**
- VPC Flow Logs to CloudWatch (10% sampling)

### EKS
- **EKS cluster** `sky-eks-staging` running Kubernetes 1.31
- **OIDC provider** for IRSA (workload identity)
- **Cluster addons**: vpc-cni, coredns, kube-proxy, eks-pod-identity-agent, aws-ebs-csi-driver
- **2 managed node groups**:
  - `infra`: 2x t3.large (8GB RAM each) — for ArgoCD, ESO, monitoring, ingress
  - `apps`: 1-3x t3.large autoscale — for sky-frontend, sky-backend, sky-ai

### Database
- **RDS PostgreSQL 16** `db.t3.small`
  - Storage: 20GB gp3 (autoscale to 100GB)
  - **pgvector** extension via parameter group
  - Backup: 7 days retention
  - Single AZ (staging — multi-AZ in production)
  - Username: `skyadmin`, password: random, stored in Secrets Manager
- **ElastiCache Redis 7.1** `cache.t3.micro`
  - Single node (no replicas in staging)
  - Encryption at rest + in transit
  - Auth token stored in Secrets Manager

### Secrets
- `sky/staging/postgres` — JSON with host, port, user, password, dbname
- `sky/staging/redis` — JSON with host, port, auth_token

## State

- State location: `s3://sky-tf-state-eu-west-1/eks-staging/terraform.tfstate`
- Lock: S3 native (`use_lockfile = true`)

## Apply

```bash
export AWS_PROFILE=sky-staging
cd infra/aws/_eks_staging
terraform init -backend-config=backend.hcl
terraform plan
terraform apply
```

EKS cluster creation takes ~15-20 min. Total apply: ~25-30 min.

## After apply

```bash
# Configure kubectl
aws eks update-kubeconfig --name sky-eks-staging --region eu-west-1 --profile sky-staging

# Verify
kubectl get nodes
kubectl get pods -A
```

## Cost estimate

| Item | $/month |
|---|---|
| EKS control plane | $73 |
| 2× t3.large (infra) | $120 |
| 1× t3.large (apps, baseline) | $60 |
| RDS db.t3.small + 20GB gp3 | $35 |
| ElastiCache cache.t3.micro | $13 |
| NAT Gateway (1) | $33 |
| Data transfer baseline | $5 |
| Secrets Manager (~3 secrets) | $1 |
| CloudWatch logs | $5 |
| **Total staging** | **~$345/month** |

## Outputs

After apply, important outputs to feed into other modules:
- `cluster_name`, `cluster_endpoint`, `cluster_oidc_provider_arn`
- `vpc_id`, `private_subnet_ids`
- `postgres_secret_arn`, `redis_secret_arn`
