# ============================================================
# DOCUMENT CLEANUP - CLOUDWATCH LOG GROUP
# ============================================================

resource "aws_cloudwatch_log_group" "document_cleanup" {
  name              = "/aws/lambda/cloudsec-document-cleanup"
  kms_key_id        = aws_kms_key.application_logs.arn
  retention_in_days = 365

  tags = {
    Name        = "cloudsec-document-cleanup"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
    Purpose     = "Delete expired S3 document versions"
  }
}


# ============================================================
# DOCUMENT CLEANUP - FAILURE QUEUES
# ============================================================

resource "aws_sqs_queue" "document_cleanup_lambda_failures" {
  name                      = "cloudsec-document-cleanup-lambda-failures"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true

  tags = {
    Name        = "cloudsec-document-cleanup-lambda-failures"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}

resource "aws_sqs_queue" "document_cleanup_scheduler_dlq" {
  name                      = "cloudsec-document-cleanup-scheduler-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true

  tags = {
    Name        = "cloudsec-document-cleanup-scheduler-dlq"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# DOCUMENT CLEANUP - LAMBDA EXECUTION ROLE
# ============================================================

resource "aws_iam_role" "document_cleanup_lambda" {
  name        = "cloudsec-document-cleanup-lambda-role"
  description = "Execution role for S3 document version cleanup"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [{
      Effect = "Allow"

      Principal = {
        Service = "lambda.amazonaws.com"
      }

      Action = "sts:AssumeRole"
    }]
  })

  tags = {
    Name        = "cloudsec-document-cleanup-lambda-role"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# DOCUMENT CLEANUP - LEAST-PRIVILEGE IAM POLICY
# ============================================================

resource "aws_iam_role_policy" "document_cleanup_lambda" {
  name = "cloudsec-document-cleanup-permissions"
  role = aws_iam_role.document_cleanup_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid      = "QueryPendingDocumentCleanupIndex"
        Effect   = "Allow"
        Action   = "dynamodb:Query"
        Resource = "${aws_dynamodb_table.submissions.arn}/index/PendingDocumentCleanupIndex"
      },
      {
        Sid      = "UpdateDocumentCleanupState"
        Effect   = "Allow"
        Action   = "dynamodb:UpdateItem"
        Resource = aws_dynamodb_table.submissions.arn
      },
      {
        Sid    = "ListTenantObjectVersions"
        Effect = "Allow"

        Action = [
          "s3:ListBucketVersions"
        ]

        Resource = aws_s3_bucket.application.arn

        Condition = {
          StringLike = {
            "s3:prefix" = [
              "tenants/*"
            ]
          }
        }
      },
      {
        Sid    = "DeleteTenantObjectVersions"
        Effect = "Allow"

        Action = [
          "s3:DeleteObjectVersion"
        ]

        Resource = "${aws_s3_bucket.application.arn}/tenants/*"
      },
      {
        Sid    = "LambdaLogging"
        Effect = "Allow"

        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]

        Resource = "${aws_cloudwatch_log_group.document_cleanup.arn}:*"
      },
      {
        Sid      = "SendLambdaFailureRecordsToSQS"
        Effect   = "Allow"
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.document_cleanup_lambda_failures.arn
      }
    ]
  })
}


# ============================================================
# DOCUMENT CLEANUP - LAMBDA FUNCTION
# ============================================================

resource "aws_lambda_function" "document_cleanup" {

  #checkov:skip=CKV_AWS_116:Asynchronous invocation failure handling uses aws_lambda_function_event_invoke_config with an SQS on_failure destination; a legacy function-level DLQ is unnecessary.

  #checkov:skip=CKV_AWS_117:Scheduled AWS API workers intentionally run outside the VPC to avoid NAT Gateway and unnecessary VPC endpoint costs.

  #checkov:skip=CKV_AWS_173:Environment variables contain configuration identifiers only; no secrets are stored, and Lambda encrypts environment variables at rest by default.

  #checkov:skip=CKV_AWS_50:X-Ray tracing is deferred to control development costs; CloudWatch logs, metrics, and alarms provide current operational monitoring.

  function_name = "cloudsec-document-cleanup"

  description = "Deletes expired S3 document versions and verifies object removal"

  role    = aws_iam_role.document_cleanup_lambda.arn
  runtime = "python3.12"
  handler = "handler.handler"

  s3_bucket         = aws_signer_signing_job.lambda_artifacts["document_cleanup"].signed_object[0].s3[0].bucket
  s3_key            = aws_signer_signing_job.lambda_artifacts["document_cleanup"].signed_object[0].s3[0].key
  s3_object_version = data.aws_s3_object.lambda_signed_artifacts["document_cleanup"].version_id

  source_code_hash = filebase64sha256(
    "${path.module}/../../../build/document_cleanup.zip"
  )

  code_signing_config_arn = aws_lambda_code_signing_config.application.arn

  architectures = ["x86_64"]

  timeout                        = 300
  memory_size                    = 128
  reserved_concurrent_executions = 1

  environment {
    variables = {
      TABLE_NAME    = aws_dynamodb_table.submissions.name
      CLEANUP_INDEX = "PendingDocumentCleanupIndex"
      BUCKET_NAME   = aws_s3_bucket.application.id
      SHARD_COUNT   = "4"
      MAX_ITEMS     = "50"
      LOG_LEVEL     = "INFO"
    }
  }

  depends_on = [
    aws_iam_role_policy.document_cleanup_lambda,
    aws_cloudwatch_log_group.document_cleanup
  ]

  tags = {
    Name        = "cloudsec-document-cleanup"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# DOCUMENT CLEANUP - ASYNCHRONOUS INVOCATION
# ============================================================

resource "aws_lambda_function_event_invoke_config" "document_cleanup" {
  function_name = aws_lambda_function.document_cleanup.function_name

  maximum_event_age_in_seconds = 3600
  maximum_retry_attempts       = 2

  destination_config {
    on_failure {
      destination = aws_sqs_queue.document_cleanup_lambda_failures.arn
    }
  }
}


# ============================================================
# DOCUMENT CLEANUP - SCHEDULER ROLE
# ============================================================

resource "aws_iam_role" "document_cleanup_scheduler" {
  name        = "cloudsec-document-cleanup-scheduler-role"
  description = "Allows EventBridge Scheduler to invoke document cleanup"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [{
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
    }]
  })

  tags = {
    Name        = "cloudsec-document-cleanup-scheduler-role"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# DOCUMENT CLEANUP - SCHEDULER PERMISSIONS
# ============================================================

resource "aws_iam_role_policy" "document_cleanup_scheduler" {
  name = "cloudsec-document-cleanup-scheduler-invoke"
  role = aws_iam_role.document_cleanup_scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid      = "InvokeDocumentCleanupLambda"
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = aws_lambda_function.document_cleanup.arn
      },
      {
        Sid      = "SendSchedulerFailuresToSQS"
        Effect   = "Allow"
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.document_cleanup_scheduler_dlq.arn
      }
    ]
  })
}


# ============================================================
# DOCUMENT CLEANUP - EVENTBRIDGE SCHEDULE
# ============================================================

resource "aws_scheduler_schedule" "document_cleanup" {

  #checkov:skip=CKV_AWS_297:Schedule targets contain no sensitive payload; AWS-owned encryption is sufficient, avoiding an unnecessary customer-managed KMS key.

  name        = "cloudsec-document-cleanup"
  description = "Process pending S3 document cleanup every 15 minutes"

  schedule_expression          = "rate(15 minutes)"
  schedule_expression_timezone = "UTC"
  state                        = "ENABLED"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.document_cleanup.arn
    role_arn = aws_iam_role.document_cleanup_scheduler.arn
    input    = "{}"

    dead_letter_config {
      arn = aws_sqs_queue.document_cleanup_scheduler_dlq.arn
    }

    retry_policy {
      maximum_event_age_in_seconds = 3600
      maximum_retry_attempts       = 2
    }
  }

  depends_on = [
    aws_iam_role_policy.document_cleanup_scheduler
  ]
}


# ============================================================
# DOCUMENT CLEANUP - LAMBDA ERROR ALARM
# ============================================================

resource "aws_cloudwatch_metric_alarm" "document_cleanup_errors" {
  alarm_name        = "cloudsec-document-cleanup-errors"
  alarm_description = "The document cleanup Lambda reported an execution error."

  namespace   = "AWS/Lambda"
  metric_name = "Errors"

  dimensions = {
    FunctionName = aws_lambda_function.document_cleanup.function_name
  }

  statistic           = "Sum"
  period              = 900
  evaluation_periods  = 1
  datapoints_to_alarm = 1

  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = [
    aws_sns_topic.security_alerts.arn
  ]

  tags = {
    Name        = "cloudsec-document-cleanup-errors"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# DOCUMENT CLEANUP - LAMBDA DLQ ALARM
# ============================================================

resource "aws_cloudwatch_metric_alarm" "document_cleanup_lambda_dlq" {
  alarm_name        = "cloudsec-document-cleanup-lambda-dlq"
  alarm_description = "Failed document cleanup Lambda executions are waiting in the failure queue."

  namespace   = "AWS/SQS"
  metric_name = "ApproximateNumberOfMessagesVisible"

  dimensions = {
    QueueName = aws_sqs_queue.document_cleanup_lambda_failures.name
  }

  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  datapoints_to_alarm = 1

  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = [
    aws_sns_topic.security_alerts.arn
  ]

  tags = {
    Name        = "cloudsec-document-cleanup-lambda-dlq"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# DOCUMENT CLEANUP - SCHEDULER DLQ ALARM
# ============================================================

resource "aws_cloudwatch_metric_alarm" "document_cleanup_scheduler_dlq" {
  alarm_name        = "cloudsec-document-cleanup-scheduler-dlq"
  alarm_description = "Failed Scheduler deliveries are waiting in the cleanup Scheduler DLQ."

  namespace   = "AWS/SQS"
  metric_name = "ApproximateNumberOfMessagesVisible"

  dimensions = {
    QueueName = aws_sqs_queue.document_cleanup_scheduler_dlq.name
  }

  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  datapoints_to_alarm = 1

  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = [
    aws_sns_topic.security_alerts.arn
  ]

  tags = {
    Name        = "cloudsec-document-cleanup-scheduler-dlq"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# OUTPUTS
# ============================================================

output "document_cleanup_lambda_arn" {
  description = "ARN of the S3 document version cleanup Lambda."
  value       = aws_lambda_function.document_cleanup.arn
}

output "document_cleanup_scheduler_dlq_arn" {
  description = "ARN of the document cleanup Scheduler DLQ."
  value       = aws_sqs_queue.document_cleanup_scheduler_dlq.arn
}
