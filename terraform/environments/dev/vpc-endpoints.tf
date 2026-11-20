# SECURITY GROUP FOR SSM INTERFACE ENDPOINTS

resource "aws_security_group" "ssm_endpoints" {
  name        = "cloudsec-ssm-endpoints-sg"
  description = "Allows HTTPS from private application instances to SSM endpoints"
  vpc_id      = aws_vpc.main.id

  egress = []

  tags = {
    Name        = "cloudsec-ssm-endpoints-sg"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# SSM ENDPOINT INBOUND - HTTPS FROM APPLICATION INSTANCES

resource "aws_vpc_security_group_ingress_rule" "ssm_from_app" {
  security_group_id = aws_security_group.ssm_endpoints.id

  referenced_security_group_id = aws_security_group.app.id
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"

  description = "Allow HTTPS from private application instances"
}


# APPLICATION OUTBOUND - HTTPS TO SSM ENDPOINTS

resource "aws_vpc_security_group_egress_rule" "app_to_ssm" {
  security_group_id = aws_security_group.app.id

  referenced_security_group_id = aws_security_group.ssm_endpoints.id
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"

  description = "Allow HTTPS to SSM interface endpoints"
}


# SSM INTERFACE ENDPOINT

resource "aws_vpc_endpoint" "ssm" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.ap-south-1.ssm"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private_a.id]
  security_group_ids  = [aws_security_group.ssm_endpoints.id]
  private_dns_enabled = true

  tags = {
    Name        = "cloudsec-ssm-endpoint"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# SSM MESSAGES INTERFACE ENDPOINT

resource "aws_vpc_endpoint" "ssmmessages" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.ap-south-1.ssmmessages"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private_a.id]
  security_group_ids  = [aws_security_group.ssm_endpoints.id]
  private_dns_enabled = true

  tags = {
    Name        = "cloudsec-ssmmessages-endpoint"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# S3 GATEWAY ENDPOINT

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.ap-south-1.s3"
  vpc_endpoint_type = "Gateway"

  route_table_ids = [
    aws_route_table.private.id
  ]

  tags = {
    Name        = "cloudsec-s3-endpoint"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# APPLICATION OUTBOUND - HTTPS TO S3 THROUGH GATEWAY ENDPOINT

resource "aws_vpc_security_group_egress_rule" "app_to_s3" {
  security_group_id = aws_security_group.app.id

  prefix_list_id = aws_vpc_endpoint.s3.prefix_list_id
  from_port      = 443
  to_port        = 443
  ip_protocol    = "tcp"

  description = "Allow HTTPS to S3 through the VPC gateway endpoint"
}


# DYNAMODB GATEWAY ENDPOINT

resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.ap-south-1.dynamodb"
  vpc_endpoint_type = "Gateway"

  route_table_ids = [
    aws_route_table.private.id
  ]

  tags = {
    Name        = "cloudsec-dynamodb-endpoint"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# APPLICATION OUTBOUND - HTTPS TO DYNAMODB

resource "aws_vpc_security_group_egress_rule" "app_to_dynamodb" {
  security_group_id = aws_security_group.app.id

  prefix_list_id = aws_vpc_endpoint.dynamodb.prefix_list_id
  from_port      = 443
  to_port        = 443
  ip_protocol    = "tcp"

  description = "Allow HTTPS to DynamoDB through the VPC gateway endpoint"
}


# ============================================================
# ECR INTERFACE ENDPOINT SECURITY GROUP
# ============================================================

resource "aws_security_group" "ecr_endpoints" {
  name        = "cloudsec-ecr-endpoints-sg"
  description = "Allows private application instances to access ECR over HTTPS"
  vpc_id      = aws_vpc.main.id

  egress = []

  tags = {
    Name        = "cloudsec-ecr-endpoints-sg"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# ECR ENDPOINT INBOUND - HTTPS FROM APPLICATION INSTANCES
# ============================================================

resource "aws_vpc_security_group_ingress_rule" "ecr_from_app" {
  security_group_id = aws_security_group.ecr_endpoints.id

  referenced_security_group_id = aws_security_group.app.id
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"

  description = "Allow HTTPS from application instances to ECR endpoints"
}


# ============================================================
# APPLICATION OUTBOUND - HTTPS TO ECR ENDPOINTS
# ============================================================

resource "aws_vpc_security_group_egress_rule" "app_to_ecr" {
  security_group_id = aws_security_group.app.id

  referenced_security_group_id = aws_security_group.ecr_endpoints.id
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"

  description = "Allow HTTPS to private ECR interface endpoints"
}


# ============================================================
# ECR API INTERFACE ENDPOINT
# ============================================================

resource "aws_vpc_endpoint" "ecr_api" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.ap-south-1.ecr.api"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private_a.id]
  security_group_ids  = [aws_security_group.ecr_endpoints.id]
  private_dns_enabled = true

  tags = {
    Name        = "cloudsec-ecr-api-endpoint"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ============================================================
# ECR DOCKER REGISTRY INTERFACE ENDPOINT
# ============================================================

resource "aws_vpc_endpoint" "ecr_dkr" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.ap-south-1.ecr.dkr"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private_a.id]
  security_group_ids  = [aws_security_group.ecr_endpoints.id]
  private_dns_enabled = true

  tags = {
    Name        = "cloudsec-ecr-dkr-endpoint"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}
