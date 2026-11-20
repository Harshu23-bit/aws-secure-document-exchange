# ==========================================
# DEDICATED S3 ACCESS LOGS BUCKET
# ==========================================

resource "aws_s3_bucket" "s3_access_logs" {

  #checkov:skip=CKV_AWS_145:SSE-S3 is required for the S3 server access logging destination bucket.

  #checkov:skip=CKV_AWS_144:Single-region development architecture; cross-region access-log replication is deferred until audit DR requirements are defined.

  #checkov:skip=CKV2_AWS_62:No event-driven consumer currently requires access-log bucket notifications.

  bucket_prefix = "cloudsec-s3-access-logs-117088935455-"

  force_destroy = false

  tags = {
    Name        = "cloudsec-s3-access-logs"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
    Purpose     = "S3 Server Access Logs"
  }
}


# ==========================================
# BLOCK PUBLIC ACCESS
# ==========================================

resource "aws_s3_bucket_public_access_block" "s3_access_logs" {
  bucket = aws_s3_bucket.s3_access_logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}


# ==========================================
# OBJECT OWNERSHIP
# ==========================================

resource "aws_s3_bucket_ownership_controls" "s3_access_logs" {
  bucket = aws_s3_bucket.s3_access_logs.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}


# ==========================================
# SERVER-SIDE ENCRYPTION
# ==========================================

resource "aws_s3_bucket_server_side_encryption_configuration" "s3_access_logs" {
  bucket = aws_s3_bucket.s3_access_logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}


# ==========================================
# VERSIONING
# ==========================================

resource "aws_s3_bucket_versioning" "s3_access_logs" {
  bucket = aws_s3_bucket.s3_access_logs.id

  versioning_configuration {
    status = "Enabled"
  }
}


# ==========================================
# LIFECYCLE MANAGEMENT
# ==========================================

resource "aws_s3_bucket_lifecycle_configuration" "s3_access_logs" {
  bucket = aws_s3_bucket.s3_access_logs.id

  rule {
    id     = "s3-access-logs-retention"
    status = "Enabled"

    filter {}

    expiration {
      days = 90
    }

    noncurrent_version_expiration {
      noncurrent_days = 90
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}


# ==========================================
# S3 ACCESS LOG DELIVERY POLICY
# ==========================================

data "aws_iam_policy_document" "s3_access_logs" {

  # APPLICATION S3 BUCKET LOGS
  statement {
    sid    = "AllowApplicationBucketLogDelivery"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["logging.s3.amazonaws.com"]
    }

    actions = [
      "s3:PutObject"
    ]

    resources = [
      "${aws_s3_bucket.s3_access_logs.arn}/s3-access/application/*"
    ]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = [aws_s3_bucket.application.arn]
    }
  }


  # VPC FLOW LOGS BUCKET LOGS
  statement {
    sid    = "AllowFlowLogsBucketLogDelivery"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["logging.s3.amazonaws.com"]
    }

    actions = [
      "s3:PutObject"
    ]

    resources = [
      "${aws_s3_bucket.s3_access_logs.arn}/s3-access/vpc-flow-logs/*"
    ]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = [aws_s3_bucket.vpc_flow_logs.arn]
    }
  }


  # APPLICATION LOAD BALANCER ACCESS LOGS
  statement {
    sid    = "AllowALBAccessLogDelivery"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["logdelivery.elasticloadbalancing.amazonaws.com"]
    }

    actions = [
      "s3:PutObject"
    ]

    resources = [
      "${aws_s3_bucket.s3_access_logs.arn}/alb/AWSLogs/${data.aws_caller_identity.current.account_id}/*"
    ]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values = [
        "arn:${data.aws_partition.current.partition}:elasticloadbalancing:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:loadbalancer/app/*"
      ]
    }
  }


  # CLOUDTRAIL BUCKET ACCESS LOGS
  statement {
    sid    = "AllowCloudTrailBucketLogDelivery"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["logging.s3.amazonaws.com"]
    }

    actions = [
      "s3:PutObject"
    ]

    resources = [
      "${aws_s3_bucket.s3_access_logs.arn}/s3-access/cloudtrail/*"
    ]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = [aws_s3_bucket.cloudtrail.arn]
    }
  }


  # LAMBDA SIGNING ARTIFACTS BUCKET ACCESS LOGS
  statement {
    sid    = "AllowLambdaSigningArtifactsLogDelivery"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["logging.s3.amazonaws.com"]
    }

    actions = [
      "s3:PutObject"
    ]

    resources = [
      "${aws_s3_bucket.s3_access_logs.arn}/s3-access/lambda-signing-artifacts/*"
    ]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = [aws_s3_bucket.lambda_signing_artifacts.arn]
    }
  }


  # JWKS IDENTITY METADATA BUCKET ACCESS LOGS
  statement {
    sid    = "AllowIdentityMetadataLogDelivery"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["logging.s3.amazonaws.com"]
    }

    actions = [
      "s3:PutObject"
    ]

    resources = [
      "${aws_s3_bucket.s3_access_logs.arn}/s3-access/identity-metadata/*"
    ]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = [aws_s3_bucket.identity_metadata.arn]
    }
  }

  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]

    resources = [
      aws_s3_bucket.s3_access_logs.arn,
      "${aws_s3_bucket.s3_access_logs.arn}/*"
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }

    condition {
      test     = "Bool"
      variable = "aws:PrincipalIsAWSService"
      values   = ["false"]
    }
  }
}


# ==========================================
# S3 ACCESS LOGS BUCKET POLICY
# ==========================================

resource "aws_s3_bucket_policy" "s3_access_logs" {
  bucket = aws_s3_bucket.s3_access_logs.id
  policy = data.aws_iam_policy_document.s3_access_logs.json

  depends_on = [
    aws_s3_bucket_public_access_block.s3_access_logs
  ]
}


# ==========================================
# ENABLE ACCESS LOGGING - APPLICATION BUCKET
# ==========================================

resource "aws_s3_bucket_logging" "application" {
  bucket        = aws_s3_bucket.application.id
  target_bucket = aws_s3_bucket.s3_access_logs.id
  target_prefix = "s3-access/application/"

  depends_on = [
    aws_s3_bucket_policy.s3_access_logs
  ]
}


# ==========================================
# ENABLE ACCESS LOGGING - FLOW LOGS BUCKET
# ==========================================

resource "aws_s3_bucket_logging" "vpc_flow_logs" {
  bucket        = aws_s3_bucket.vpc_flow_logs.id
  target_bucket = aws_s3_bucket.s3_access_logs.id
  target_prefix = "s3-access/vpc-flow-logs/"

  depends_on = [
    aws_s3_bucket_policy.s3_access_logs
  ]
}


# ==========================================
# ENABLE ACCESS LOGGING - IDENTITY METADATA
# ==========================================

resource "aws_s3_bucket_logging" "identity_metadata" {
  bucket        = aws_s3_bucket.identity_metadata.id
  target_bucket = aws_s3_bucket.s3_access_logs.id
  target_prefix = "s3-access/identity-metadata/"

  depends_on = [
    aws_s3_bucket_policy.s3_access_logs
  ]
}


# ==========================================
# ENABLE ACCESS LOGGING - LAMBDA SIGNING ARTIFACTS
# ==========================================

resource "aws_s3_bucket_logging" "lambda_signing_artifacts" {
  bucket        = aws_s3_bucket.lambda_signing_artifacts.id
  target_bucket = aws_s3_bucket.s3_access_logs.id
  target_prefix = "s3-access/lambda-signing-artifacts/"

  depends_on = [
    aws_s3_bucket_policy.s3_access_logs
  ]
}
