# ==========================================
# CLOUDTRAIL DELIVERY NOTIFICATION SNS TOPIC
# ==========================================

resource "aws_sns_topic" "cloudtrail" {
  name              = local.cloudtrail_sns_topic_name
  display_name      = "CloudTrail Delivery Notifications"
  kms_master_key_id = aws_kms_key.cloudtrail.arn

  tags = {
    Name        = local.cloudtrail_sns_topic_name
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
    Purpose     = "CloudTrail Log Delivery Notifications"
  }
}

# ==========================================
# CLOUDTRAIL SNS ACCESS POLICY
# ==========================================

data "aws_iam_policy_document" "cloudtrail_sns" {
  statement {
    sid    = "AllowCloudTrailToPublishNotifications"
    effect = "Allow"

    actions = [
      "sns:Publish"
    ]

    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }

    resources = [
      aws_sns_topic.cloudtrail.arn
    ]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = [local.cloudtrail_trail_arn]
    }
  }
}

resource "aws_sns_topic_policy" "cloudtrail" {
  arn    = aws_sns_topic.cloudtrail.arn
  policy = data.aws_iam_policy_document.cloudtrail_sns.json
}

# ==========================================
# OPTIONAL EMAIL SUBSCRIPTION
# ==========================================

resource "aws_sns_topic_subscription" "cloudtrail_delivery_email" {
  count = var.cloudtrail_delivery_email == null ? 0 : 1

  topic_arn = aws_sns_topic.cloudtrail.arn
  protocol  = "email"
  endpoint  = var.cloudtrail_delivery_email
}

# ==========================================
# OUTPUT
# ==========================================

output "cloudtrail_sns_topic_arn" {
  description = "ARN of the encrypted CloudTrail delivery notification SNS topic."
  value       = aws_sns_topic.cloudtrail.arn
}
