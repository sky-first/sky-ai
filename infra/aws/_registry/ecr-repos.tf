resource "aws_ecr_repository" "app" {
  for_each = toset(var.image_repos)

  name                 = each.key
  image_tag_mutability = "MUTABLE" # allow re-tag for :latest, :production, :staging
  force_delete         = false     # safety: don't allow accidental delete with images present

  image_scanning_configuration {
    scan_on_push = true # cheap and finds CVEs early
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  lifecycle {
    prevent_destroy = true # protect against accidental destroy of registry holding all images
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  for_each = aws_ecr_repository.app

  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 30 tagged images"
        selection = {
          tagStatus     = "tagged"
          tagPatternList = ["*"]
          countType     = "imageCountMoreThan"
          countNumber   = 30
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Expire untagged images after 14 days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 14
        }
        action = { type = "expire" }
      }
    ]
  })
}

# Cross-account pull policy.
# Allows production account (and any additional accounts) to pull images
# without granting them push access.
locals {
  pull_account_ids = concat(
    [var.production_account_id],
    var.additional_pull_account_ids,
  )
}

resource "aws_ecr_repository_policy" "cross_account_pull" {
  for_each = aws_ecr_repository.app

  repository = each.value.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "AllowCrossAccountPull"
      Effect = "Allow"
      Principal = {
        AWS = [for id in local.pull_account_ids : "arn:aws:iam::${id}:root"]
      }
      Action = [
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage",
        "ecr:BatchCheckLayerAvailability",
      ]
    }]
  })
}
