# ============================================================
# EC2 IAM ROLE
# ============================================================

resource "aws_iam_role" "ec2_ssm" {
  name        = "cloudsec-ec2-ssm-role"
  description = "IAM role for private EC2 instances running the Cloud Security application"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          Service = "ec2.amazonaws.com"
        }

        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name        = "cloudsec-ec2-ssm-role"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# SYSTEMS MANAGER PERMISSIONS
# ============================================================

resource "aws_iam_role_policy_attachment" "ec2_ssm_core" {
  role = aws_iam_role.ec2_ssm.name

  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}


# ============================================================
# APPLICATION DATA ACCESS
# ============================================================

resource "aws_iam_role_policy" "ec2_application_data_access" {
  name = "cloudsec-application-data-access"
  role = aws_iam_role.ec2_ssm.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [

      # ------------------------------------------------------
      # SUBMISSIONS TABLE
      # ------------------------------------------------------

      {
        Sid    = "SubmissionItemAccess"
        Effect = "Allow"

        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:Query",
          "dynamodb:TransactWriteItems"
        ]

        Resource = [
          aws_dynamodb_table.submissions.arn
        ]
      },

      {
        Sid    = "SubmissionIndexQueries"
        Effect = "Allow"

        Action = [
          "dynamodb:Query"
        ]

        Resource = [
          "${aws_dynamodb_table.submissions.arn}/index/OwnerIndex",
          "${aws_dynamodb_table.submissions.arn}/index/TenantStatusIndex"
        ]
      },

      # ------------------------------------------------------
      # TENANT MEMBERSHIPS
      # READ AND TRANSACTIONAL WRITE ACCESS
      # ------------------------------------------------------

      {
        Sid    = "TenantMembershipReadAccess"
        Effect = "Allow"

        Action = [
          "dynamodb:GetItem",
          "dynamodb:Query",
          "dynamodb:TransactWriteItems"
        ]

        Resource = [
          aws_dynamodb_table.tenant_memberships.arn
        ]
      },

      {
        Sid    = "TenantMembershipIndexQueries"
        Effect = "Allow"

        Action = [
          "dynamodb:Query"
        ]

        Resource = [
          "${aws_dynamodb_table.tenant_memberships.arn}/index/TenantMembersIndex"
        ]
      },

      # ------------------------------------------------------
      # APPLICATION AUDIT EVENTS
      # Insert and query access; no UpdateItem or DeleteItem permissions.
      # ------------------------------------------------------

      {
        Sid    = "ApplicationAuditAccess"
        Effect = "Allow"

        Action = [
          "dynamodb:PutItem",
          "dynamodb:Query",
          "dynamodb:TransactWriteItems"
        ]

        Resource = [
          aws_dynamodb_table.audit_events.arn
        ]
      },
      {
        Sid      = "TenantAuditIndexQuery"
        Effect   = "Allow"
        Action   = "dynamodb:Query"
        Resource = "${aws_dynamodb_table.audit_events.arn}/index/TenantAuditIndex"
      },

      # ------------------------------------------------------
      # APPLICATION DOCUMENT STORAGE
      # No bucket listing or object deletion.
      # ------------------------------------------------------

      {
        Sid    = "ApplicationDocumentObjectAccess"
        Effect = "Allow"

        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion",
          "s3:PutObject"
        ]

        Resource = [
          "${aws_s3_bucket.application.arn}/tenants/*"
        ]
      },

      # ------------------------------------------------------
      # APPLICATION S3 KMS KEY
      # ------------------------------------------------------

      {
        Sid    = "ApplicationDocumentKMSAccess"
        Effect = "Allow"

        Action = [
          "kms:GenerateDataKey",
          "kms:Decrypt"
        ]

        Resource = [
          aws_kms_key.application.arn
        ]

        Condition = {
          StringEquals = {
            "kms:ViaService"                   = "s3.ap-south-1.amazonaws.com"
            "kms:EncryptionContext:aws:s3:arn" = aws_s3_bucket.application.arn
          }
        }
      }
    ]
  })
}


# ============================================================
# COGNITO JWKS READ ACCESS
# ============================================================

resource "aws_iam_role_policy" "ec2_jwks_read" {
  name = "cloudsec-ec2-jwks-read"
  role = aws_iam_role.ec2_ssm.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid    = "ReadCognitoJWKS"
        Effect = "Allow"

        Action = [
          "s3:GetObject"
        ]

        Resource = [
          "${aws_s3_bucket.identity_metadata.arn}/security/jwks.json"
        ]
      }
    ]
  })
}


# ============================================================
# ECR IMAGE PULL PERMISSIONS
# ============================================================

resource "aws_iam_role_policy" "ec2_ecr_pull" {
  name = "cloudsec-ec2-ecr-pull"
  role = aws_iam_role.ec2_ssm.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid    = "ECRAuthentication"
        Effect = "Allow"

        Action = [
          "ecr:GetAuthorizationToken"
        ]

        Resource = "*"
      },
      {
        Sid    = "PullApplicationImage"
        Effect = "Allow"

        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage"
        ]

        Resource = [
          aws_ecr_repository.document_api.arn
        ]
      }
    ]
  })
}


# ============================================================
# EC2 INSTANCE PROFILE
# ============================================================

resource "aws_iam_instance_profile" "ec2_ssm" {
  name = "cloudsec-ec2-ssm-profile"
  role = aws_iam_role.ec2_ssm.name

  tags = {
    Name        = "cloudsec-ec2-ssm-profile"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# OUTPUTS
# ============================================================

output "ec2_iam_role_arn" {
  description = "IAM role ARN assigned to EC2 instances."
  value       = aws_iam_role.ec2_ssm.arn
}

output "ec2_instance_profile_name" {
  description = "Instance profile used by EC2 instances."
  value       = aws_iam_instance_profile.ec2_ssm.name
}
