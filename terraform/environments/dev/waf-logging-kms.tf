# ==========================================
# WAF LOGGING KMS KEY POLICY
# ==========================================

data "aws_iam_policy_document" "waf_logs" {

  #checkov:skip=CKV_AWS_356:KMS key-policy Resource * refers to this individual key; service permissions are restricted by principal and encryption context.

  #checkov:skip=CKV_AWS_109:Standard KMS account delegation and CloudWatch Logs service permissions are required; service access is restricted to the designated log group.

  #checkov:skip=CKV_AWS_111:CloudWatch Logs permissions are scoped through the log-group encryption context and deployment permissions through kms:ViaService.

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

  # Allow regional CloudWatch Logs to use the key for WAF log encryption.
  statement {
    sid    = "AllowCloudWatchLogsToUseKey"
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
        "arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:aws-waf-logs-cloudsec-application"
      ]
    }
  }

  # Allow the Terraform deployment role to associate this key
  # with the WAF CloudWatch Logs group.
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

      values = [
        "logs.${data.aws_region.current.region}.amazonaws.com"
      ]
    }
  }
}

# ==========================================
# WAF LOGGING CUSTOMER-MANAGED KMS KEY
# ==========================================

resource "aws_kms_key" "waf_logs" {
  description             = "KMS key for encrypting AWS WAF CloudWatch logs"
  enable_key_rotation     = true
  deletion_window_in_days = 7
  policy                  = data.aws_iam_policy_document.waf_logs.json

  tags = {
    Name        = "cloudsec-waf-logs-key"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}

# ==========================================
# WAF LOGGING KMS ALIAS
# ==========================================

resource "aws_kms_alias" "waf_logs" {
  name          = "alias/cloudsec-waf-logs"
  target_key_id = aws_kms_key.waf_logs.key_id
}
