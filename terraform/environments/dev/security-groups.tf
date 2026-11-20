# ==========================================
# APPLICATION LOAD BALANCER SECURITY GROUP
# ==========================================

resource "aws_security_group" "alb" {
  name        = "cloudsec-alb-sg"
  description = "Allows traffic only from API Gateway VPC Link"
  vpc_id      = aws_vpc.main.id

  egress = []

  lifecycle {
    ignore_changes = [egress]
  }

  tags = {
    Name        = "cloudsec-alb-sg"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ==========================================
# APPLICATION EC2 SECURITY GROUP
# ==========================================

resource "aws_security_group" "app" {
  name        = "cloudsec-app-sg"
  description = "Allows application traffic only from ALB"
  vpc_id      = aws_vpc.main.id

  egress = []

  lifecycle {
    ignore_changes = [egress]
  }

  tags = {
    Name        = "cloudsec-app-sg"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ==========================================
# API GATEWAY VPC LINK SECURITY GROUP
# ==========================================

resource "aws_security_group" "api_gateway_vpc_link" {
  name        = "cloudsec-api-vpc-link-sg"
  description = "Controls API Gateway VPC Link access to internal ALB"
  vpc_id      = aws_vpc.main.id

  egress = []

  lifecycle {
    ignore_changes = [egress]
  }

  tags = {
    Name        = "cloudsec-api-vpc-link-sg"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ==========================================
# VPC LINK INBOUND RULES
# ==========================================

resource "aws_vpc_security_group_egress_rule" "vpc_link_to_alb" {
  security_group_id = aws_security_group.api_gateway_vpc_link.id

  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = 80
  to_port                      = 80
  ip_protocol                  = "tcp"

  description = "Allow VPC Link to reach internal ALB"
}


# ==========================================
# ALB INBOUND - ONLY FROM VPC LINK
# ==========================================

resource "aws_vpc_security_group_ingress_rule" "alb_from_vpc_link" {

  #checkov:skip=CKV_AWS_260:Ingress is restricted to the API Gateway VPC Link security group through referenced_security_group_id; no public CIDR ingress is permitted.

  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.api_gateway_vpc_link.id
  from_port                    = 80
  to_port                      = 80
  ip_protocol                  = "tcp"
  description                  = "Allow HTTP only from API Gateway VPC Link"
}


# ==========================================
# ALB OUTBOUND - HTTP TO APPLICATION
# ==========================================

resource "aws_vpc_security_group_egress_rule" "alb_to_app" {
  security_group_id = aws_security_group.alb.id

  referenced_security_group_id = aws_security_group.app.id
  from_port                    = 8080
  to_port                      = 8080
  ip_protocol                  = "tcp"

  description = "Allow ALB to communicate with application instances"
}


# ==========================================
# APPLICATION INBOUND - ONLY FROM ALB
# ==========================================

resource "aws_vpc_security_group_ingress_rule" "app_from_alb" {
  security_group_id = aws_security_group.app.id

  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = 8080
  to_port                      = 8080
  ip_protocol                  = "tcp"

  description = "Allow HTTP traffic only from ALB"
}
