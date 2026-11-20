# ==========================================
# DEDICATED CLOUDTRAIL AUDIT BUCKET
# ==========================================

resource "aws_s3_bucket" "cloudtrail" {

  #checkov:skip=CKV_AWS_144:Single-region development architecture; cross-region audit-log replication is deferred until DR requirements are defined.

  #checkov:skip=CKV2_AWS_62:No S3 event-driven consumer currently requires CloudTrail bucket notifications.

  bucket_prefix = "cloudsec-cloudtrail-117088935455-"

  force_destroy = false

  tags = {
    Name        = "cloudsec-cloudtrail-audit"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
    Purpose     = "CloudTrail Audit Logs"
  }
}

# ==========================================
# BLOCK PUBLIC ACCESS
# ==========================================

resource "aws_s3_bucket_public_access_block" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ==========================================
# OBJECT OWNERSHIP
# ==========================================

resource "aws_s3_bucket_ownership_controls" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# ==========================================
# KMS ENCRYPTION
# ==========================================

resource "aws_s3_bucket_server_side_encryption_configuration" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.cloudtrail.arn
    }
  }
}

# ==========================================
# VERSIONING
# ==========================================

resource "aws_s3_bucket_versioning" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id

  versioning_configuration {
    status = "Enabled"
  }
}

# ==========================================
# LIFECYCLE MANAGEMENT
# ==========================================

resource "aws_s3_bucket_lifecycle_configuration" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id

  rule {
    id     = "cloudtrail-audit-log-retention"
    status = "Enabled"

    filter {}

    expiration {
      days = 365
    }

    noncurrent_version_expiration {
      noncurrent_days = 365
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# ==========================================
# CLOUDTRAIL DELIVERY BUCKET POLICY
# ==========================================

data "aws_iam_policy_document" "cloudtrail_bucket" {
  # Allow CloudTrail to check bucket permissions.
  statement {
    sid    = "AWSCloudTrailAclCheck"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }

    actions = [
      "s3:GetBucketAcl"
    ]

    resources = [
      aws_s3_bucket.cloudtrail.arn
    ]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"

      values = [
        local.cloudtrail_trail_arn
      ]
    }
  }

  # Allow CloudTrail to deliver audit logs.
  statement {
    sid    = "AWSCloudTrailWrite"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }

    actions = [
      "s3:PutObject"
    ]

    resources = [
      "${aws_s3_bucket.cloudtrail.arn}/AWSLogs/${data.aws_caller_identity.current.account_id}/*"
    ]

    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"

      values = [
        "bucket-owner-full-control"
      ]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"

      values = [
        local.cloudtrail_trail_arn
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
      aws_s3_bucket.cloudtrail.arn,
      "${aws_s3_bucket.cloudtrail.arn}/*"
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

resource "aws_s3_bucket_policy" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id
  policy = data.aws_iam_policy_document.cloudtrail_bucket.json

  depends_on = [
    aws_s3_bucket_public_access_block.cloudtrail
  ]
}

# ==========================================
# CLOUDTRAIL BUCKET SERVER ACCESS LOGGING
# ==========================================

resource "aws_s3_bucket_logging" "cloudtrail" {
  bucket        = aws_s3_bucket.cloudtrail.id
  target_bucket = aws_s3_bucket.s3_access_logs.id
  target_prefix = "s3-access/cloudtrail/"

  depends_on = [
    aws_s3_bucket_policy.s3_access_logs
  ]
}

# ==========================================
# OUTPUTS
# ==========================================

output "cloudtrail_bucket_name" {
  description = "Dedicated S3 bucket storing CloudTrail audit logs."
  value       = aws_s3_bucket.cloudtrail.id
}

output "cloudtrail_bucket_arn" {
  description = "ARN of the dedicated CloudTrail audit bucket."
  value       = aws_s3_bucket.cloudtrail.arn
}
