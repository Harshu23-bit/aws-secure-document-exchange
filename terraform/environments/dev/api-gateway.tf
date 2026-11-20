# ==========================================
# API GATEWAY VPC LINK V2
# ==========================================

resource "aws_apigatewayv2_vpc_link" "application" {
  name = "cloudsec-api-vpc-link"

  security_group_ids = [
    aws_security_group.api_gateway_vpc_link.id
  ]

  subnet_ids = [
    aws_subnet.private_a.id,
    aws_subnet.private_b.id
  ]

  tags = {
    Name        = "cloudsec-api-vpc-link"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ==========================================
# REGIONAL REST API
# ==========================================

resource "aws_api_gateway_rest_api" "application" {

  #checkov:skip=CKV_AWS_237:REST API replacement changes its execute-api endpoint because no custom domain or API mapping is configured. create_before_destroy alone cannot guarantee endpoint continuity; revisit with a stable custom-domain deployment strategy.

  name        = "cloudsec-document-api"
  description = "Public HTTPS entry point for the Secure Document Exchange API"

  endpoint_configuration {
    types = ["REGIONAL"]
  }

  tags = {
    Name        = "cloudsec-document-api"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}



# ==========================================
# COGNITO USER POOL AUTHORIZER
# ==========================================

resource "aws_api_gateway_authorizer" "cognito" {
  name          = "cloudsec-cognito-authorizer"
  rest_api_id   = aws_api_gateway_rest_api.application.id
  type          = "COGNITO_USER_POOLS"
  provider_arns = [aws_cognito_user_pool.application.arn]

  identity_source = "method.request.header.Authorization"
}


# ==========================================
# API GATEWAY ERROR RESPONSE CORS
# ==========================================

resource "aws_api_gateway_gateway_response" "default_4xx" {
  rest_api_id   = aws_api_gateway_rest_api.application.id
  response_type = "DEFAULT_4XX"

  response_parameters = {
    "gatewayresponse.header.Access-Control-Allow-Origin"  = "'${var.api_gateway_cors_origin}'"
    "gatewayresponse.header.Access-Control-Allow-Methods" = "'GET,POST,PUT,PATCH,DELETE,OPTIONS'"
    "gatewayresponse.header.Access-Control-Allow-Headers" = "'Authorization,Content-Type,Accept'"
  }
}

resource "aws_api_gateway_gateway_response" "default_5xx" {
  rest_api_id   = aws_api_gateway_rest_api.application.id
  response_type = "DEFAULT_5XX"

  response_parameters = {
    "gatewayresponse.header.Access-Control-Allow-Origin"  = "'${var.api_gateway_cors_origin}'"
    "gatewayresponse.header.Access-Control-Allow-Methods" = "'GET,POST,PUT,PATCH,DELETE,OPTIONS'"
    "gatewayresponse.header.Access-Control-Allow-Headers" = "'Authorization,Content-Type,Accept'"
  }
}


# ==========================================
# CATCH-ALL PROXY RESOURCE
# ==========================================

resource "aws_api_gateway_resource" "proxy" {
  rest_api_id = aws_api_gateway_rest_api.application.id
  parent_id   = aws_api_gateway_rest_api.application.root_resource_id
  path_part   = "{proxy+}"
}

resource "aws_api_gateway_request_validator" "proxy" {
  name                        = "cloudsec-proxy-request-validator"
  rest_api_id                 = aws_api_gateway_rest_api.application.id
  validate_request_body       = false
  validate_request_parameters = true
}


# ==========================================
# PROXY METHOD
# ==========================================

resource "aws_api_gateway_method" "proxy" {
  rest_api_id          = aws_api_gateway_rest_api.application.id
  resource_id          = aws_api_gateway_resource.proxy.id
  http_method          = "ANY"
  authorization        = "COGNITO_USER_POOLS"
  authorizer_id        = aws_api_gateway_authorizer.cognito.id
  authorization_scopes = ["cloudsec-api/access"]
  request_validator_id = aws_api_gateway_request_validator.proxy.id

  request_parameters = {
    "method.request.path.proxy" = true
  }
}


# ==========================================
# PROXY PRIVATE INTEGRATION
# ==========================================

resource "aws_api_gateway_integration" "proxy" {
  rest_api_id = aws_api_gateway_rest_api.application.id
  resource_id = aws_api_gateway_resource.proxy.id
  http_method = aws_api_gateway_method.proxy.http_method

  integration_http_method = "ANY"
  type                    = "HTTP_PROXY"
  connection_type         = "VPC_LINK"
  connection_id           = aws_apigatewayv2_vpc_link.application.id
  integration_target      = aws_lb.application.arn

  uri = "http://${aws_lb.application.dns_name}"

  request_parameters = {
    "integration.request.path.proxy" = "method.request.path.proxy"
  }

  passthrough_behavior = "WHEN_NO_MATCH"
}


# ==========================================
# ROOT METHOD
# ==========================================

resource "aws_api_gateway_method" "root" {

  #checkov:skip=CKV2_AWS_53:Root method has no path parameters; application-level FastAPI validation handles request inputs.

  rest_api_id          = aws_api_gateway_rest_api.application.id
  resource_id          = aws_api_gateway_rest_api.application.root_resource_id
  http_method          = "ANY"
  authorization        = "COGNITO_USER_POOLS"
  authorizer_id        = aws_api_gateway_authorizer.cognito.id
  authorization_scopes = ["cloudsec-api/access"]
}


# ==========================================
# ROOT PRIVATE INTEGRATION
# ==========================================

resource "aws_api_gateway_integration" "root" {
  rest_api_id = aws_api_gateway_rest_api.application.id
  resource_id = aws_api_gateway_rest_api.application.root_resource_id
  http_method = aws_api_gateway_method.root.http_method

  integration_http_method = "ANY"
  type                    = "HTTP_PROXY"
  connection_type         = "VPC_LINK"
  connection_id           = aws_apigatewayv2_vpc_link.application.id
  integration_target      = aws_lb.application.arn

  uri = "http://${aws_lb.application.dns_name}"

  passthrough_behavior = "WHEN_NO_MATCH"
}



# ==========================================
# CORS PREFLIGHT - PROXY RESOURCE
# ==========================================

resource "aws_api_gateway_method" "proxy_options" {

  #checkov:skip=CKV2_AWS_53:CORS preflight uses a MOCK integration and has no backend request parameters requiring validation.

  rest_api_id   = aws_api_gateway_rest_api.application.id
  resource_id   = aws_api_gateway_resource.proxy.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "proxy_options" {
  rest_api_id = aws_api_gateway_rest_api.application.id
  resource_id = aws_api_gateway_resource.proxy.id
  http_method = aws_api_gateway_method.proxy_options.http_method

  type = "MOCK"

  request_templates = {
    "application/json" = "{\"statusCode\": 200}"
  }
}

resource "aws_api_gateway_method_response" "proxy_options_200" {
  rest_api_id = aws_api_gateway_rest_api.application.id
  resource_id = aws_api_gateway_resource.proxy.id
  http_method = aws_api_gateway_method.proxy_options.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true
    "method.response.header.Access-Control-Allow-Methods" = true
    "method.response.header.Access-Control-Allow-Origin"  = true
  }
}

resource "aws_api_gateway_integration_response" "proxy_options_200" {
  rest_api_id = aws_api_gateway_rest_api.application.id
  resource_id = aws_api_gateway_resource.proxy.id
  http_method = aws_api_gateway_method.proxy_options.http_method
  status_code = aws_api_gateway_method_response.proxy_options_200.status_code

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = "'Authorization,Content-Type,Accept'"
    "method.response.header.Access-Control-Allow-Methods" = "'GET,POST,PUT,PATCH,DELETE,OPTIONS'"
    "method.response.header.Access-Control-Allow-Origin"  = "'${var.api_gateway_cors_origin}'"
  }
}


# ==========================================
# CORS PREFLIGHT - ROOT RESOURCE
# ==========================================

resource "aws_api_gateway_method" "root_options" {

  #checkov:skip=CKV2_AWS_53:CORS preflight uses a MOCK integration and has no backend request parameters requiring validation.

  rest_api_id   = aws_api_gateway_rest_api.application.id
  resource_id   = aws_api_gateway_rest_api.application.root_resource_id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "root_options" {
  rest_api_id = aws_api_gateway_rest_api.application.id
  resource_id = aws_api_gateway_rest_api.application.root_resource_id
  http_method = aws_api_gateway_method.root_options.http_method

  type = "MOCK"

  request_templates = {
    "application/json" = "{\"statusCode\": 200}"
  }
}

resource "aws_api_gateway_method_response" "root_options_200" {
  rest_api_id = aws_api_gateway_rest_api.application.id
  resource_id = aws_api_gateway_rest_api.application.root_resource_id
  http_method = aws_api_gateway_method.root_options.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true
    "method.response.header.Access-Control-Allow-Methods" = true
    "method.response.header.Access-Control-Allow-Origin"  = true
  }
}

resource "aws_api_gateway_integration_response" "root_options_200" {
  rest_api_id = aws_api_gateway_rest_api.application.id
  resource_id = aws_api_gateway_rest_api.application.root_resource_id
  http_method = aws_api_gateway_method.root_options.http_method
  status_code = aws_api_gateway_method_response.root_options_200.status_code

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = "'Authorization,Content-Type,Accept'"
    "method.response.header.Access-Control-Allow-Methods" = "'GET,POST,PUT,PATCH,DELETE,OPTIONS'"
    "method.response.header.Access-Control-Allow-Origin"  = "'${var.api_gateway_cors_origin}'"
  }
}


# ==========================================
# API DEPLOYMENT
# ==========================================

resource "aws_api_gateway_deployment" "application" {
  rest_api_id = aws_api_gateway_rest_api.application.id

  triggers = {
    redeployment = sha1(jsonencode({
      proxy_resource                     = aws_api_gateway_resource.proxy
      proxy_request_validator            = aws_api_gateway_request_validator.proxy
      proxy_method                       = aws_api_gateway_method.proxy
      proxy_integration                  = aws_api_gateway_integration.proxy
      root_method                        = aws_api_gateway_method.root
      root_integration                   = aws_api_gateway_integration.root
      authorizer                         = aws_api_gateway_authorizer.cognito
      default_4xx_gateway_response       = aws_api_gateway_gateway_response.default_4xx
      default_5xx_gateway_response       = aws_api_gateway_gateway_response.default_5xx
      proxy_options_method               = aws_api_gateway_method.proxy_options
      proxy_options_integration          = aws_api_gateway_integration.proxy_options
      proxy_options_method_response      = aws_api_gateway_method_response.proxy_options_200
      proxy_options_integration_response = aws_api_gateway_integration_response.proxy_options_200
      root_options_method                = aws_api_gateway_method.root_options
      root_options_integration           = aws_api_gateway_integration.root_options
      root_options_method_response       = aws_api_gateway_method_response.root_options_200
      root_options_integration_response  = aws_api_gateway_integration_response.root_options_200
    }))
  }

  depends_on = [
    aws_api_gateway_request_validator.proxy,
    aws_api_gateway_integration.proxy,
    aws_api_gateway_integration.root,
    aws_api_gateway_integration_response.proxy_options_200,
    aws_api_gateway_integration_response.root_options_200,
    aws_api_gateway_gateway_response.default_4xx,
    aws_api_gateway_gateway_response.default_5xx
  ]

  lifecycle {
    create_before_destroy = true
  }
}


# ==========================================
# API STAGE
# ==========================================

resource "aws_api_gateway_stage" "application" {

  #checkov:skip=CKV_AWS_73:X-Ray tracing is deferred because the FastAPI application has no distributed tracing instrumentation. API Gateway access logs, integration latency metrics, CloudWatch alarms, CloudTrail, and WAF logs provide current observability.

  #checkov:skip=CKV2_AWS_51:This policy requires an API Gateway client certificate for backend authentication, not browser-to-API mTLS. The current VPC Link integration uses HTTP to an internal ALB; Cognito authorizes API callers. Revisit with an HTTPS backend and certificate-based service authentication.

  #checkov:skip=CKV_AWS_120:API Gateway caching is intentionally disabled for this authenticated multi-tenant document API. Tenant-scoped authorization, document permissions, and frequently changing membership and document states make shared response caching an unnecessary data-isolation and staleness risk. Avoids additional API Gateway cache charges.

  rest_api_id   = aws_api_gateway_rest_api.application.id
  deployment_id = aws_api_gateway_deployment.application.id
  stage_name    = "api"

  xray_tracing_enabled = false

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gateway_access.arn

    format = jsonencode({
      requestId          = "$context.requestId"
      extendedRequestId  = "$context.extendedRequestId"
      sourceIp           = "$context.identity.sourceIp"
      requestTime        = "$context.requestTime"
      httpMethod         = "$context.httpMethod"
      resourcePath       = "$context.resourcePath"
      path               = "$context.path"
      status             = "$context.status"
      protocol           = "$context.protocol"
      responseLength     = "$context.responseLength"
      responseLatency    = "$context.responseLatency"
      integrationStatus  = "$context.integration.status"
      integrationLatency = "$context.integration.latency"
    })
  }

  depends_on = [
    aws_api_gateway_account.application
  ]

  tags = {
    Name        = "cloudsec-api-stage"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ==========================================
# API GATEWAY EXECUTION LOGGING
# ==========================================

resource "aws_api_gateway_method_settings" "application" {

  #checkov:skip=CKV_AWS_225:Method-level caching is intentionally disabled to prevent stale or incorrectly scoped responses in the authenticated multi-tenant API. Authorization and document access decisions must be evaluated against current application state.

  rest_api_id = aws_api_gateway_rest_api.application.id
  stage_name  = aws_api_gateway_stage.application.stage_name
  method_path = "*/*"

  settings {
    logging_level      = "ERROR"
    data_trace_enabled = false
    metrics_enabled    = true
  }
}


# ==========================================
# WAF ASSOCIATION - API GATEWAY STAGE
# ==========================================

resource "aws_wafv2_web_acl_association" "api_gateway" {
  resource_arn = "arn:aws:apigateway:${data.aws_region.current.region}::/restapis/${aws_api_gateway_rest_api.application.id}/stages/${aws_api_gateway_stage.application.stage_name}"

  web_acl_arn = aws_wafv2_web_acl.application.arn
}


# ==========================================
# API GATEWAY OUTPUTS
# ==========================================

output "application_api_gateway_id" {
  description = "ID of the public API Gateway REST API."
  value       = aws_api_gateway_rest_api.application.id
}

output "application_api_gateway_invoke_url" {
  description = "HTTPS invoke URL of the public API Gateway stage."
  value       = aws_api_gateway_stage.application.invoke_url
}

output "application_vpc_link_id" {
  description = "ID of the API Gateway VPC Link V2."
  value       = aws_apigatewayv2_vpc_link.application.id
}


# ==========================================
# API GATEWAY CLOUDWATCH ACCESS LOGGING
# ==========================================

resource "aws_cloudwatch_log_group" "api_gateway_access" {
  name              = "/aws/apigateway/cloudsec-document-api"
  retention_in_days = 365
  kms_key_id        = aws_kms_key.application_logs.arn

  tags = {
    Name        = "cloudsec-api-gateway-access"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


# ==========================================
# API GATEWAY CLOUDWATCH IAM ROLE
# ==========================================

resource "aws_iam_role" "api_gateway_cloudwatch" {
  name        = "cloudsec-api-gateway-cloudwatch"
  description = "Allows API Gateway to publish execution and access logs to CloudWatch."

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "apigateway.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name        = "cloudsec-api-gateway-cloudwatch"
    Environment = "dev"
    Project     = "AWS-Secure-Infrastructure"
  }
}


resource "aws_iam_role_policy_attachment" "api_gateway_cloudwatch" {
  role = aws_iam_role.api_gateway_cloudwatch.name

  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonAPIGatewayPushToCloudWatchLogs"
}


# ==========================================
# REGIONAL API GATEWAY ACCOUNT LOGGING ROLE
# ==========================================

resource "aws_api_gateway_account" "application" {
  cloudwatch_role_arn = aws_iam_role.api_gateway_cloudwatch.arn

  depends_on = [
    aws_iam_role_policy_attachment.api_gateway_cloudwatch
  ]
}
