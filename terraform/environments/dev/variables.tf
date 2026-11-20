# ==========================================
# SECURITY NOTIFICATION VARIABLES
# ==========================================

variable "security_alert_email" {
  description = "Optional email address for CloudWatch security alarm notifications."

  type     = string
  default  = null
  nullable = true

  validation {
    condition = (
      var.security_alert_email == null ||
      (
        trimspace(var.security_alert_email) != "" &&
        can(regex("^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$", var.security_alert_email))
      )
    )

    error_message = "security_alert_email must be null or a valid non-empty email address."
  }
}

variable "cloudtrail_delivery_email" {
  description = "Optional email address for CloudTrail log delivery notifications."

  type     = string
  default  = null
  nullable = true

  validation {
    condition = (
      var.cloudtrail_delivery_email == null ||
      (
        trimspace(var.cloudtrail_delivery_email) != "" &&
        can(regex("^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$", var.cloudtrail_delivery_email))
      )
    )

    error_message = "cloudtrail_delivery_email must be null or a valid non-empty email address."
  }
}

# ============================================================
# COGNITO DOMAIN CONFIGURATION
# ============================================================

variable "cognito_domain_prefix" {
  description = "Globally unique Cognito domain prefix for the development User Pool."

  type     = string
  nullable = false

  validation {
    condition = (
      length(var.cognito_domain_prefix) >= 1 &&
      length(var.cognito_domain_prefix) <= 63 &&
      can(regex("^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", var.cognito_domain_prefix))
    )

    error_message = "The Cognito domain prefix must contain 1-63 lowercase letters, numbers, or hyphens, and must not start or end with a hyphen."
  }
}

variable "waf_rate_limit" {
  description = "Maximum API requests per IP during the configured WAF evaluation window."
  type        = number
  default     = 300

  validation {
    condition     = var.waf_rate_limit >= 100
    error_message = "waf_rate_limit must be at least 100."
  }
}

variable "waf_rate_evaluation_window_sec" {
  description = "WAF rate-based rule evaluation window in seconds."
  type        = number
  default     = 300

  validation {
    condition = contains(
      [60, 120, 300, 600],
      var.waf_rate_evaluation_window_sec
    )
    error_message = "The WAF evaluation window must be 60, 120, 300, or 600 seconds."
  }
}


# ============================================================
# IMMUTABLE APPLICATION IMAGE DEPLOYMENT
# ============================================================

variable "application_image_digest" {
  description = "SHA-256 digest of the application image in private ECR. Leave null until the image has been pushed."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = (
      var.application_image_digest == null ||
      can(regex("^sha256:[a-f0-9]{64}$", var.application_image_digest))
    )

    error_message = "application_image_digest must be null or a valid sha256 digest."
  }
}


variable "api_gateway_cors_origin" {
  description = "Allowed browser origin for API Gateway CORS preflight responses."
  type        = string
  default     = "http://localhost:5173"

  validation {
    condition     = can(regex("^https?://[^/]+$", var.api_gateway_cors_origin))
    error_message = "api_gateway_cors_origin must be a single HTTP or HTTPS origin without a path."
  }
}
