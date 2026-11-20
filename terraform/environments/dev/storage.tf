# APPLICATION S3 BUCKET
resource "aws_s3_bucket" "application" {

  #checkov:skip=CKV_AWS_144:Single-region development architecture; application document replication requires defined RPO, RTO and recovery architecture.

  #checkov:skip=CKV2_AWS_62:Current document workflow uses API-driven processing; no S3 event notification consumer is implemented.

  bucket_prefix = "cloudsec-application-117088935455-"

  # Prevent accidental deletion of the bucket and its contents.
  force_destroy = false

  tags = {
    Name        = "cloudsec-application-storage"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# BLOCK ALL PUBLIC ACCESS
resource "aws_s3_bucket_public_access_block" "application" {
  bucket = aws_s3_bucket.application.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}


# ENFORCE BUCKET OWNER OWNERSHIP
resource "aws_s3_bucket_ownership_controls" "application" {
  bucket = aws_s3_bucket.application.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}


# ENABLE VERSIONING
resource "aws_s3_bucket_versioning" "application" {
  bucket = aws_s3_bucket.application.id

  versioning_configuration {
    status = "Enabled"
  }
}


# DEFAULT SERVER-SIDE ENCRYPTION USING KMS
resource "aws_s3_bucket_server_side_encryption_configuration" "application" {
  bucket = aws_s3_bucket.application.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.application.arn
    }

    bucket_key_enabled = true
  }
}


# LIFECYCLE MANAGEMENT
resource "aws_s3_bucket_lifecycle_configuration" "application" {
  bucket = aws_s3_bucket.application.id

  rule {
    id     = "application-storage-lifecycle"
    status = "Enabled"

    # Remove incomplete multipart uploads after 7 days.
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}


# DENY UNENCRYPTED TRANSPORT
data "aws_iam_policy_document" "application_bucket" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    actions = [
      "s3:*"
    ]

    resources = [
      aws_s3_bucket.application.arn,
      "${aws_s3_bucket.application.arn}/*"
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid    = "DenyUploadsWithoutKMS"
    effect = "Deny"

    actions = [
      "s3:PutObject"
    ]

    resources = [
      "${aws_s3_bucket.application.arn}/*"
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "StringNotEquals"
      variable = "s3:x-amz-server-side-encryption"
      values   = ["aws:kms"]
    }
  }

  statement {
    sid    = "DenyUploadsWithWrongKMSKey"
    effect = "Deny"

    actions = [
      "s3:PutObject"
    ]

    resources = [
      "${aws_s3_bucket.application.arn}/*"
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "StringNotEquals"
      variable = "s3:x-amz-server-side-encryption-aws-kms-key-id"
      values   = [aws_kms_key.application.arn]
    }
  }
}


# APPLY BUCKET SECURITY POLICY
resource "aws_s3_bucket_policy" "application" {
  bucket = aws_s3_bucket.application.id
  policy = data.aws_iam_policy_document.application_bucket.json
}


# OUTPUTS
output "application_bucket_name" {
  description = "Name of the application bucket."
  value       = aws_s3_bucket.application.id
}

output "application_bucket_arn" {
  description = "ARN of the application bucket."
  value       = aws_s3_bucket.application.arn
}
