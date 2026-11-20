# ============================================================
# PRIVATE ECR REPOSITORY
# ============================================================

resource "aws_ecr_repository" "document_api" {
  name                 = "cloudsec-document-api"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
  }

  tags = {
    Name        = "cloudsec-document-api"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# ECR IMAGE LIFECYCLE
# Retain the 10 most recent tagged images.
# Expire untagged images after 7 days.
# ============================================================

resource "aws_ecr_lifecycle_policy" "document_api" {
  repository = aws_ecr_repository.document_api.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after 7 days"

        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }

        action = {
          type = "expire"
        }
      },
      {
        rulePriority = 2
        description  = "Retain the 10 most recent tagged images"

        selection = {
          tagStatus      = "tagged"
          tagPatternList = ["*"]
          countType      = "imageCountMoreThan"
          countNumber    = 10
        }

        action = {
          type = "expire"
        }
      }
    ]
  })
}


# ============================================================
# OUTPUTS
# ============================================================

output "ecr_repository_url" {
  description = "Private ECR repository URL for the document API."
  value       = aws_ecr_repository.document_api.repository_url
}

output "ecr_repository_arn" {
  description = "Private ECR repository ARN."
  value       = aws_ecr_repository.document_api.arn
}
