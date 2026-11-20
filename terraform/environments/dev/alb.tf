# ==========================================
# INTERNAL APPLICATION LOAD BALANCER
# ==========================================

resource "aws_lb" "application" {

  #checkov:skip=CKV2_AWS_20:Internal ALB accepts traffic only from the API Gateway VPC Link security group. No public HTTP ingress exists. HTTPS redirection requires a configured TLS listener and backend certificate strategy; revisit with internal TLS implementation.

  name               = "cloudsec-application-alb"
  internal           = true
  load_balancer_type = "application"

  security_groups = [
    aws_security_group.alb.id
  ]

  subnets = [
    aws_subnet.private_a.id,
    aws_subnet.private_b.id
  ]

  drop_invalid_header_fields = true

  access_logs {
    bucket  = aws_s3_bucket.s3_access_logs.id
    prefix  = "alb"
    enabled = true
  }

  enable_deletion_protection = true

  tags = {
    Name        = "cloudsec-application-alb"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }

  depends_on = [
    aws_s3_bucket_policy.s3_access_logs
  ]
}


# ==========================================
# APPLICATION TARGET GROUP
# ==========================================

resource "aws_lb_target_group" "application" {

  #checkov:skip=CKV_AWS_378:Target traffic uses HTTP within private subnets and is restricted to the ALB security group. Backend instances expose no public ingress. Internal transport encryption remains a documented residual risk pending certificate lifecycle implementation.

  name        = "cloudsec-application-tg"
  port        = 8080
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "instance"

  health_check {
    enabled             = true
    protocol            = "HTTP"
    path                = "/health"
    port                = "traffic-port"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }

  tags = {
    Name        = "cloudsec-application-tg"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ==========================================
# INTERNAL HTTP LISTENER
# ==========================================

resource "aws_lb_listener" "http" {

  #checkov:skip=CKV_AWS_2:Internal ALB HTTP listener accepts traffic only from the API Gateway VPC Link security group. Public HTTPS terminates at Regional API Gateway. Internal VPC Link-to-ALB traffic remains unencrypted and is a documented residual risk.

  #checkov:skip=CKV_AWS_103:TLS policy is not applicable because this internal ALB currently has no HTTPS listener. Revisit when a trusted internal certificate and HTTPS backend architecture are implemented.

  load_balancer_arn = aws_lb.application.arn

  port     = 80
  protocol = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.application.arn
  }
}


# ==========================================
# ALB OUTPUTS
# ==========================================

output "application_alb_dns_name" {
  description = "Private DNS name of the internal application load balancer."
  value       = aws_lb.application.dns_name
}

output "application_alb_arn" {
  description = "ARN of the internal application load balancer."
  value       = aws_lb.application.arn
}
