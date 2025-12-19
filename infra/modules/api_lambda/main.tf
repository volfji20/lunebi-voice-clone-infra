locals {
  prefix = "${var.project}-${var.env}-${var.region}"
}

resource "aws_cognito_user_pool" "main" {
  name = "${local.prefix}-user-pool"
  
  # Email as username
  username_attributes = ["email"]
  auto_verified_attributes = ["email"]
  
  # Password policy
  password_policy {
    minimum_length    = 8
    require_lowercase = true
    require_numbers   = true
    require_symbols   = true
    require_uppercase = true
  }

  username_configuration {
    case_sensitive = false
  }
    schema {
    name                = "custom_scopes"
    attribute_data_type = "String"
    mutable             = true
    required            = false
    string_attribute_constraints {
      min_length = 1
      max_length = 1000
    }
  }
}

resource "aws_cognito_resource_server" "lunebi_api" {
  identifier   = "lunebi-api"  
  name         = "Lunebi API"
  user_pool_id = aws_cognito_user_pool.main.id

  scope {
    scope_name        = "voices:enroll"
    scope_description = "Enroll voice"
  }

  scope {
    scope_name        = "voices:delete"
    scope_description = "Delete voice"
  }

  scope {
    scope_name        = "stories:prepare"
    scope_description = "Prepare story"
  }

  scope {
    scope_name        = "stories:append"
    scope_description = "Append story"
  }

  scope {
    scope_name        = "stories:status:read"
    scope_description = "Read story status"
  }
  depends_on = [aws_cognito_user_pool.main]
}

# -----------------------------
# Cognito Domain for OAuth2
# -----------------------------
resource "aws_cognito_user_pool_domain" "main" {
  domain       = "${var.project}-${var.env}"  
  user_pool_id = aws_cognito_user_pool.main.id
}

resource "aws_cognito_user_pool_client" "api_client" {
  name            = "${local.prefix}-api-client"
  user_pool_id    = aws_cognito_user_pool.main.id
  generate_secret = true
  
  # ✅ CRITICAL: Use authorization_code grant for proper aud claim
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_scopes = [
    "openid",
    "email",
    "profile",
    "lunebi-api/voices:enroll",
    "lunebi-api/voices:delete", 
    "lunebi-api/stories:prepare",
    "lunebi-api/stories:append",
    "lunebi-api/stories:status:read"
  ]

  allowed_oauth_flows = ["code", "implicit"]
  
  
  # ✅ CRITICAL: Callback URLs required for authorization_code flow
  callback_urls = [
    "https://app.lunebi.com/callback",
    "http://localhost:3000/callback"  # for development
  ]
  
  # ✅ CRITICAL: Supported identity providers
  supported_identity_providers = ["COGNITO"]
  
  # Token configuration
  access_token_validity  = 1  # 1 hour
  id_token_validity      = 1  # 1 hour
  refresh_token_validity = 30 # 30 days

  # Explicit auth flows
  explicit_auth_flows = [
    "ALLOW_REFRESH_TOKEN_AUTH",
    "ALLOW_USER_SRP_AUTH", 
    "ALLOW_CUSTOM_AUTH",
    "ALLOW_USER_PASSWORD_AUTH"
  ]

  # Security
  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true
}

# -----------------------------
# API Gateway (HTTP API)
# -----------------------------
resource "aws_apigatewayv2_api" "http" {
  name          = "${local.prefix}-httpapi"
  protocol_type = "HTTP"

  cors_configuration {
    allow_methods = ["OPTIONS", "GET", "POST"]
    allow_headers = ["Content-Type", "Authorization"]
    allow_origins = ["*"]
  }
}


# -----------------------------
# Routes with Scopes and Authorization
# -----------------------------
resource "aws_apigatewayv2_authorizer" "jwt" {
  api_id           = aws_apigatewayv2_api.http.id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "${local.prefix}-jwt-authorizer"

  jwt_configuration {
    audience = [aws_cognito_user_pool_client.api_client.id]
    issuer   = "https://cognito-idp.${var.region}.amazonaws.com/${aws_cognito_user_pool.main.id}"
  }

  # Wait for Cognito to be fully created
  depends_on = [aws_cognito_user_pool.main]
}

resource "aws_apigatewayv2_route" "voices_enroll" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "POST /voices/enroll"
  target             = "integrations/${aws_apigatewayv2_integration.lambda.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
  
  # Add authorization scopes - FIXED with colons
  authorization_scopes = var.env == "prod" ? ["lunebi-api/voices:enroll"] : null
}

resource "aws_apigatewayv2_route" "voices_delete" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "POST /voices/delete"
  target             = "integrations/${aws_apigatewayv2_integration.lambda.id}"
  authorization_type = "JWT" 
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
  
  # FIXED with colon
  authorization_scopes = var.env == "prod" ? ["lunebi-api/voices:delete"] : null
}

resource "aws_apigatewayv2_route" "stories_prepare" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "POST /stories/prepare"
  target             = "integrations/${aws_apigatewayv2_integration.lambda.id}"
  authorization_type = "JWT"  
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id 
  
  # FIXED with colon
  authorization_scopes = var.env == "prod" ? ["lunebi-api/stories:prepare"] : null
}

resource "aws_apigatewayv2_route" "stories_append" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "POST /stories/{id}"
  target             = "integrations/${aws_apigatewayv2_integration.lambda.id}"
  authorization_type = "JWT"  
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id  
  
  # FIXED with colon
  authorization_scopes = var.env == "prod" ? ["lunebi-api/stories:append"] : null
}

resource "aws_apigatewayv2_route" "stories_status" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "GET /stories/{id}/status"
  target             = "integrations/${aws_apigatewayv2_integration.lambda.id}"
  authorization_type = "JWT"  
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id 
  
  # FIXED with colon
  authorization_scopes = var.env == "prod" ? ["lunebi-api/stories:status:read"] : null
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.app.invoke_arn
  payload_format_version = "2.0"
}

# -----------------------------
# Stage
# -----------------------------
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = var.env
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 10   # max concurrent requests beyond steady rate
    throttling_rate_limit  = 50   # requests per second
  }
}

# -----------------------------
# Custom Domain for API Gateway
# -----------------------------
resource "aws_apigatewayv2_domain_name" "api_domain" {
  domain_name = var.domain_name

  domain_name_configuration {
    certificate_arn = var.api_cert_arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }
}

resource "aws_apigatewayv2_api_mapping" "api_mapping" {
  api_id      = aws_apigatewayv2_api.http.id
  domain_name = aws_apigatewayv2_domain_name.api_domain.domain_name
  stage       = aws_apigatewayv2_stage.default.name
}

# -----------------------------
# Route53 record for API custom domain
# -----------------------------
data "aws_route53_zone" "main" {
  name         = "lunebi.com."
  private_zone = false
}

resource "aws_route53_record" "api_domain" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = "api.lunebi.com"
  type    = "A"

  alias {
    name                   = aws_apigatewayv2_domain_name.api_domain.domain_name_configuration[0].target_domain_name
    zone_id                = aws_apigatewayv2_domain_name.api_domain.domain_name_configuration[0].hosted_zone_id
    evaluate_target_health = false
  }
}

# -----------------------------
# IAM Role for Lambda
# -----------------------------
resource "aws_iam_role" "lambda_exec" {
  name = "${local.prefix}-lambda-exec"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Action    = "sts:AssumeRole",
      Effect    = "Allow",
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

# ✅ CORRECT: This is for Lambda NOT in VPC
resource "aws_iam_role_policy_attachment" "lambda_basic_exec" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Optional: Lambda Insights for metrics
resource "aws_iam_role_policy_attachment" "lambda_insights_exec" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchLambdaInsightsExecutionRolePolicy"
}

# -----------------------------
# Secrets & Config
# -----------------------------
resource "aws_secretsmanager_secret" "app_secret" {
  name = "${local.prefix}-app-secret"
}

resource "aws_secretsmanager_secret_version" "app_secret_v" {
  secret_id     = aws_secretsmanager_secret.app_secret.id
  secret_string = jsonencode({ api_key = var.secret_value })
}

resource "aws_ssm_parameter" "config" {
  name  = "/${local.prefix}/config"
  type  = "String"
  value = var.config_value
}

resource "aws_ssm_parameter" "enable_backend_wiring" {
  name  = "/${local.prefix}/ENABLE_BACKEND_WIRING"
  type  = "String"
  value = "false"  # M2 is mocked
}

resource "aws_ssm_parameter" "enable_auth" {
  name  = "/${local.prefix}/ENABLE_AUTH" 
  type  = "String"
  value = "true"
}

# IAM Policy for Lambda 
data "aws_iam_policy_document" "lambda_read" {
  # SQS: SendMessage only (to main queue)
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [var.sqs_queue_arn]
  }

  # DynamoDB: Get, Put, Update on both tables
  statement {
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem"
    ]
    resources = [
      var.voices_table_arn,
      var.stories_table_arn
    ]
  }

  # S3: PutObject for playlist skeletons only
  statement {
    actions   = ["s3:PutObject"]
    resources = ["${var.s3Bucket_arn}/stories/*/playlist.m3u8"]
  }
  
  # KMS: For S3 operations
statement {
  actions = [
    "kms:Decrypt",
    "kms:GenerateDataKey",
    "kms:GenerateDataKeyWithoutPlaintext"
  ]
  resources = [var.stories_kms_key_arn]  # Direct reference
}

  # KMS: Encrypt/Decrypt for DynamoDB
  statement {
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [var.ddb_kms_key_arn]
  }

  # SSM Parameter (existing)
  statement {
    actions   = ["ssm:GetParameter", "ssm:GetParameters"]
    resources = [aws_ssm_parameter.config.arn]
  }

  # Secrets Manager (existing)
  statement {
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [aws_secretsmanager_secret.app_secret.arn]
  }
}


resource "aws_iam_policy" "lambda_read" {
  name   = "${local.prefix}-lambda-read"
  policy = data.aws_iam_policy_document.lambda_read.json
}

resource "aws_iam_role_policy_attachment" "attach_lambda_read" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = aws_iam_policy.lambda_read.arn
}

# -----------------------------
# Lambda (infra only, code via CI/CD)
# -----------------------------
resource "aws_lambda_function" "app" {
  function_name = "${local.prefix}-lambda"
  role          = aws_iam_role.lambda_exec.arn
  runtime       = "python3.11"
  handler       = "app.lambda_handler"

  # Dummy bootstrap zip so Terraform can create the function
  filename         = "${path.module}/bootstrap.zip"
  source_code_hash = filebase64sha256("${path.module}/bootstrap.zip")


  timeout     = 10     # 10s timeout
  memory_size = 512     # 512 MB memory
  ephemeral_storage {
    size = 512         # 512 MB ephemeral storage
  }

  environment {
    variables = {
      CONFIG_PARAM          = aws_ssm_parameter.config.name
      SECRET_ARN            = aws_secretsmanager_secret.app_secret.arn
      ENABLE_BACKEND_WIRING = "true"
      ENABLE_AUTH           = "true"

      VOICES_TABLE_NAME  = var.voices_table_name
      STORIES_TABLE_NAME = var.stories_table_name
      SQS_QUEUE_URL      = var.sqs_queue_url
      S3_BUCKET_NAME     = var.s3_bucket_name
      
      # JWT Configuration - Conditional based on environment
      JWT_ISSUER    = var.env == "prod" ? "https://cognito-idp.${var.region}.amazonaws.com/${aws_cognito_user_pool.main.id}" : "https://mock-issuer.lunebi.com"
      # Instead of a single static string, allow multiple client IDs (future-proof)
      JWT_ALLOWED_CLIENT_IDS = aws_cognito_user_pool_client.api_client.id

      JWT_ALGORITHM = "RS256"
      
      # Cognito Configuration
      COGNITO_USER_POOL_ID        = aws_cognito_user_pool.main.id
      COGNITO_USER_POOL_CLIENT_ID = aws_cognito_user_pool_client.api_client.id
      COGNITO_REGION              = var.region
      
      # Development JWKS
      JWKS_SECRET_ARN = var.env == "dev" ? aws_secretsmanager_secret.mock_jwks[0].arn : ""
    }
  }


  depends_on = [
    aws_iam_role_policy_attachment.lambda_basic_exec,
    aws_iam_role_policy_attachment.lambda_insights_exec,
    aws_iam_role_policy_attachment.attach_lambda_read,
    aws_cognito_user_pool.main,      
    aws_cognito_user_pool_client.api_client,
  ]
    lifecycle {
    create_before_destroy = true
  }
}

# -----------------------------
# Lambda Permission for API Gateway
# -----------------------------
resource "aws_lambda_permission" "allow_apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.app.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}

# -----------------------------
# CloudWatch Log Groups
# -----------------------------
resource "aws_cloudwatch_log_group" "api_gw" {
  name              = "/aws/apigateway/${aws_apigatewayv2_api.http.id}"
  retention_in_days = 30

}

# -----------------------------
# CloudWatch Alarms 
# -----------------------------
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${local.prefix}-lambda-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  dimensions = {
    FunctionName = aws_lambda_function.app.function_name
  }
  alarm_description = "Lambda function is throwing errors"
}

# -----------------------------
# CloudWatch Dashboard for API + Lambda + Custom Metrics
# -----------------------------
resource "aws_cloudwatch_dashboard" "api_dashboard" {
  dashboard_name = "${local.prefix}-api-dashboard"
  dashboard_body = jsonencode({
    widgets = [
      # API Gateway metrics
      {
        "type" : "metric",
        "x" : 0,
        "y" : 0,
        "width" : 12,
        "height" : 6,
        "properties" : {
          "metrics" : [
            [ "AWS/ApiGateway", "4XXError", "ApiId", aws_apigatewayv2_api.http.id ],
            [ "AWS/ApiGateway", "5XXError", "ApiId", aws_apigatewayv2_api.http.id ],
            [ "AWS/ApiGateway", "Latency",  "ApiId", aws_apigatewayv2_api.http.id ],
            [ "AWS/ApiGateway", "Count",    "ApiId", aws_apigatewayv2_api.http.id ]
          ],
          "view"   : "timeSeries",
          "region" : var.region,
          "title"  : "API Gateway Metrics"
        }
      },

      # Lambda metrics
      {
        "type" : "metric",
        "x" : 0,
        "y" : 7,
        "width" : 12,
        "height" : 6,
        "properties" : {
          "metrics" : [
            [ "AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.app.function_name ],
            [ "AWS/Lambda", "Errors",      "FunctionName", aws_lambda_function.app.function_name ],
            [ "AWS/Lambda", "Duration",    "FunctionName", aws_lambda_function.app.function_name ],
            [ "AWS/Lambda", "Throttles",   "FunctionName", aws_lambda_function.app.function_name ]
          ],
          "view"   : "timeSeries",
          "region" : var.region,
          "title"  : "Lambda Metrics"
        }
      },

      # Custom App Metrics (Requests & Errors)
      {
        "type" : "metric",
        "x" : 0,
        "y" : 14,
        "width" : 12,
        "height" : 6,
        "properties" : {
          "metrics" : [
            [ "Lunebi/API", "Requests", "Route", "ALL" ],
            [ "Lunebi/API", "Errors",   "Route", "ALL" ]
          ],
          "view"   : "timeSeries",
          "region" : var.region,
          "title"  : "Custom API Requests & Errors",
          "stat"   : "Sum"
        }
      },

      # Custom App Metrics (Latency p50 / p95)
      {
        "type" : "metric",
        "x" : 0,
        "y" : 21,
        "width" : 12,
        "height" : 6,
        "properties" : {
          "metrics" : [
            [ "Lunebi/API", "Latency", "Route", "ALL", { "stat": "p50" } ],
            [ "Lunebi/API", "Latency", "Route", "ALL", { "stat": "p95" } ]
          ],
          "view"   : "timeSeries",
          "region" : var.region,
          "title"  : "Custom API Latency (p50 / p95)"
        }
      }
    ]
  })
}


# =============================================================================
# ADDITIONAL IAM PERMISSIONS FOR COGNITO & SECRETS
# =============================================================================
data "aws_iam_policy_document" "lambda_cognito_access" {
  # Cognito permissions
  statement {
    actions = [
      "cognito-idp:DescribeUserPool",
      "cognito-idp:DescribeUserPoolClient"
    ]
    resources = [
      aws_cognito_user_pool.main.arn,
      "${aws_cognito_user_pool.main.arn}/client/*"
    ]
  }
  
  # Secrets Manager permissions for JWKS (dev only) - FIXED
  dynamic "statement" {
    for_each = var.env == "dev" ? [1] : []
    content {
      actions = ["secretsmanager:GetSecretValue"]
      resources = [aws_secretsmanager_secret.mock_jwks[0].arn]
      # REMOVED: jwt_private_key reference since it doesn't exist
    }
  }
}

resource "aws_iam_policy" "lambda_cognito_access" {
  name        = "${local.prefix}-lambda-cognito-access"
  description = "Allow Lambda to access Cognito and JWKS secrets"
  policy      = data.aws_iam_policy_document.lambda_cognito_access.json
}

resource "aws_iam_role_policy_attachment" "lambda_cognito_access" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = aws_iam_policy.lambda_cognito_access.arn
}
# =============================================================================
# FIXED MOCK JWKS (Use generated RSA key instead of variable)
# =============================================================================
resource "aws_secretsmanager_secret" "mock_jwks" {
  count       = var.env == "dev" ? 1 : 0 
  name        = "${local.prefix}-jwks"
  description = "JWKS public keys for JWT validation in development"
}

resource "aws_secretsmanager_secret_version" "mock_jwks_v" {
  count = var.env == "dev" ? 1 : 0 
  secret_id = aws_secretsmanager_secret.mock_jwks[0].id
  
  secret_string = jsonencode({
    keys = [
      {
        kty = "RSA"
        kid = "2025-09-dev"
        use = "sig"
        alg = "RS256"
        n   = var.JWKS
        e   = "AQAB"
      }
    ]
  })
}
