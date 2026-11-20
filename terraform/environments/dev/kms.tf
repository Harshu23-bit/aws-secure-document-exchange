# KMS KEY POLICY
data "aws_iam_policy_document" "application_kms" {

  #checkov:skip=CKV_AWS_356:KMS key-policy Resource * refers only to this application key and does not grant access to every KMS key.

  #checkov:skip=CKV_AWS_109:Standard account-root delegation enables IAM authorization; effective application-role permissions are separately restricted.

  #checkov:skip=CKV_AWS_111:This is the standard KMS account-delegation statement; actual key usage is controlled through IAM permissions.

  statement {
    sid    = "EnableIAMUserPermissions"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }

    actions   = ["kms:*"]
    resources = ["*"]
  }

  statement {
    sid    = "AllowDynamoDBUseOfApplicationKey"
    effect = "Allow"

    principals {
      type = "AWS"

      identifiers = [
        "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
      ]
    }

    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:DescribeKey",
      "kms:CreateGrant"
    ]

    resources = ["*"]

    condition {
      test     = "StringLike"
      variable = "kms:ViaService"
      values   = ["dynamodb.ap-south-1.amazonaws.com"]
    }
  }
}

# CUSTOMER-MANAGED KMS KEY
resource "aws_kms_key" "application" {
  description             = "KMS key for encrypting application data in S3 and DynamoDB"
  enable_key_rotation     = true
  deletion_window_in_days = 7
  policy                  = data.aws_iam_policy_document.application_kms.json

  tags = {
    Name        = "cloudsec-application-kms-key"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}

# KMS KEY ALIAS
resource "aws_kms_alias" "application" {
  name          = "alias/cloudsec-application"
  target_key_id = aws_kms_key.application.key_id
}

# KMS OUTPUT
output "application_kms_key_arn" {
  description = "Customer-managed KMS key ARN for application data."
  value       = aws_kms_key.application.arn
}

data "aws_iam_policy_document" "application_logs_kms" {

  #checkov:skip=CKV_AWS_356:KMS key-policy Resource * refers only to this CloudWatch Logs key and does not grant access to every KMS key.

  #checkov:skip=CKV_AWS_109:Standard account-root delegation enables IAM authorization; effective key-administration permissions are separately governed by IAM.

  #checkov:skip=CKV_AWS_111:Standard KMS account-delegation statement; actual key usage is controlled through IAM permissions and the CloudWatch Logs encryption-context restriction.

  statement {
    sid    = "EnableIAMUserPermissions"
    effect = "Allow"

    principals {
      type = "AWS"

      identifiers = [
        "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:root"
      ]
    }

    actions   = ["kms:*"]
    resources = ["*"]
  }

  statement {
    sid    = "AllowCloudWatchLogsEncryption"
    effect = "Allow"

    principals {
      type = "Service"

      identifiers = [
        "logs.${data.aws_region.current.region}.amazonaws.com"
      ]
    }

    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:Describe*"
    ]

    resources = ["*"]

    condition {
      test     = "ArnEquals"
      variable = "kms:EncryptionContext:aws:logs:arn"

      values = [
        "arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/cloudsec-document-expiry",
        "arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/cloudsec-document-cleanup",
        "arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/cloudsec-document-finalization",
        "arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/cloudsec-jwks-sync",
        "arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/cloudsec-document-version-hygiene",
        "arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/apigateway/cloudsec-document-api",
      ]
    }
  }

  statement {
    sid    = "AllowDeploymentRoleToDescribeKey"
    effect = "Allow"

    principals {
      type = "AWS"

      identifiers = [
        "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:role/CloudSecurityProjectAdmin"
      ]
    }

    actions   = ["kms:DescribeKey"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"

      values = [
        "logs.${data.aws_region.current.region}.amazonaws.com"
      ]
    }
  }
}

# ============================================================
# APPLICATION CLOUDWATCH LOGGING KMS KEY
# ============================================================

resource "aws_kms_key" "application_logs" {
  description             = "KMS key for application Lambda CloudWatch logs"
  enable_key_rotation     = true
  deletion_window_in_days = 7

  policy = data.aws_iam_policy_document.application_logs_kms.json

  tags = {
    Name        = "cloudsec-application-logs-kms-key"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
    Purpose     = "Application log encryption"
  }
}

resource "aws_kms_alias" "application_logs" {
  name          = "alias/cloudsec-application-logs"
  target_key_id = aws_kms_key.application_logs.key_id
}

output "application_logs_kms_key_arn" {
  description = "Customer-managed KMS key ARN for application logs."
  value       = aws_kms_key.application_logs.arn
}
