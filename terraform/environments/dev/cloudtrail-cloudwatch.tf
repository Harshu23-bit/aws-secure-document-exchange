# ==========================================
# CLOUDTRAIL CLOUDWATCH LOG GROUP
# ==========================================

resource "aws_cloudwatch_log_group" "cloudtrail" {
  name              = local.cloudtrail_log_group_name
  retention_in_days = 365
  kms_key_id        = aws_kms_key.cloudtrail.arn

  tags = {
    Name        = "cloudsec-cloudtrail-logs"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
    Purpose     = "Centralized CloudTrail Audit Events"
  }
}

# ==========================================
# CLOUDTRAIL CLOUDWATCH DELIVERY POLICY
# ==========================================

data "aws_iam_policy_document" "cloudtrail_cloudwatch" {

  statement {
    sid    = "AllowCreateCloudTrailLogStreams"
    effect = "Allow"

    actions = [
      "logs:CreateLogStream"
    ]

    resources = [
      "${local.cloudtrail_log_group_arn}:log-stream:${data.aws_caller_identity.current.account_id}_CloudTrail_*"
    ]
  }

  statement {
    sid    = "AllowPublishCloudTrailEvents"
    effect = "Allow"

    actions = [
      "logs:PutLogEvents"
    ]

    resources = [
      "${local.cloudtrail_log_group_arn}:log-stream:${data.aws_caller_identity.current.account_id}_CloudTrail_*"
    ]
  }
}

# ==========================================
# ATTACH DELIVERY POLICY TO IAM ROLE
# ==========================================

resource "aws_iam_role_policy" "cloudtrail_cloudwatch" {
  name   = "CloudTrailCloudWatchLogsDeliveryPolicy"
  role   = aws_iam_role.cloudtrail_cloudwatch.id
  policy = data.aws_iam_policy_document.cloudtrail_cloudwatch.json
}
