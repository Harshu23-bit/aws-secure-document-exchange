# ==========================================
# CLOUDTRAIL SECURITY DETECTION LOCALS
# ==========================================

locals {
  cloudtrail_security_metric_namespace = "CloudSec/CloudTrailSecurity"

  cloudtrail_security_detections = {

    # --------------------------------------
    # 1. ROOT ACCOUNT USAGE
    # --------------------------------------

    root_account_usage = {
      metric_name = "RootAccountUsage"
      alarm_name  = "cloudsec-root-account-usage"

      description = "Detects CloudTrail events performed using root account credentials."

      filter_pattern = "{ $.userIdentity.type = \"Root\" }"
    }

    # --------------------------------------
    # 2. FAILED CONSOLE SIGN-INS
    # --------------------------------------

    failed_console_signins = {
      metric_name = "FailedConsoleSignIns"
      alarm_name  = "cloudsec-failed-console-signins"

      description = "Detects unsuccessful AWS Management Console sign-in attempts."

      filter_pattern = "{ $.eventSource = \"signin.amazonaws.com\" && $.eventName = \"ConsoleLogin\" && $.responseElements.ConsoleLogin = \"Failure\" }"
    }

    # --------------------------------------
    # 3. UNAUTHORIZED API CALLS
    # --------------------------------------

    unauthorized_api_calls = {
      metric_name = "UnauthorizedApiCalls"
      alarm_name  = "cloudsec-unauthorized-api-calls"

      description = "Detects API calls rejected due to access-denied or unauthorized-operation errors."

      filter_pattern = "{ $.errorCode = \"*AccessDenied*\" || $.errorCode = \"*UnauthorizedOperation*\" }"
    }

    # --------------------------------------
    # 4. IAM POLICY CHANGES
    # --------------------------------------

    iam_policy_changes = {
      metric_name = "IamPolicyChanges"
      alarm_name  = "cloudsec-iam-policy-changes"

      description = "Detects IAM policy creation, modification, attachment, detachment and deletion."

      filter_pattern = "{ $.eventSource = \"iam.amazonaws.com\" && ($.eventName = \"CreatePolicy\" || $.eventName = \"CreatePolicyVersion\" || $.eventName = \"DeletePolicy\" || $.eventName = \"DeletePolicyVersion\" || $.eventName = \"SetDefaultPolicyVersion\" || $.eventName = \"AttachGroupPolicy\" || $.eventName = \"AttachRolePolicy\" || $.eventName = \"AttachUserPolicy\" || $.eventName = \"DetachGroupPolicy\" || $.eventName = \"DetachRolePolicy\" || $.eventName = \"DetachUserPolicy\" || $.eventName = \"PutGroupPolicy\" || $.eventName = \"PutRolePolicy\" || $.eventName = \"PutUserPolicy\" || $.eventName = \"DeleteGroupPolicy\" || $.eventName = \"DeleteRolePolicy\" || $.eventName = \"DeleteUserPolicy\" || $.eventName = \"UpdateAssumeRolePolicy\") }"
    }

    # --------------------------------------
    # 5. IAM IDENTITY AND CREDENTIAL CHANGES
    # --------------------------------------

    iam_identity_and_credential_changes = {
      metric_name = "IamIdentityCredentialChanges"
      alarm_name  = "cloudsec-iam-identity-credential-changes"

      description = "Detects IAM user, role, access key, console credential, group membership and MFA device changes."

      filter_pattern = "{ $.eventSource = \"iam.amazonaws.com\" && ($.eventName = \"CreateUser\" || $.eventName = \"DeleteUser\" || $.eventName = \"CreateRole\" || $.eventName = \"DeleteRole\" || $.eventName = \"CreateAccessKey\" || $.eventName = \"UpdateAccessKey\" || $.eventName = \"DeleteAccessKey\" || $.eventName = \"CreateLoginProfile\" || $.eventName = \"UpdateLoginProfile\" || $.eventName = \"DeleteLoginProfile\" || $.eventName = \"AddUserToGroup\" || $.eventName = \"RemoveUserFromGroup\" || $.eventName = \"CreateVirtualMFADevice\" || $.eventName = \"EnableMFADevice\" || $.eventName = \"DeactivateMFADevice\" || $.eventName = \"DeleteVirtualMFADevice\" || $.eventName = \"ResyncMFADevice\") }"
    }

    # --------------------------------------
    # 6. SECURITY GROUP CHANGES
    # --------------------------------------

    security_group_changes = {
      metric_name = "SecurityGroupChanges"
      alarm_name  = "cloudsec-security-group-changes"

      description = "Detects creation, deletion and ingress or egress rule modifications of security groups."

      filter_pattern = "{ $.eventSource = \"ec2.amazonaws.com\" && ($.eventName = \"CreateSecurityGroup\" || $.eventName = \"DeleteSecurityGroup\" || $.eventName = \"AuthorizeSecurityGroupIngress\" || $.eventName = \"AuthorizeSecurityGroupEgress\" || $.eventName = \"RevokeSecurityGroupIngress\" || $.eventName = \"RevokeSecurityGroupEgress\" || $.eventName = \"ModifySecurityGroupRules\") }"
    }

    # --------------------------------------
    # 7. CLOUDTRAIL TAMPERING
    # --------------------------------------

    cloudtrail_tampering = {
      metric_name = "CloudTrailTampering"
      alarm_name  = "cloudsec-cloudtrail-tampering"

      description = "Detects attempts to stop, delete or modify CloudTrail logging configuration."

      filter_pattern = "{ $.eventSource = \"cloudtrail.amazonaws.com\" && ($.eventName = \"StopLogging\" || $.eventName = \"DeleteTrail\" || $.eventName = \"UpdateTrail\" || $.eventName = \"PutEventSelectors\" || $.eventName = \"PutInsightSelectors\") }"
    }
  }
}

# ==========================================
# CLOUDTRAIL LOG METRIC FILTERS
# ==========================================

resource "aws_cloudwatch_log_metric_filter" "security" {
  for_each = local.cloudtrail_security_detections

  name           = "cloudsec-${each.key}"
  log_group_name = aws_cloudwatch_log_group.cloudtrail.name

  pattern = each.value.filter_pattern

  metric_transformation {
    name          = each.value.metric_name
    namespace     = local.cloudtrail_security_metric_namespace
    value         = "1"
    default_value = 0
  }
}

# ==========================================
# CLOUDWATCH SECURITY ALARMS
# ==========================================

resource "aws_cloudwatch_metric_alarm" "security" {
  for_each = local.cloudtrail_security_detections

  alarm_name        = each.value.alarm_name
  alarm_description = each.value.description

  comparison_operator = "GreaterThanThreshold"

  evaluation_periods  = 1
  datapoints_to_alarm = 1

  metric_name = each.value.metric_name
  namespace   = local.cloudtrail_security_metric_namespace

  period    = 300
  statistic = "Sum"

  threshold = 0

  treat_missing_data = "notBreaching"

  actions_enabled = true

  alarm_actions = [
    aws_sns_topic.security_alerts.arn
  ]

  tags = {
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
    Purpose     = "CloudTrail Security Detection"
    Detection   = each.key
  }

  depends_on = [
    aws_sns_topic_policy.security_alerts
  ]
}
