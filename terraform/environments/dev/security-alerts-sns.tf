# ==========================================
# SECURITY ALERTS LOCALS
# ==========================================

locals {
  security_alerts_topic_name = "cloudsec-security-alerts"

  security_alarm_arn_pattern = "arn:${data.aws_partition.current.partition}:cloudwatch:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:alarm:cloudsec-*"
}

# ==========================================
# ENCRYPTED SECURITY ALERTS SNS TOPIC
# ==========================================

resource "aws_sns_topic" "security_alerts" {
  name              = local.security_alerts_topic_name
  display_name      = "Cloud Security Alerts"
  kms_master_key_id = aws_kms_key.cloudtrail.arn

  tags = {
    Name        = local.security_alerts_topic_name
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
    Purpose     = "Cloud Security Alert Notifications"
  }
}

# ==========================================
# SECURITY ALERTS SNS TOPIC POLICY
# ==========================================

data "aws_iam_policy_document" "security_alerts_sns" {

  statement {
    sid    = "AllowCloudWatchAlarmsToPublish"
    effect = "Allow"

    actions = [
      "sns:Publish"
    ]

    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }

    resources = [
      aws_sns_topic.security_alerts.arn
    ]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"

      values = [
        data.aws_caller_identity.current.account_id
      ]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"

      values = [
        local.security_alarm_arn_pattern
      ]
    }
  }
}

resource "aws_sns_topic_policy" "security_alerts" {
  arn    = aws_sns_topic.security_alerts.arn
  policy = data.aws_iam_policy_document.security_alerts_sns.json
}

# ==========================================
# OPTIONAL EMAIL SUBSCRIPTION
# ==========================================

resource "aws_sns_topic_subscription" "security_alerts_email" {
  count = var.security_alert_email == null ? 0 : 1

  topic_arn = aws_sns_topic.security_alerts.arn
  protocol  = "email"
  endpoint  = var.security_alert_email
}

# ==========================================
# OUTPUTS
# ==========================================

output "security_alerts_sns_topic_arn" {
  description = "Encrypted SNS topic ARN for CloudTrail security alerts."
  value       = aws_sns_topic.security_alerts.arn
}
