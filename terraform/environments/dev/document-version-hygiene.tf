# ============================================================
# DOCUMENT VERSION HYGIENE - CLOUDWATCH LOG GROUP
# ============================================================

resource "aws_cloudwatch_log_group" "document_version_hygiene" {
  name              = "/aws/lambda/cloudsec-document-version-hygiene"
  kms_key_id        = aws_kms_key.application_logs.arn
  retention_in_days = 365

  tags = {
    Name        = "cloudsec-document-version-hygiene"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
    Purpose     = "Remove unaccepted uploaded document versions"
  }
}


# ============================================================
# DOCUMENT VERSION HYGIENE - FAILURE QUEUES
# ============================================================

resource "aws_sqs_queue" "document_version_hygiene_lambda_failures" {
  name                      = "cloudsec-document-version-hygiene-lambda-failures"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true

  tags = {
    Name        = "cloudsec-document-version-hygiene-lambda-failures"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}

resource "aws_sqs_queue" "document_version_hygiene_scheduler_dlq" {
  name                      = "cloudsec-document-version-hygiene-scheduler-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true

  tags = {
    Name        = "cloudsec-document-version-hygiene-scheduler-dlq"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# DOCUMENT VERSION HYGIENE - LAMBDA EXECUTION ROLE
# ============================================================

resource "aws_iam_role" "document_version_hygiene_lambda" {
  name        = "cloudsec-document-version-hygiene-lambda-role"
  description = "Execution role for uploaded document version hygiene"

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
    Name        = "cloudsec-document-version-hygiene-lambda-role"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# DOCUMENT VERSION HYGIENE - LEAST-PRIVILEGE IAM POLICY
# ============================================================

resource "aws_iam_role_policy" "document_version_hygiene_lambda" {
  name = "cloudsec-document-version-hygiene-permissions"
  role = aws_iam_role.document_version_hygiene_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid      = "QueryUploadedDocumentHygieneIndex"
        Effect   = "Allow"
        Action   = "dynamodb:Query"
        Resource = "${aws_dynamodb_table.submissions.arn}/index/PendingDocumentExpiryIndex"
      },
      {
        Sid      = "RemoveCompletedHygieneIndexAttributes"
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
        Sid    = "DeleteUnacceptedTenantObjectVersions"
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

        Resource = "${aws_cloudwatch_log_group.document_version_hygiene.arn}:*"
      },
      {
        Sid      = "SendLambdaFailureRecordsToSQS"
        Effect   = "Allow"
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.document_version_hygiene_lambda_failures.arn
      }
    ]
  })
}


# ============================================================
# DOCUMENT VERSION HYGIENE - LAMBDA FUNCTION
# ============================================================

resource "aws_lambda_function" "document_version_hygiene" {

  #checkov:skip=CKV_AWS_116:Asynchronous invocation failure handling uses aws_lambda_function_event_invoke_config with an SQS on_failure destination.

  #checkov:skip=CKV_AWS_117:Scheduled AWS API workers intentionally run outside the VPC to avoid NAT Gateway and unnecessary VPC endpoint costs.

  #checkov:skip=CKV_AWS_173:Environment variables contain configuration identifiers only; no secrets are stored.

  #checkov:skip=CKV_AWS_50:X-Ray tracing is deferred to control development costs; CloudWatch logs, metrics, and alarms provide operational monitoring.

  function_name = "cloudsec-document-version-hygiene"

  description = "Preserves accepted document versions and removes unaccepted S3 versions and delete markers"

  role    = aws_iam_role.document_version_hygiene_lambda.arn
  runtime = "python3.12"
  handler = "handler.handler"

  s3_bucket         = aws_signer_signing_job.lambda_artifacts["document_version_hygiene"].signed_object[0].s3[0].bucket
  s3_key            = aws_signer_signing_job.lambda_artifacts["document_version_hygiene"].signed_object[0].s3[0].key
  s3_object_version = data.aws_s3_object.lambda_signed_artifacts["document_version_hygiene"].version_id

  source_code_hash = filebase64sha256(
    "${path.module}/../../../build/document_version_hygiene.zip"
  )

  code_signing_config_arn = aws_lambda_code_signing_config.application.arn

  architectures = ["x86_64"]

  timeout                        = 300
  memory_size                    = 128
  reserved_concurrent_executions = 1

  environment {
    variables = {
      TABLE_NAME    = aws_dynamodb_table.submissions.name
      HYGIENE_INDEX = "PendingDocumentExpiryIndex"
      BUCKET_NAME   = aws_s3_bucket.application.id
      SHARD_COUNT   = "4"
      MAX_ITEMS     = "50"
      LOG_LEVEL     = "INFO"
    }
  }

  depends_on = [
    aws_iam_role_policy.document_version_hygiene_lambda,
    aws_cloudwatch_log_group.document_version_hygiene
  ]

  tags = {
    Name        = "cloudsec-document-version-hygiene"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# DOCUMENT VERSION HYGIENE - ASYNCHRONOUS INVOCATION
# ============================================================

resource "aws_lambda_function_event_invoke_config" "document_version_hygiene" {
  function_name = aws_lambda_function.document_version_hygiene.function_name

  maximum_event_age_in_seconds = 3600
  maximum_retry_attempts       = 2

  destination_config {
    on_failure {
      destination = aws_sqs_queue.document_version_hygiene_lambda_failures.arn
    }
  }
}


# ============================================================
# DOCUMENT VERSION HYGIENE - SCHEDULER ROLE
# ============================================================

resource "aws_iam_role" "document_version_hygiene_scheduler" {
  name        = "cloudsec-document-version-hygiene-scheduler-role"
  description = "Allows EventBridge Scheduler to invoke document version hygiene"

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
    Name        = "cloudsec-document-version-hygiene-scheduler-role"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# DOCUMENT VERSION HYGIENE - SCHEDULER PERMISSIONS
# ============================================================

resource "aws_iam_role_policy" "document_version_hygiene_scheduler" {
  name = "cloudsec-document-version-hygiene-scheduler-invoke"
  role = aws_iam_role.document_version_hygiene_scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid      = "InvokeDocumentVersionHygieneLambda"
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = aws_lambda_function.document_version_hygiene.arn
      },
      {
        Sid      = "SendSchedulerFailuresToSQS"
        Effect   = "Allow"
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.document_version_hygiene_scheduler_dlq.arn
      }
    ]
  })
}


# ============================================================
# DOCUMENT VERSION HYGIENE - EVENTBRIDGE SCHEDULE
# ============================================================

resource "aws_scheduler_schedule" "document_version_hygiene" {

  #checkov:skip=CKV_AWS_297:Schedule targets contain no sensitive payload; AWS-owned encryption is sufficient.

  name        = "cloudsec-document-version-hygiene"
  description = "Remove unaccepted uploaded document versions every 15 minutes"

  schedule_expression          = "rate(15 minutes)"
  schedule_expression_timezone = "UTC"
  state                        = "ENABLED"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.document_version_hygiene.arn
    role_arn = aws_iam_role.document_version_hygiene_scheduler.arn
    input    = "{}"

    dead_letter_config {
      arn = aws_sqs_queue.document_version_hygiene_scheduler_dlq.arn
    }

    retry_policy {
      maximum_event_age_in_seconds = 3600
      maximum_retry_attempts       = 2
    }
  }

  depends_on = [
    aws_iam_role_policy.document_version_hygiene_scheduler
  ]
}


# ============================================================
# DOCUMENT VERSION HYGIENE - LAMBDA ERROR ALARM
# ============================================================

resource "aws_cloudwatch_metric_alarm" "document_version_hygiene_errors" {
  alarm_name        = "cloudsec-document-version-hygiene-errors"
  alarm_description = "The document version hygiene Lambda reported an execution error."

  namespace   = "AWS/Lambda"
  metric_name = "Errors"

  dimensions = {
    FunctionName = aws_lambda_function.document_version_hygiene.function_name
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
    Name        = "cloudsec-document-version-hygiene-errors"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# DOCUMENT VERSION HYGIENE - LAMBDA DLQ ALARM
# ============================================================

resource "aws_cloudwatch_metric_alarm" "document_version_hygiene_lambda_dlq" {
  alarm_name        = "cloudsec-document-version-hygiene-lambda-dlq"
  alarm_description = "Failed document version hygiene Lambda executions are waiting in the failure queue."

  namespace   = "AWS/SQS"
  metric_name = "ApproximateNumberOfMessagesVisible"

  dimensions = {
    QueueName = aws_sqs_queue.document_version_hygiene_lambda_failures.name
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
    Name        = "cloudsec-document-version-hygiene-lambda-dlq"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# DOCUMENT VERSION HYGIENE - SCHEDULER DLQ ALARM
# ============================================================

resource "aws_cloudwatch_metric_alarm" "document_version_hygiene_scheduler_dlq" {
  alarm_name        = "cloudsec-document-version-hygiene-scheduler-dlq"
  alarm_description = "Failed Scheduler deliveries are waiting in the document version hygiene Scheduler DLQ."

  namespace   = "AWS/SQS"
  metric_name = "ApproximateNumberOfMessagesVisible"

  dimensions = {
    QueueName = aws_sqs_queue.document_version_hygiene_scheduler_dlq.name
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
    Name        = "cloudsec-document-version-hygiene-scheduler-dlq"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# OUTPUTS
# ============================================================

output "document_version_hygiene_lambda_arn" {
  description = "ARN of the uploaded document version hygiene Lambda."
  value       = aws_lambda_function.document_version_hygiene.arn
}

output "document_version_hygiene_scheduler_dlq_arn" {
  description = "ARN of the document version hygiene Scheduler DLQ."
  value       = aws_sqs_queue.document_version_hygiene_scheduler_dlq.arn
}
