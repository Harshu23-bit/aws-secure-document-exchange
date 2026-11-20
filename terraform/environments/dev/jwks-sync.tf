# ============================================================
# COGNITO JWKS METADATA STORAGE
# ============================================================

resource "aws_s3_bucket" "identity_metadata" {

  #checkov:skip=CKV_AWS_145:JWKS contains public signing keys; SSE-S3 provides encryption at rest without an unnecessary customer-managed KMS dependency.

  #checkov:skip=CKV_AWS_144:JWKS can be regenerated from Cognito; cross-region replication is not required by the current development DR objectives.

  #checkov:skip=CKV2_AWS_62:JWKS synchronization is initiated by EventBridge Scheduler and does not consume S3 event notifications.
  bucket_prefix = "cloudsec-identity-metadata-"

  force_destroy = false

  tags = {
    Name        = "cloudsec-identity-metadata"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
    Purpose     = "Cognito public JWKS metadata"
  }
}

resource "aws_s3_bucket_public_access_block" "identity_metadata" {
  bucket = aws_s3_bucket.identity_metadata.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "identity_metadata" {
  bucket = aws_s3_bucket.identity_metadata.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "identity_metadata" {
  bucket = aws_s3_bucket.identity_metadata.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "identity_metadata" {
  bucket = aws_s3_bucket.identity_metadata.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "identity_metadata" {
  bucket = aws_s3_bucket.identity_metadata.id

  rule {
    id     = "identity-metadata-version-retention"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# Enforce TLS for all bucket access.
data "aws_iam_policy_document" "identity_metadata" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "AWS"
      identifiers = ["*"]
    }

    actions = ["s3:*"]

    resources = [
      aws_s3_bucket.identity_metadata.arn,
      "${aws_s3_bucket.identity_metadata.arn}/*"
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "identity_metadata" {
  bucket = aws_s3_bucket.identity_metadata.id
  policy = data.aws_iam_policy_document.identity_metadata.json

  depends_on = [
    aws_s3_bucket_public_access_block.identity_metadata
  ]
}

# Store the object at:
# s3://<bucket>/security/jwks.json


# ============================================================
# LAMBDA LOG GROUP
# ============================================================

resource "aws_cloudwatch_log_group" "jwks_sync" {
  name              = "/aws/lambda/cloudsec-jwks-sync"
  kms_key_id        = aws_kms_key.application_logs.arn
  retention_in_days = 365

  tags = {
    Name        = "cloudsec-jwks-sync"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# JWKS LAMBDA FAILURE DESTINATION
# ============================================================

resource "aws_sqs_queue" "jwks_sync_failures" {
  name = "cloudsec-jwks-sync-failures"

  message_retention_seconds = 1209600

  sqs_managed_sse_enabled = true

  tags = {
    Name        = "cloudsec-jwks-sync-failures"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
    Purpose     = "Capture failed JWKS Lambda executions"
  }
}


# ============================================================
# LAMBDA EXECUTION ROLE
# ============================================================

resource "aws_iam_role" "jwks_sync_lambda" {
  name        = "cloudsec-jwks-sync-lambda-role"
  description = "Execution role for scheduled Cognito JWKS synchronization"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          Service = "lambda.amazonaws.com"
        }

        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name        = "cloudsec-jwks-sync-lambda-role"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# LAMBDA LEAST-PRIVILEGE POLICY
# ============================================================

resource "aws_iam_role_policy" "jwks_sync_lambda" {
  name = "cloudsec-jwks-sync-permissions"
  role = aws_iam_role.jwks_sync_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [

      # Allow checking for the JWKS object in its dedicated metadata bucket.
      {
        Sid      = "JWKSBucketList"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.identity_metadata.arn

        Condition = {
          StringLike = {
            "s3:prefix" = [
              "security/jwks.json"
            ]
          }
        }
      },

      # Read existing JWKS object and publish updates.
      {
        Sid    = "JWKSObjectAccess"
        Effect = "Allow"

        Action = [
          "s3:GetObject",
          "s3:PutObject"
        ]

        Resource = "${aws_s3_bucket.identity_metadata.arn}/security/jwks.json"
      },

      # Write logs to the Terraform-managed log group.
      {
        Sid    = "LambdaLogging"
        Effect = "Allow"

        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]

        Resource = "${aws_cloudwatch_log_group.jwks_sync.arn}:*"
      },

      # Publish only to the designated custom metric namespace.
      {
        Sid      = "JWKSHeartbeatMetric"
        Effect   = "Allow"
        Action   = "cloudwatch:PutMetricData"
        Resource = "*"

        Condition = {
          StringEquals = {
            "cloudwatch:namespace" = "CloudSec/JWKS"
          }
        }
      },

      # Send failed asynchronous invocation records to the DLQ.
      {
        Sid      = "SendFailureRecordsToSQS"
        Effect   = "Allow"
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.jwks_sync_failures.arn
      }
    ]
  })
}


# ============================================================
# EVENTBRIDGE SCHEDULER DELIVERY FAILURE QUEUE
# ============================================================

resource "aws_sqs_queue" "jwks_scheduler_failures" {
  name = "cloudsec-jwks-scheduler-failures"

  message_retention_seconds = 1209600

  sqs_managed_sse_enabled = true

  tags = {
    Name        = "cloudsec-jwks-scheduler-failures"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
    Purpose     = "Capture undelivered JWKS scheduled invocations"
  }
}


# ============================================================
# LAMBDA FUNCTION
# ============================================================

resource "aws_lambda_function" "jwks_sync" {

  #checkov:skip=CKV_AWS_116:Asynchronous invocation failure handling uses aws_lambda_function_event_invoke_config with an SQS on_failure destination; a legacy function-level DLQ is unnecessary.

  #checkov:skip=CKV_AWS_117:Scheduled AWS API workers intentionally run outside the VPC to avoid NAT Gateway and unnecessary VPC endpoint costs.

  #checkov:skip=CKV_AWS_173:Environment variables contain configuration identifiers only; no secrets are stored, and Lambda encrypts environment variables at rest by default.

  #checkov:skip=CKV_AWS_50:X-Ray tracing is deferred to control development costs; CloudWatch logs, metrics, and alarms provide current operational monitoring.

  function_name = "cloudsec-jwks-sync"
  description   = "Synchronizes Cognito public JWKS metadata to private S3 storage"

  role    = aws_iam_role.jwks_sync_lambda.arn
  runtime = "python3.12"
  handler = "handler.handler"

  s3_bucket         = aws_signer_signing_job.lambda_artifacts["jwks_sync"].signed_object[0].s3[0].bucket
  s3_key            = aws_signer_signing_job.lambda_artifacts["jwks_sync"].signed_object[0].s3[0].key
  s3_object_version = data.aws_s3_object.lambda_signed_artifacts["jwks_sync"].version_id

  source_code_hash = filebase64sha256(
    "${path.module}/../../../build/jwks_sync.zip"
  )

  code_signing_config_arn = aws_lambda_code_signing_config.application.arn

  architectures = ["x86_64"]

  timeout     = 30
  memory_size = 128

  reserved_concurrent_executions = 1

  environment {
    variables = {
      USER_POOL_ID     = aws_cognito_user_pool.application.id
      JWKS_BUCKET      = aws_s3_bucket.identity_metadata.id
      METRIC_NAMESPACE = "CloudSec/JWKS"
    }
  }

  depends_on = [
    aws_iam_role_policy.jwks_sync_lambda,
    aws_cloudwatch_log_group.jwks_sync
  ]

  tags = {
    Name        = "cloudsec-jwks-sync"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# LAMBDA ASYNCHRONOUS INVOCATION CONFIGURATION
# ============================================================

resource "aws_lambda_function_event_invoke_config" "jwks_sync" {
  function_name = aws_lambda_function.jwks_sync.function_name

  maximum_event_age_in_seconds = 3600
  maximum_retry_attempts       = 2

  destination_config {
    on_failure {
      destination = aws_sqs_queue.jwks_sync_failures.arn
    }
  }

  depends_on = [
    aws_iam_role_policy.jwks_sync_lambda
  ]
}


# ============================================================
# EVENTBRIDGE SCHEDULER EXECUTION ROLE
# ============================================================

resource "aws_iam_role" "jwks_scheduler" {
  name        = "cloudsec-jwks-scheduler-role"
  description = "Allows EventBridge Scheduler to invoke the JWKS Lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          Service = "scheduler.amazonaws.com"
        }

        Action = "sts:AssumeRole"

        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }

          ArnEquals = {
            "aws:SourceArn" = "arn:${data.aws_partition.current.partition}:scheduler:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:schedule-group/default"
          }
        }
      }
    ]
  })

  tags = {
    Name        = "cloudsec-jwks-scheduler-role"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}

resource "aws_iam_role_policy" "jwks_scheduler" {
  name = "cloudsec-jwks-scheduler-invoke"
  role = aws_iam_role.jwks_scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid      = "InvokeJWKSFunction"
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = aws_lambda_function.jwks_sync.arn
      },
      {
        Sid      = "SendSchedulerFailuresToDLQ"
        Effect   = "Allow"
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.jwks_scheduler_failures.arn
      }
    ]
  })
}


# ============================================================
# EVENTBRIDGE SCHEDULE
# ============================================================

resource "aws_scheduler_schedule" "jwks_sync" {

  #checkov:skip=CKV_AWS_297:Schedule targets contain no sensitive payload; AWS-owned encryption is sufficient, avoiding an unnecessary customer-managed KMS key.

  name        = "cloudsec-jwks-sync"
  description = "Synchronize Cognito JWKS metadata every hour"

  schedule_expression          = "cron(0 * * * ? *)"
  schedule_expression_timezone = "UTC"
  state                        = "ENABLED"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.jwks_sync.arn
    role_arn = aws_iam_role.jwks_scheduler.arn
    input    = "{}"

    dead_letter_config {
      arn = aws_sqs_queue.jwks_scheduler_failures.arn
    }

    retry_policy {
      maximum_event_age_in_seconds = 3600
      maximum_retry_attempts       = 2
    }
  }

  depends_on = [
    aws_iam_role_policy.jwks_scheduler
  ]
}


# ============================================================
# JWKS SYNCHRONIZATION FAILURE ALARM
# ============================================================

resource "aws_cloudwatch_metric_alarm" "jwks_sync_errors" {
  alarm_name        = "cloudsec-jwks-sync-errors"
  alarm_description = "The Cognito JWKS synchronization Lambda reported an execution error."

  namespace   = "AWS/Lambda"
  metric_name = "Errors"

  dimensions = {
    FunctionName = aws_lambda_function.jwks_sync.function_name
  }

  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  datapoints_to_alarm = 1

  threshold           = 0
  comparison_operator = "GreaterThanThreshold"

  treat_missing_data = "notBreaching"

  alarm_actions = [
    aws_sns_topic.security_alerts.arn
  ]

  tags = {
    Name        = "cloudsec-jwks-sync-errors"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# JWKS SYNCHRONIZATION - LAMBDA FAILURE QUEUE ALARM
# ============================================================

resource "aws_cloudwatch_metric_alarm" "jwks_sync_lambda_dlq" {
  alarm_name = "cloudsec-jwks-sync-lambda-dlq"

  alarm_description = "Failed JWKS synchronization Lambda executions are waiting in the failure destination queue."

  namespace   = "AWS/SQS"
  metric_name = "ApproximateNumberOfMessagesVisible"

  dimensions = {
    QueueName = aws_sqs_queue.jwks_sync_failures.name
  }

  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  datapoints_to_alarm = 1

  threshold           = 0
  comparison_operator = "GreaterThanThreshold"

  treat_missing_data = "notBreaching"

  alarm_actions = [
    aws_sns_topic.security_alerts.arn
  ]

  tags = {
    Name        = "cloudsec-jwks-sync-lambda-dlq"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}

# ============================================================
# EVENTBRIDGE SCHEDULER DELIVERY FAILURE ALARM
# ============================================================

resource "aws_cloudwatch_metric_alarm" "jwks_scheduler_dlq_messages" {
  alarm_name = "cloudsec-jwks-scheduler-dlq-messages"

  alarm_description = "One or more JWKS scheduled invocations could not be delivered and were sent to the Scheduler dead-letter queue."

  namespace   = "AWS/SQS"
  metric_name = "ApproximateNumberOfMessagesVisible"

  dimensions = {
    QueueName = aws_sqs_queue.jwks_scheduler_failures.name
  }

  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  datapoints_to_alarm = 1

  threshold           = 0
  comparison_operator = "GreaterThanThreshold"

  treat_missing_data = "notBreaching"

  alarm_actions = [
    aws_sns_topic.security_alerts.arn
  ]

  tags = {
    Name        = "cloudsec-jwks-scheduler-dlq-messages"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# JWKS HEARTBEAT / STALE SYNCHRONIZATION ALARM
# ============================================================

resource "aws_cloudwatch_metric_alarm" "jwks_stale" {
  alarm_name = "cloudsec-jwks-stale"

  alarm_description = "No successful Cognito JWKS synchronization heartbeat was received for two consecutive hourly periods."

  namespace   = "CloudSec/JWKS"
  metric_name = "SyncSuccess"

  dimensions = {
    UserPoolId = aws_cognito_user_pool.application.id
  }

  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 2
  datapoints_to_alarm = 2

  threshold           = 1
  comparison_operator = "LessThanThreshold"

  treat_missing_data = "breaching"

  alarm_actions = [
    aws_sns_topic.security_alerts.arn
  ]

  tags = {
    Name        = "cloudsec-jwks-stale"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# OUTPUTS
# ============================================================

output "jwks_metadata_bucket_name" {
  description = "Private S3 bucket containing the synchronized Cognito JWKS."
  value       = aws_s3_bucket.identity_metadata.id
}

output "jwks_metadata_object_arn" {
  description = "Exact S3 object ARN containing the Cognito JWKS."
  value       = "${aws_s3_bucket.identity_metadata.arn}/security/jwks.json"
}

output "jwks_sync_lambda_arn" {
  description = "ARN of the scheduled Cognito JWKS synchronization Lambda."
  value       = aws_lambda_function.jwks_sync.arn
}

output "jwks_scheduler_dlq_arn" {
  description = "ARN of the EventBridge Scheduler delivery failure queue."
  value       = aws_sqs_queue.jwks_scheduler_failures.arn
}
