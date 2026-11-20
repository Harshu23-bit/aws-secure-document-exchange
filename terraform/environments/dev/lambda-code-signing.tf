# ============================================================
# LAMBDA CODE SIGNING - ARTIFACT STORAGE
# ============================================================

resource "aws_s3_bucket" "lambda_signing_artifacts" {

  #checkov:skip=CKV_AWS_144:Single-region development architecture; cross-region replication is deferred until DR requirements are defined.

  #checkov:skip=CKV2_AWS_62:No event-driven consumer currently requires S3 event notifications.

  #checkov:skip=CKV_AWS_145:SSE-S3 is sufficient for temporary Lambda deployment artifacts; a dedicated KMS key is not justified.
  bucket_prefix = "cloudsec-lambda-signing-${data.aws_caller_identity.current.account_id}-"

  force_destroy = false

  tags = {
    Name        = "cloudsec-lambda-signing-artifacts"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
    Purpose     = "Lambda-Code-Signing"
  }
}


resource "aws_s3_bucket_public_access_block" "lambda_signing_artifacts" {
  bucket = aws_s3_bucket.lambda_signing_artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}


resource "aws_s3_bucket_ownership_controls" "lambda_signing_artifacts" {
  bucket = aws_s3_bucket.lambda_signing_artifacts.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}


resource "aws_s3_bucket_versioning" "lambda_signing_artifacts" {
  bucket = aws_s3_bucket.lambda_signing_artifacts.id

  versioning_configuration {
    status = "Enabled"
  }
}


resource "aws_s3_bucket_server_side_encryption_configuration" "lambda_signing_artifacts" {
  bucket = aws_s3_bucket.lambda_signing_artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}


resource "aws_s3_bucket_lifecycle_configuration" "lambda_signing_artifacts" {

  #checkov:skip=CKV_AWS_300:Both unsigned and signed artifact lifecycle rules explicitly abort incomplete multipart uploads after seven days; this is already configured.

  bucket = aws_s3_bucket.lambda_signing_artifacts.id

  rule {
    id     = "expire-unsigned-artifacts"
    status = "Enabled"

    filter {
      prefix = "unsigned/"
    }

    expiration {
      days = 30
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  rule {
    id     = "expire-signed-artifacts"
    status = "Enabled"

    filter {
      prefix = "signed/"
    }

    expiration {
      days = 90
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}


data "aws_iam_policy_document" "lambda_signing_artifacts" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    actions = ["s3:*"]

    resources = [
      aws_s3_bucket.lambda_signing_artifacts.arn,
      "${aws_s3_bucket.lambda_signing_artifacts.arn}/*"
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
}


resource "aws_s3_bucket_policy" "lambda_signing_artifacts" {
  bucket = aws_s3_bucket.lambda_signing_artifacts.id
  policy = data.aws_iam_policy_document.lambda_signing_artifacts.json
}


# ============================================================
# AWS SIGNER - SIGNING PROFILE
# ============================================================

resource "aws_signer_signing_profile" "lambda" {
  name_prefix = "cloudsec_lambda_"

  platform_id = "AWSLambda-SHA384-ECDSA"

  signature_validity_period {
    value = 2
    type  = "YEARS"
  }

  tags = {
    Name        = "cloudsec-lambda-signing"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# LAMBDA CODE SIGNING CONFIGURATION
# ============================================================

resource "aws_lambda_code_signing_config" "application" {
  description = "Enforce trusted AWS Signer signatures for application Lambda deployment packages"

  allowed_publishers {
    signing_profile_version_arns = [
      aws_signer_signing_profile.lambda.version_arn
    ]
  }

  policies {
    untrusted_artifact_on_deployment = "Enforce"
  }

  tags = {
    Name        = "cloudsec-lambda-code-signing"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# OUTPUTS
# ============================================================

output "lambda_signing_artifact_bucket" {
  description = "Private S3 bucket used for Lambda signing artifacts."
  value       = aws_s3_bucket.lambda_signing_artifacts.id
}


output "lambda_signing_profile_name" {
  description = "AWS Signer profile used for Lambda packages."
  value       = aws_signer_signing_profile.lambda.name
}


output "lambda_code_signing_config_arn" {
  description = "Enforced Lambda code-signing configuration ARN."
  value       = aws_lambda_code_signing_config.application.arn
}

locals {
  lambda_artifacts = {

    document_expiry = {
      filename = "document_expiry.zip"
      prefix   = "signed/document-expiry/"
    }

    document_cleanup = {
      filename = "document_cleanup.zip"
      prefix   = "signed/document-cleanup/"
    }

    document_finalization = {
      filename = "document_finalization.zip"
      prefix   = "signed/document-finalization/"
    }

    document_version_hygiene = {
      filename = "document_version_hygiene.zip"
      prefix   = "signed/document-version-hygiene/"
    }

    jwks_sync = {
      filename = "jwks_sync.zip"
      prefix   = "signed/jwks-sync/"
    }
  }
}

resource "aws_s3_object" "lambda_unsigned_artifacts" {
  for_each = local.lambda_artifacts

  bucket = aws_s3_bucket.lambda_signing_artifacts.id
  key    = "unsigned/${each.value.filename}"
  source = "${path.module}/../../../build/${each.value.filename}"
  etag   = filemd5("${path.module}/../../../build/${each.value.filename}")

  depends_on = [
    aws_s3_bucket_versioning.lambda_signing_artifacts
  ]
}

resource "aws_signer_signing_job" "lambda_artifacts" {
  for_each = local.lambda_artifacts

  profile_name = aws_signer_signing_profile.lambda.name

  source {
    s3 {
      bucket  = aws_s3_object.lambda_unsigned_artifacts[each.key].bucket
      key     = aws_s3_object.lambda_unsigned_artifacts[each.key].key
      version = aws_s3_object.lambda_unsigned_artifacts[each.key].version_id
    }
  }

  destination {
    s3 {
      bucket = aws_s3_bucket.lambda_signing_artifacts.id
      prefix = each.value.prefix
    }
  }
}

data "aws_s3_object" "lambda_signed_artifacts" {
  for_each = local.lambda_artifacts

  bucket = aws_signer_signing_job.lambda_artifacts[each.key].signed_object[0].s3[0].bucket
  key    = aws_signer_signing_job.lambda_artifacts[each.key].signed_object[0].s3[0].key
}
