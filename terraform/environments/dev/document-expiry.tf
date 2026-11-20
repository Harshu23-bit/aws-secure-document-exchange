# ============================================================
# DOCUMENT EXPIRY CLEANUP - LOG GROUP
# ============================================================

resource "aws_cloudwatch_log_group" "document_expiry" {
  name              = "/aws/lambda/cloudsec-document-expiry"
  kms_key_id        = aws_kms_key.application_logs.arn
  retention_in_days = 365

  tags = {
    Name        = "cloudsec-document-expiry"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
    Purpose     = "Pending document upload cleanup"
  }
}


# ============================================================
# DOCUMENT EXPIRY CLEANUP - FAILURE QUEUES
# ============================================================

# Captures failed asynchronous Lambda executions after retries.

resource "aws_sqs_queue" "document_expiry_lambda_failures" {
  name = "cloudsec-document-expiry-lambda-failures"

  message_retention_seconds = 1209600

  sqs_managed_sse_enabled = true

  tags = {
    Name        = "cloudsec-document-expiry-lambda-failures"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
    Purpose     = "Capture failed document expiry Lambda executions"
  }
}


# Captures events Scheduler cannot successfully deliver to Lambda.

resource "aws_sqs_queue" "document_expiry_scheduler_dlq" {
  name = "cloudsec-document-expiry-scheduler-dlq"

  message_retention_seconds = 1209600

  sqs_managed_sse_enabled = true

  tags = {
    Name        = "cloudsec-document-expiry-scheduler-dlq"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
    Purpose     = "Capture failed document expiry Scheduler deliveries"
  }
}


# ============================================================
# DOCUMENT EXPIRY CLEANUP - EXECUTION ROLE
# ============================================================

resource "aws_iam_role" "document_expiry_lambda" {
  name        = "cloudsec-document-expiry-lambda-role"
  description = "Execution role for pending document upload cleanup"

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
    Name        = "cloudsec-document-expiry-lambda-role"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# DOCUMENT EXPIRY CLEANUP - IAM PERMISSIONS
# ============================================================

resource "aws_iam_role_policy" "document_expiry_lambda" {
  name = "cloudsec-document-expiry-permissions"
  role = aws_iam_role.document_expiry_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [

      # Query only the dedicated expiry index.
      {
        Sid    = "QueryPendingDocumentExpiryIndex"
        Effect = "Allow"

        Action = [
          "dynamodb:Query"
        ]

        Resource = "${aws_dynamodb_table.submissions.arn}/index/PendingDocumentExpiryIndex"
      },

      # Perform atomic cleanup transactions on the submissions table.
      {
        Sid    = "ReconcileExpiredDocumentCounters"
        Effect = "Allow"

        Action = [
          "dynamodb:TransactWriteItems"
        ]

        Resource = aws_dynamodb_table.submissions.arn
      },

      # Write logs to the dedicated CloudWatch log group.
      {
        Sid    = "LambdaLogging"
        Effect = "Allow"

        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]

        Resource = "${aws_cloudwatch_log_group.document_expiry.arn}:*"
      },

      # Send failed asynchronous invocation records to the Lambda failure queue.
      {
        Sid      = "SendLambdaFailureRecordsToSQS"
        Effect   = "Allow"
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.document_expiry_lambda_failures.arn
      }
    ]
  })
}


# ============================================================
# DOCUMENT EXPIRY CLEANUP - LAMBDA
# ============================================================

resource "aws_lambda_function" "document_expiry" {

  #checkov:skip=CKV_AWS_116:Asynchronous invocation failure handling uses aws_lambda_function_event_invoke_config with an SQS on_failure destination; a legacy function-level DLQ is unnecessary.

  #checkov:skip=CKV_AWS_117:Scheduled AWS API workers intentionally run outside the VPC to avoid NAT Gateway and unnecessary VPC endpoint costs.

  #checkov:skip=CKV_AWS_173:Environment variables contain configuration identifiers only; no secrets are stored, and Lambda encrypts environment variables at rest by default.

  #checkov:skip=CKV_AWS_50:X-Ray tracing is deferred to control development costs; CloudWatch logs, metrics, and alarms provide current operational monitoring.

  function_name = "cloudsec-document-expiry"

  description = "Expires abandoned pending document uploads and reconciles submission quotas"

  role    = aws_iam_role.document_expiry_lambda.arn
  runtime = "python3.12"
  handler = "handler.handler"

  s3_bucket         = aws_signer_signing_job.lambda_artifacts["document_expiry"].signed_object[0].s3[0].bucket
  s3_key            = aws_signer_signing_job.lambda_artifacts["document_expiry"].signed_object[0].s3[0].key
  s3_object_version = data.aws_s3_object.lambda_signed_artifacts["document_expiry"].version_id

  source_code_hash = filebase64sha256(
    "${path.module}/../../../build/document_expiry.zip"
  )

  code_signing_config_arn = aws_lambda_code_signing_config.application.arn

  architectures = ["x86_64"]

  timeout                        = 60
  memory_size                    = 128
  reserved_concurrent_executions = 1

  environment {
    variables = {
      TABLE_NAME   = aws_dynamodb_table.submissions.name
      EXPIRY_INDEX = "PendingDocumentExpiryIndex"
      SHARD_COUNT  = "4"
      MAX_ITEMS    = "100"
      LOG_LEVEL    = "INFO"
    }
  }

  depends_on = [
    aws_iam_role_policy.document_expiry_lambda,
    aws_cloudwatch_log_group.document_expiry
  ]

  tags = {
    Name        = "cloudsec-document-expiry"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# DOCUMENT EXPIRY CLEANUP - ASYNCHRONOUS INVOCATION
# ============================================================

resource "aws_lambda_function_event_invoke_config" "document_expiry" {
  function_name = aws_lambda_function.document_expiry.function_name

  maximum_event_age_in_seconds = 3600
  maximum_retry_attempts       = 2

  destination_config {
    on_failure {
      destination = aws_sqs_queue.document_expiry_lambda_failures.arn
    }
  }

  depends_on = [
    aws_iam_role_policy.document_expiry_lambda
  ]
}


# ============================================================
# DOCUMENT EXPIRY CLEANUP - SCHEDULER ROLE
# ============================================================

resource "aws_iam_role" "document_expiry_scheduler" {
  name        = "cloudsec-document-expiry-scheduler-role"
  description = "Allows EventBridge Scheduler to invoke document expiry cleanup"

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
    Name        = "cloudsec-document-expiry-scheduler-role"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# DOCUMENT EXPIRY CLEANUP - SCHEDULER PERMISSIONS
# ============================================================

resource "aws_iam_role_policy" "document_expiry_scheduler" {
  name = "cloudsec-document-expiry-scheduler-invoke"
  role = aws_iam_role.document_expiry_scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [

      # Invoke only the document expiry Lambda.
      {
        Sid      = "InvokeDocumentExpiryLambda"
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = aws_lambda_function.document_expiry.arn
      },

      # Send failed Scheduler deliveries to the dedicated DLQ.
      {
        Sid      = "SendSchedulerFailuresToSQS"
        Effect   = "Allow"
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.document_expiry_scheduler_dlq.arn
      }
    ]
  })
}


# ============================================================
# DOCUMENT EXPIRY CLEANUP - EVENTBRIDGE SCHEDULE
# ============================================================

resource "aws_scheduler_schedule" "document_expiry" {

  #checkov:skip=CKV_AWS_297:Schedule targets contain no sensitive payload; AWS-owned encryption is sufficient, avoiding an unnecessary customer-managed KMS key.

  name        = "cloudsec-document-expiry"
  description = "Clean up expired pending document uploads every 15 minutes"

  schedule_expression          = "rate(15 minutes)"
  schedule_expression_timezone = "UTC"
  state                        = "ENABLED"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.document_expiry.arn
    role_arn = aws_iam_role.document_expiry_scheduler.arn
    input    = "{}"

    dead_letter_config {
      arn = aws_sqs_queue.document_expiry_scheduler_dlq.arn
    }

    retry_policy {
      maximum_event_age_in_seconds = 3600
      maximum_retry_attempts       = 2
    }
  }

  depends_on = [
    aws_iam_role_policy.document_expiry_scheduler
  ]
}


# ============================================================
# DOCUMENT EXPIRY CLEANUP - ERROR ALARM
# ============================================================

resource "aws_cloudwatch_metric_alarm" "document_expiry_errors" {
  alarm_name = "cloudsec-document-expiry-errors"

  alarm_description = "The document expiry cleanup Lambda reported an execution error."

  namespace   = "AWS/Lambda"
  metric_name = "Errors"

  dimensions = {
    FunctionName = aws_lambda_function.document_expiry.function_name
  }

  statistic           = "Sum"
  period              = 900
  evaluation_periods  = 1
  datapoints_to_alarm = 1

  threshold           = 0
  comparison_operator = "GreaterThanThreshold"

  treat_missing_data = "notBreaching"

  alarm_actions = [
    aws_sns_topic.security_alerts.arn
  ]

  tags = {
    Name        = "cloudsec-document-expiry-errors"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# DOCUMENT EXPIRY CLEANUP - LAMBDA FAILURE QUEUE ALARM
# ============================================================

resource "aws_cloudwatch_metric_alarm" "document_expiry_lambda_dlq" {
  alarm_name = "cloudsec-document-expiry-lambda-dlq"

  alarm_description = "Failed document expiry Lambda executions are waiting in the failure queue."

  namespace   = "AWS/SQS"
  metric_name = "ApproximateNumberOfMessagesVisible"

  dimensions = {
    QueueName = aws_sqs_queue.document_expiry_lambda_failures.name
  }

  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  datapoints_to_alarm = 1

  threshold           = 0
  comparison_operator = "GreaterThanThreshold"

  treat_missing_data = "notBreaching"

  alarm_actions = [
    aws_sns_topic.security_alerts.arn
  ]

  tags = {
    Name        = "cloudsec-document-expiry-lambda-dlq"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# DOCUMENT EXPIRY CLEANUP - SCHEDULER DLQ ALARM
# ============================================================

resource "aws_cloudwatch_metric_alarm" "document_expiry_scheduler_dlq" {
  alarm_name = "cloudsec-document-expiry-scheduler-dlq"

  alarm_description = "EventBridge Scheduler delivery failures are waiting in the Scheduler DLQ."

  namespace   = "AWS/SQS"
  metric_name = "ApproximateNumberOfMessagesVisible"

  dimensions = {
    QueueName = aws_sqs_queue.document_expiry_scheduler_dlq.name
  }

  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  datapoints_to_alarm = 1

  threshold           = 0
  comparison_operator = "GreaterThanThreshold"

  treat_missing_data = "notBreaching"

  alarm_actions = [
    aws_sns_topic.security_alerts.arn
  ]

  tags = {
    Name        = "cloudsec-document-expiry-scheduler-dlq"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# OUTPUT
# ============================================================

output "document_expiry_lambda_arn" {
  description = "ARN of the pending document expiry cleanup Lambda."
  value       = aws_lambda_function.document_expiry.arn
}
