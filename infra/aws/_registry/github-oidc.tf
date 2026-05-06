# GitHub Actions OIDC provider in sky-staging.
# One provider per account that runs GitHub Actions workflows.
# Thumbprints rotate occasionally — these are the current GitHub root CA fingerprints.

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a3a8518e8759bf075b76b750d4f2df264fcd",
  ]
}

# One IAM role per repo. Each role can only push to its matching ECR repo.
# Trust policy uses StringLike with `repo:<org>/<repo>:*` so any branch in that
# repo can assume it (refine to `:ref:refs/heads/main` if you want stricter).

resource "aws_iam_role" "gha_push" {
  for_each = toset(var.image_repos)

  name        = "sky-gha-${each.key}"
  description = "GitHub Actions role for ${var.github_org}/${each.key} to push to ECR ${each.key}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_org}/${each.key}:*"
        }
      }
    }]
  })

  max_session_duration = 3600 # 1h is enough for a build job
}

# Permission policy: ECR push limited to the matching repo.
resource "aws_iam_role_policy" "gha_push_ecr" {
  for_each = aws_iam_role.gha_push

  name = "ecr-push-${each.key}"
  role = each.value.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ECRAuthToken"
        Effect = "Allow"
        Action = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "ECRPushPullSpecificRepo"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:PutImage",
        ]
        Resource = aws_ecr_repository.app[each.key].arn
      }
    ]
  })
}
