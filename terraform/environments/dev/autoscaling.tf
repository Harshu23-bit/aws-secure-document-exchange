# ==========================================
# APPLICATION AUTO SCALING GROUP
# ==========================================

resource "aws_autoscaling_group" "application" {
  name             = "cloudsec-application-asg"
  min_size         = var.application_image_digest == null ? 0 : 1
  max_size         = 2
  desired_capacity = var.application_image_digest == null ? 0 : 1

  vpc_zone_identifier = [
    aws_subnet.private_a.id,
    aws_subnet.private_b.id
  ]

  target_group_arns = [
    aws_lb_target_group.application.arn
  ]

  health_check_type         = "ELB"
  health_check_grace_period = 300

  launch_template {
    id      = aws_launch_template.application.id
    version = aws_launch_template.application.latest_version
  }

  tag {
    key                 = "Name"
    value               = "cloudsec-application-instance"
    propagate_at_launch = true
  }

  tag {
    key                 = "Environment"
    value               = "dev"
    propagate_at_launch = true
  }

  tag {
    key                 = "Project"
    value               = "AWS-Secure-Infrastructure"
    propagate_at_launch = true
  }
}
