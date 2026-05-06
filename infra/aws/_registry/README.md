# Registry Module

> Runs against **`sky-staging`** account (`741375879811`).
> Hosts the central ECR registry **temporarily** here until quota approval allows creating `sky-shared`.
> When `sky-shared` is created, this module migrates there (re-tag and push images, update Helm values).

## What this creates

- **3 ECR repositories** (private):
  - `sky-frontend` — Next.js frontend image
  - `sky-backend` — FastAPI backend image
  - `sky-ai` — LangGraph AI service image
- **ECR lifecycle policies**: keep last 30 tagged images, expire untagged after 14 days
- **ECR repository policies**: allow cross-account pull from:
  - `sky-staging` itself (apps run here in same account — no policy needed)
  - `sky-production` (`032080729567`)
  - Future client accounts (added when they exist)
- **GitHub OIDC provider** (one per account)
- **3 IAM roles**, one per repo, that GitHub Actions assume to push images:
  - `sky-gha-sky-frontend` — only push to `sky-frontend` repo
  - `sky-gha-sky-backend` — only push to `sky-backend` repo
  - `sky-gha-sky-ai` — only push to `sky-ai` repo

Principle of least privilege: each repo's CI can only push to its own ECR.

## How GitHub Actions consume this

Each app repo (`sky-frontend`, `sky-backend`, `sky-ai`) has a workflow like:

```yaml
permissions:
  id-token: write
  contents: read

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::741375879811:role/sky-gha-sky-frontend
          aws-region: eu-west-1
      - uses: aws-actions/amazon-ecr-login@v2
      - run: docker build -t $ECR_REGISTRY/sky-frontend:$GITHUB_SHA .
      - run: docker push $ECR_REGISTRY/sky-frontend:$GITHUB_SHA
```

## State

State location: `s3://sky-tf-state-eu-west-1/registry-staging/terraform.tfstate`
Lock table: `sky-tf-locks` (DynamoDB)

## Init / apply

```bash
export AWS_PROFILE=sky-staging  # or use --profile flag
cd infra/aws/_registry
terraform init -backend-config=backend.hcl
terraform plan
terraform apply
```

## Cost

- ECR storage: free for first 500 MB, then $0.10/GB/month
- ECR data transfer: $0.09/GB outbound (cross-region pulls — minimize by keeping clusters in eu-west-1)
- IAM/OIDC: $0
- **Total: ~$1-5/month** with realistic usage

## Future migration to `sky-shared`

When the AWS Organizations quota is increased and `sky-shared` is created, this module needs to be re-targeted:

1. Backup ECR images: `docker pull` all images locally, `docker push` to new repo in sky-shared
2. Update Terraform: change `provider` profile from `sky-staging` → `sky-shared`
3. `terraform import` existing resources into the new state file
4. Update Helm values / GitHub Actions to point to new ECR registry URL
5. Delete repos from sky-staging when no longer pulled
