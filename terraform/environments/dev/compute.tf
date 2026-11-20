# ==========================================
# LATEST AMAZON LINUX 2023 AMI
# ==========================================

data "aws_ssm_parameter" "amazon_linux_2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}


# ==========================================
# EC2 LAUNCH TEMPLATE
# ==========================================

resource "aws_launch_template" "application" {
  name_prefix = "cloudsec-application-"
  description = "Secure launch template for private application instances"

  image_id      = data.aws_ssm_parameter.amazon_linux_2023.value
  instance_type = "t3.small"

  user_data = base64encode(templatefile(
    "${path.module}/../../../scripts/bootstrap.sh.tftpl",
    {
      ecr_repository_url       = aws_ecr_repository.document_api.repository_url
      application_image_digest = var.application_image_digest != null ? var.application_image_digest : ""
      aws_region               = "ap-south-1"
      submissions_table_name   = aws_dynamodb_table.submissions.name
      memberships_table_name   = aws_dynamodb_table.tenant_memberships.name
      audit_events_table_name  = aws_dynamodb_table.audit_events.name
      documents_bucket_name    = aws_s3_bucket.application.id
      documents_kms_key_arn    = aws_kms_key.application.arn
      cognito_region           = "ap-south-1"
      cognito_user_pool_id     = aws_cognito_user_pool.application.id
      cognito_api_client_id    = aws_cognito_user_pool_client.browser_oidc.id
      jwks_bucket_name         = aws_s3_bucket.identity_metadata.id
      jwks_object_key          = "security/jwks.json"
    }
  ))

  network_interfaces {
    device_index                = 0
    associate_public_ip_address = false

    security_groups = [
      aws_security_group.app.id
    ]
  }

  iam_instance_profile {
    name = aws_iam_instance_profile.ec2_ssm.name
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  block_device_mappings {
    device_name = "/dev/xvda"

    ebs {
      volume_size           = 12
      volume_type           = "gp3"
      encrypted             = true
      delete_on_termination = true
    }
  }

  monitoring {
    enabled = false
  }

  tag_specifications {
    resource_type = "instance"

    tags = {
      Name        = "cloudsec-application-instance"
      Environment = "dev"
      Project     = "AWS-Secure-Infrastructure"
    }
  }

  tag_specifications {
    resource_type = "volume"

    tags = {
      Name        = "cloudsec-application-volume"
      Environment = "dev"
      Project     = "AWS-Secure-Infrastructure"
    }
  }

  tags = {
    Name        = "cloudsec-application-launch-template"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}
