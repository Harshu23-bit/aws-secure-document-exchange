# ==========================================
# CLOUDTRAIL LOCALS
# ==========================================

locals {
  cloudtrail_name = "cloudsec-account-audit-trail"

  cloudtrail_log_group_name = "/aws/cloudtrail/cloudsec-account-audit-trail"

  cloudtrail_sns_topic_name = "cloudsec-cloudtrail-delivery-notifications"

  cloudtrail_trail_arn = "arn:${data.aws_partition.current.partition}:cloudtrail:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:trail/${local.cloudtrail_name}"

  cloudtrail_log_group_arn = "arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:${local.cloudtrail_log_group_name}"
}

# ==========================================
# CLOUDTRAIL IAM TRUST POLICY
# ==========================================

data "aws_iam_policy_document" "cloudtrail_assume_role" {
  statement {
    sid     = "AllowCloudTrailAssumeRole"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [local.cloudtrail_trail_arn]
    }
  }
}

# ==========================================
# CLOUDTRAIL IAM ROLE
# ==========================================

resource "aws_iam_role" "cloudtrail_cloudwatch" {
  name               = "CloudTrailCloudWatchLogsRole"
  description        = "Allows CloudTrail to publish audit events to its CloudWatch Logs group."
  assume_role_policy = data.aws_iam_policy_document.cloudtrail_assume_role.json

  tags = {
    Name        = "cloudsec-cloudtrail-cloudwatch-role"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}

# ==========================================
# CLOUDTRAIL
# ==========================================

resource "aws_cloudtrail" "account" {
  name                       = local.cloudtrail_name
  s3_bucket_name             = aws_s3_bucket.cloudtrail.id
  cloud_watch_logs_group_arn = "${aws_cloudwatch_log_group.cloudtrail.arn}:*"
  cloud_watch_logs_role_arn  = aws_iam_role.cloudtrail_cloudwatch.arn
  kms_key_id                 = aws_kms_key.cloudtrail.arn

  sns_topic_name = aws_sns_topic.cloudtrail.name

  enable_logging                = true
  enable_log_file_validation    = true
  include_global_service_events = true
  is_multi_region_trail         = true
  is_organization_trail         = false

  event_selector {
    include_management_events = true
    read_write_type           = "All"
  }

  tags = {
    Name        = "cloudsec-account-audit-trail"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
    Purpose     = "Multi-region Account Audit Logging"
  }

  depends_on = [
    aws_s3_bucket_policy.cloudtrail,
    aws_iam_role_policy.cloudtrail_cloudwatch,
    aws_sns_topic_policy.cloudtrail
  ]
}

# ==========================================
# OUTPUTS
# ==========================================

output "cloudtrail_trail_arn" {
  description = "ARN of the multi-region CloudTrail audit trail."
  value       = aws_cloudtrail.account.arn
}

output "cloudtrail_cloudwatch_role_arn" {
  description = "IAM role used by CloudTrail to publish events to CloudWatch Logs."
  value       = aws_iam_role.cloudtrail_cloudwatch.arn
}
