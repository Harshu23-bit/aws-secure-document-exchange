# ==========================================
# CLOUDTRAIL KMS KEY POLICY
# ==========================================

data "aws_iam_policy_document" "cloudtrail_kms" {

  #checkov:skip=CKV_AWS_356:KMS key-policy Resource * refers to the individual key; service permissions are scoped by principals and conditions.

  #checkov:skip=CKV_AWS_109:KMS account delegation and AWS service permissions follow documented KMS integration requirements; no unrestricted cross-key access is granted.

  #checkov:skip=CKV_AWS_111:KMS key-policy permissions are scoped to this key; CloudTrail and CloudWatch service permissions use their required encryption and source conditions.

  # Allow account-level IAM delegation.
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

  # Allow CloudTrail to encrypt audit log files.
  statement {
    sid    = "AllowCloudTrailEncryptLogs"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }

    actions = [
      "kms:GenerateDataKey*"
    ]

    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = [local.cloudtrail_trail_arn]
    }

    condition {
      test     = "StringLike"
      variable = "kms:EncryptionContext:aws:cloudtrail:arn"

      values = [
        "arn:${data.aws_partition.current.partition}:cloudtrail:*:${data.aws_caller_identity.current.account_id}:trail/*"
      ]
    }
  }

  # Allow CloudTrail to describe the encryption key.
  statement {
    sid    = "AllowCloudTrailDescribeKey"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }

    actions = [
      "kms:DescribeKey"
    ]

    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = [local.cloudtrail_trail_arn]
    }
  }

  # Allow CloudTrail to publish notifications to an encrypted SNS topic.
  statement {
    sid    = "AllowCloudTrailToUseKMSForSNS"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }

    actions = [
      "kms:GenerateDataKey*",
      "kms:Decrypt"
    ]

    resources = ["*"]
  }

  # Allow CloudWatch Logs to encrypt the CloudTrail log group.
  statement {
    sid    = "AllowCloudWatchLogsEncryption"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["logs.${data.aws_region.current.region}.amazonaws.com"]
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
      values   = [local.cloudtrail_log_group_arn]
    }
  }

  # Allow the Terraform deployment role to associate this key
  # with the CloudTrail CloudWatch Logs group.
  statement {
    sid    = "AllowCloudSecurityProjectAdminDescribeKey"
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
      values   = ["logs.${data.aws_region.current.region}.amazonaws.com"]
    }
  }

  # Allow CloudWatch alarms to publish to the encrypted security-alert SNS topic.
  statement {
    sid    = "AllowCloudWatchAlarmsToPublishToEncryptedSNS"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }

    actions = [
      "kms:GenerateDataKey*",
      "kms:Decrypt"
    ]

    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = [local.security_alarm_arn_pattern]
    }
  }
}

# ==========================================
# CLOUDTRAIL CUSTOMER-MANAGED KMS KEY
# ==========================================

resource "aws_kms_key" "cloudtrail" {
  description             = "Customer-managed KMS key for CloudTrail audit logs, CloudWatch Logs and SNS notifications"
  enable_key_rotation     = true
  deletion_window_in_days = 7
  policy                  = data.aws_iam_policy_document.cloudtrail_kms.json

  tags = {
    Name        = "cloudsec-cloudtrail-kms-key"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
    Purpose     = "CloudTrail and CloudWatch Audit Log Encryption"
  }
}

# ==========================================
# CLOUDTRAIL KMS ALIAS
# ==========================================

resource "aws_kms_alias" "cloudtrail" {
  name          = "alias/cloudsec-cloudtrail"
  target_key_id = aws_kms_key.cloudtrail.key_id
}

# ==========================================
# OUTPUT
# ==========================================

output "cloudtrail_kms_key_arn" {
  description = "Customer-managed KMS key ARN for CloudTrail, CloudWatch Logs and SNS notifications."
  value       = aws_kms_key.cloudtrail.arn
}
