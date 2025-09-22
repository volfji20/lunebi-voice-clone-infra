locals {
  prefix = "${var.project}-${var.env}-${var.region}"
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

resource "aws_iam_role_policy_attachment" "lambda_basic_exec" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
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

# -----------------------------
# IAM Policy for Lambda (read secret + config)
# -----------------------------
data "aws_iam_policy_document" "lambda_read" {
  statement {
    actions   = ["ssm:GetParameter", "ssm:GetParameters"]
    resources = [aws_ssm_parameter.config.arn]
  }
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
  runtime       = "nodejs20.x"
  handler       = "index.handler"

  # dummy bootstrap zip so Terraform can create function
  filename         = "${path.module}/bootstrap.zip"
  source_code_hash = filebase64sha256("${path.module}/bootstrap.zip")

  environment {
    variables = {
      CONFIG_PARAM = aws_ssm_parameter.config.name
      SECRET_ARN   = aws_secretsmanager_secret.app_secret.arn
    }
  }
}

# -----------------------------
# API Gateway (HTTP API)
# -----------------------------
resource "aws_apigatewayv2_api" "http" {
  name          = "${local.prefix}-httpapi"
  protocol_type = "HTTP"
  
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.app.arn
  payload_format_version = "2.0"
}

# -----------------------------
# Optional JWT Authorizer
# -----------------------------
resource "aws_apigatewayv2_authorizer" "jwt" {
  count           = var.jwt_authorizer_enabled ? 1 : 0
  api_id          = aws_apigatewayv2_api.http.id
  name            = "${local.prefix}-jwt-auth"
  authorizer_type = "JWT"
  identity_sources = ["$request.header.Authorization"]

  jwt_configuration {
    issuer   = "https://example-issuer/"
    audience = ["example-audience"]
  }
}

# -----------------------------
# Routes
# -----------------------------
locals {
  routes = {
    "POST /stories/prepare"    = true
    "POST /stories/{id}"       = true
    "GET /stories/{id}/status" = true
  }
}

resource "aws_apigatewayv2_route" "routes" {
  for_each  = local.routes
  api_id    = aws_apigatewayv2_api.http.id
  route_key = each.key
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"

  authorization_type = var.jwt_authorizer_enabled ? "JWT" : "NONE"
  authorizer_id      = var.jwt_authorizer_enabled ? aws_apigatewayv2_authorizer.jwt[0].id : null
}

# -----------------------------
# Stage
# -----------------------------
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = var.env
  auto_deploy = true

  
}

# -----------------------------
# Custom Domain for API Gateway
# -----------------------------
resource "aws_apigatewayv2_domain_name" "api_domain" {
  domain_name = "api.lunebi.com"

  domain_name_configuration {
    certificate_arn = var.api_cert_arn  # your existing ACM cert for api.lunebi.com
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }
}

# Map domain → API → stage
resource "aws_apigatewayv2_api_mapping" "api_mapping" {
  api_id      = aws_apigatewayv2_api.http.id
  domain_name = aws_apigatewayv2_domain_name.api_domain.domain_name
  stage       = aws_apigatewayv2_stage.default.name
}

resource "aws_lambda_permission" "allow_apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.app.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
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
