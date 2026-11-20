resource "aws_cloudwatch_log_group" "waf" {
  name              = "aws-waf-logs-cloudsec-application"
  retention_in_days = 365
  kms_key_id        = aws_kms_key.waf_logs.arn

  tags = {
    Name        = "cloudsec-waf-logs"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}

resource "aws_wafv2_web_acl_logging_configuration" "application" {
  resource_arn = aws_wafv2_web_acl.application.arn

  log_destination_configs = [
    aws_cloudwatch_log_group.waf.arn
  ]

  redacted_fields {
    single_header {
      name = "authorization"
    }
  }
}
