# ==========================================
# VPC FLOW LOGS - S3 DESTINATION
# ==========================================

resource "aws_s3_bucket" "vpc_flow_logs" {

  #checkov:skip=CKV_AWS_145:SSE-S3 is supported for VPC Flow Logs delivery; a customer-managed KMS key is not required by the current development threat model.

  #checkov:skip=CKV_AWS_144:Single-region development architecture; cross-region flow-log replication is not currently required.

  #checkov:skip=CKV2_AWS_62:No event-driven consumer currently requires VPC Flow Logs bucket notifications.
  bucket_prefix = "cloudsec-vpc-flowlogs-117088935455-"

  force_destroy = false

  tags = {
    Name        = "cloudsec-vpc-flowlogs"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
    Purpose     = "VPC Flow Logs"
  }
}

# ==========================================
# BLOCK PUBLIC ACCESS
# ==========================================

resource "aws_s3_bucket_public_access_block" "vpc_flow_logs" {
  bucket = aws_s3_bucket.vpc_flow_logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ==========================================
# OBJECT OWNERSHIP
# ==========================================

resource "aws_s3_bucket_ownership_controls" "vpc_flow_logs" {
  bucket = aws_s3_bucket.vpc_flow_logs.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# ==========================================
# SERVER-SIDE ENCRYPTION
# ==========================================

resource "aws_s3_bucket_server_side_encryption_configuration" "vpc_flow_logs" {
  bucket = aws_s3_bucket.vpc_flow_logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# ==========================================
# LIFECYCLE MANAGEMENT
# ==========================================

resource "aws_s3_bucket_lifecycle_configuration" "vpc_flow_logs" {
  bucket = aws_s3_bucket.vpc_flow_logs.id

  rule {
    id     = "expire-old-flow-logs"
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
# VPC FLOW LOGS DELIVERY POLICY
# ==========================================

data "aws_partition" "current" {}

data "aws_iam_policy_document" "vpc_flow_logs_bucket" {
  statement {
    sid    = "AWSLogDeliveryAclCheck"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["delivery.logs.amazonaws.com"]
    }

    actions = [
      "s3:GetBucketAcl"
    ]

    resources = [
      aws_s3_bucket.vpc_flow_logs.arn
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
        "arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:*"
      ]
    }
  }

  statement {
    sid    = "AWSLogDeliveryWrite"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["delivery.logs.amazonaws.com"]
    }

    actions = [
      "s3:PutObject"
    ]

    resources = [
      "${aws_s3_bucket.vpc_flow_logs.arn}/AWSLogs/${data.aws_caller_identity.current.account_id}/*"
    ]

    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values = [
        "arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:*"
      ]
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
      aws_s3_bucket.vpc_flow_logs.arn,
      "${aws_s3_bucket.vpc_flow_logs.arn}/*"
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

resource "aws_s3_bucket_policy" "vpc_flow_logs" {
  bucket = aws_s3_bucket.vpc_flow_logs.id
  policy = data.aws_iam_policy_document.vpc_flow_logs_bucket.json

  depends_on = [
    aws_s3_bucket_public_access_block.vpc_flow_logs
  ]
}

# ==========================================
# S3 VERSIONING
# ==========================================

resource "aws_s3_bucket_versioning" "vpc_flow_logs" {
  bucket = aws_s3_bucket.vpc_flow_logs.id

  versioning_configuration {
    status = "Enabled"
  }
}
