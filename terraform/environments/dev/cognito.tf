# ============================================================
# COGNITO USER POOL
# ============================================================

resource "aws_cognito_user_pool" "application" {
  name           = "cloudsec-users-dev"
  user_pool_tier = "ESSENTIALS"

  # Email is the user's sign-in identifier.
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  username_configuration {
    case_sensitive = false
  }

  # Only administrators can create accounts.
  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  # Password security baseline.
  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_numbers                  = true
    require_symbols                  = true
    require_uppercase                = true
    temporary_password_validity_days = 7
  }

  # Optional authenticator-app MFA.
  mfa_configuration = "OPTIONAL"

  software_token_mfa_configuration {
    enabled = true
  }

  # Recover accounts through verified email.
  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  # Protect the user directory against accidental deletion.
  deletion_protection = "ACTIVE"

  tags = {
    Name        = "cloudsec-users-dev"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
    DataClass   = "Identity"
  }
}


# ============================================================
# APP CLIENT 1 - BROWSER OIDC / MANAGED LOGIN
# ============================================================

resource "aws_cognito_user_pool_client" "browser_oidc" {
  name         = "cloudsec-browser-oidc"
  user_pool_id = aws_cognito_user_pool.application.id

  generate_secret = false

  # OAuth 2.0 Authorization Code Flow.
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]

  allowed_oauth_scopes = [
    "openid",
    "email",
    "cloudsec-api/access"
  ]

  depends_on = [
    aws_cognito_resource_server.application_api
  ]

  supported_identity_providers = [
    "COGNITO"
  ]

  callback_urls = [
    "http://localhost:5173/auth/callback"
  ]

  logout_urls = [
    "http://localhost:5173/"
  ]

  default_redirect_uri = "http://localhost:5173/auth/callback"

  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true

  # Short-lived access and ID tokens.
  access_token_validity  = 15
  id_token_validity      = 15
  refresh_token_validity = 1

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }

  # Rotate refresh tokens.
  refresh_token_rotation {
    feature                    = "ENABLED"
    retry_grace_period_seconds = 10
  }

  read_attributes = [
    "email",
    "email_verified"
  ]
}


# ============================================================
# APP CLIENT 2 - DIRECT API / SRP AUTHENTICATION
# ============================================================

resource "aws_cognito_user_pool_client" "native_srp" {
  name         = "cloudsec-native-srp"
  user_pool_id = aws_cognito_user_pool.application.id

  generate_secret = false

  # Secure Remote Password authentication.
  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH"
  ]

  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true

  access_token_validity  = 15
  id_token_validity      = 15
  refresh_token_validity = 1

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }

  refresh_token_rotation {
    feature                    = "ENABLED"
    retry_grace_period_seconds = 10
  }

  read_attributes = [
    "email",
    "email_verified"
  ]
}


# ============================================================
# COGNITO MANAGED LOGIN DOMAIN
# ============================================================

resource "aws_cognito_user_pool_domain" "managed_login" {
  domain                = var.cognito_domain_prefix
  user_pool_id          = aws_cognito_user_pool.application.id
  managed_login_version = 2
}


# ============================================================
# DEFAULT MANAGED LOGIN BRANDING
# ============================================================

resource "aws_cognito_managed_login_branding" "browser" {
  user_pool_id = aws_cognito_user_pool.application.id
  client_id    = aws_cognito_user_pool_client.browser_oidc.id

  use_cognito_provided_values = true
}


# ============================================================
# COGNITO OUTPUTS
# ============================================================

output "cognito_user_pool_id" {
  description = "Cognito User Pool ID."
  value       = aws_cognito_user_pool.application.id
}

output "cognito_issuer_url" {
  description = "OIDC issuer URL for JWT validation."
  value       = "https://cognito-idp.ap-south-1.amazonaws.com/${aws_cognito_user_pool.application.id}"
}

output "cognito_managed_login_domain" {
  description = "Cognito Managed Login domain."
  value       = "https://${var.cognito_domain_prefix}.auth.ap-south-1.amazoncognito.com"
}

output "cognito_browser_client_id" {
  description = "Public OIDC browser App Client ID."
  value       = aws_cognito_user_pool_client.browser_oidc.id
}

output "cognito_srp_client_id" {
  description = "Public SRP authentication App Client ID."
  value       = aws_cognito_user_pool_client.native_srp.id
}


# ============================================================
# COGNITO RESOURCE SERVER - APPLICATION API
# ============================================================

resource "aws_cognito_resource_server" "application_api" {
  identifier   = "cloudsec-api"
  name         = "CloudSec Document API"
  user_pool_id = aws_cognito_user_pool.application.id

  scope {
    scope_name        = "access"
    scope_description = "Access the Secure Document Exchange API."
  }
}
