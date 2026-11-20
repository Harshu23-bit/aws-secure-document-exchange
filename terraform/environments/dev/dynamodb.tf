# ============================================================
# DYNAMODB - SUBMISSIONS
# ============================================================

resource "aws_dynamodb_table" "submissions" {
  name         = "cloudsec-submissions-dev"
  billing_mode = "PAY_PER_REQUEST"

  hash_key  = "PK"
  range_key = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  attribute {
    name = "GSI1PK"
    type = "S"
  }

  attribute {
    name = "GSI1SK"
    type = "S"
  }

  attribute {
    name = "GSI2PK"
    type = "S"
  }

  attribute {
    name = "GSI2SK"
    type = "S"
  }

  attribute {
    name = "GSI3PK"
    type = "S"
  }

  attribute {
    name = "GSI3SK"
    type = "S"
  }

  attribute {
    name = "GSI4PK"
    type = "S"
  }

  attribute {
    name = "GSI4SK"
    type = "S"
  }

  global_secondary_index {
    name            = "OwnerIndex"
    projection_type = "INCLUDE"

    key_schema {
      attribute_name = "GSI1PK"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "GSI1SK"
      key_type       = "RANGE"
    }

    non_key_attributes = [
      "tenant_id",
      "submission_id",
      "owner_id",
      "status",
      "created_at",
      "updated_at",
      "version",
      "title"
    ]
  }

  global_secondary_index {
    name            = "TenantStatusIndex"
    projection_type = "INCLUDE"

    key_schema {
      attribute_name = "GSI2PK"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "GSI2SK"
      key_type       = "RANGE"
    }

    non_key_attributes = [
      "tenant_id",
      "submission_id",
      "owner_id",
      "status",
      "created_at",
      "updated_at",
      "version",
      "title"
    ]
  }

  # Sparse index for pending-upload expiry and uploaded-document hygiene.
  global_secondary_index {
    name            = "PendingDocumentExpiryIndex"
    projection_type = "INCLUDE"

    key_schema {
      attribute_name = "GSI3PK"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "GSI3SK"
      key_type       = "RANGE"
    }

    non_key_attributes = [
      "tenant_id",
      "entity_type",
      "submission_id",
      "document_id",
      "object_key",
      "size_bytes",
      "expires_at",
      "status",
      "version_id",
      "upload_url_expires_at",
      "upload_hygiene_after"
    ]
  }

  # Sparse index containing documents awaiting S3 object cleanup.
  global_secondary_index {
    name            = "PendingDocumentCleanupIndex"
    projection_type = "INCLUDE"

    key_schema {
      attribute_name = "GSI4PK"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "GSI4SK"
      key_type       = "RANGE"
    }

    non_key_attributes = [
      "tenant_id",
      "submission_id",
      "document_id",
      "object_key",
      "expires_at",
      "cleanup_after",
      "cleanup_attempts",
      "cleanup_completed_at",
      "finalize_after",
      "status"
    ]
  }

  # Recover accidental writes or deletions.
  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.application.arn
  }

  tags = {
    Name        = "cloudsec-submissions-dev"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
    DataClass   = "Application"
  }
}


# ============================================================
# DYNAMODB - TENANT MEMBERSHIPS
# ============================================================

resource "aws_dynamodb_table" "tenant_memberships" {
  name         = "cloudsec-tenant-memberships-dev"
  billing_mode = "PAY_PER_REQUEST"

  hash_key  = "PK"
  range_key = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  attribute {
    name = "GSI1PK"
    type = "S"
  }

  attribute {
    name = "GSI1SK"
    type = "S"
  }

  global_secondary_index {
    name            = "TenantMembersIndex"
    projection_type = "INCLUDE"

    key_schema {
      attribute_name = "GSI1PK"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "GSI1SK"
      key_type       = "RANGE"
    }

    non_key_attributes = [
      "user_id",
      "tenant_id",
      "role",
      "status",
      "created_at"
    ]
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.application.arn
  }

  tags = {
    Name        = "cloudsec-tenant-memberships-dev"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
    DataClass   = "Application"
  }
}


# ============================================================
# DYNAMODB - APPLICATION AUDIT EVENTS
# ============================================================

resource "aws_dynamodb_table" "audit_events" {
  name         = "cloudsec-audit-events-dev"
  billing_mode = "PAY_PER_REQUEST"

  hash_key  = "PK"
  range_key = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  attribute {
    name = "GSI1PK"
    type = "S"
  }

  attribute {
    name = "GSI1SK"
    type = "S"
  }

  global_secondary_index {
    name            = "TenantAuditIndex"
    projection_type = "ALL"

    key_schema {
      attribute_name = "GSI1PK"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "GSI1SK"
      key_type       = "RANGE"
    }
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.application.arn
  }

  tags = {
    Name        = "cloudsec-audit-events-dev"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
    DataClass   = "Audit"
  }
}


# ============================================================
# OUTPUTS
# ============================================================

output "submissions_table_name" {
  description = "DynamoDB table storing submissions and related items."
  value       = aws_dynamodb_table.submissions.name
}

output "tenant_memberships_table_name" {
  description = "DynamoDB table storing tenant memberships."
  value       = aws_dynamodb_table.tenant_memberships.name
}

output "audit_events_table_name" {
  description = "DynamoDB table storing application audit events."
  value       = aws_dynamodb_table.audit_events.name
}
