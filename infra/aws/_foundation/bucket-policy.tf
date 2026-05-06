# Cross-account access to the state bucket.
#
# Each member account (sky-staging, sky-production, future clients) gets
# scoped read/write access ONLY to its own state prefixes.
#
# Pattern: <module-name>-<env>/  (e.g., registry-staging/, eks-staging/)
# Each environment has its own prefixes; one account cannot read another's.
#
# Adding a new account: append a statement here, run `terraform apply` in
# this module, and the new account can immediately use the state bucket.

locals {
  # Map of account_id -> list of prefixes that account can read/write.
  state_prefix_grants = {
    (var.staging_account_id) = [
      "registry-staging/",
      "eks-staging/",
    ]
    (var.production_account_id) = [
      "eks-production/",
      "registry-production/",
    ]
  }
}

data "aws_iam_policy_document" "tf_state" {
  # Per-account statements: read/write objects under granted prefixes.
  dynamic "statement" {
    for_each = local.state_prefix_grants
    content {
      sid    = "AllowAccount${replace(statement.key, "/[^a-zA-Z0-9]/", "")}ObjectAccess"
      effect = "Allow"
      principals {
        type        = "AWS"
        identifiers = ["arn:aws:iam::${statement.key}:root"]
      }
      actions = [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
      ]
      resources = [
        for prefix in statement.value : "${aws_s3_bucket.tf_state.arn}/${prefix}*"
      ]
    }
  }

  # Per-account statements: list bucket scoped to granted prefixes.
  dynamic "statement" {
    for_each = local.state_prefix_grants
    content {
      sid    = "AllowAccount${replace(statement.key, "/[^a-zA-Z0-9]/", "")}List"
      effect = "Allow"
      principals {
        type        = "AWS"
        identifiers = ["arn:aws:iam::${statement.key}:root"]
      }
      actions   = ["s3:ListBucket"]
      resources = [aws_s3_bucket.tf_state.arn]
      condition {
        test     = "StringLike"
        variable = "s3:prefix"
        values   = [for prefix in statement.value : "${prefix}*"]
      }
    }
  }
}

resource "aws_s3_bucket_policy" "tf_state" {
  bucket = aws_s3_bucket.tf_state.id
  policy = data.aws_iam_policy_document.tf_state.json
}

# DynamoDB resource policy — allow lock table operations from member accounts.
# Required because Terraform locking uses DynamoDB cross-account.
data "aws_iam_policy_document" "tf_locks" {
  statement {
    sid    = "AllowMemberAccountsLockOps"
    effect = "Allow"
    principals {
      type = "AWS"
      identifiers = [
        "arn:aws:iam::${var.staging_account_id}:root",
        "arn:aws:iam::${var.production_account_id}:root",
      ]
    }
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:DeleteItem",
      "dynamodb:DescribeTable",
    ]
    resources = [aws_dynamodb_table.tf_locks.arn]
  }
}

resource "aws_dynamodb_resource_policy" "tf_locks" {
  resource_arn = aws_dynamodb_table.tf_locks.arn
  policy       = data.aws_iam_policy_document.tf_locks.json
}
