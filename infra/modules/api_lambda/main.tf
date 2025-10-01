locals {
  prefix = "${var.project}-${var.env}-${var.region}"
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
# Routes with Scopes
# -----------------------------
resource "aws_apigatewayv2_route" "voices_enroll" {
  api_id               = aws_apigatewayv2_api.http.id
  route_key            = "POST /voices/enroll"
  target               = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_route" "voices_delete" {
  api_id               = aws_apigatewayv2_api.http.id
  route_key            = "POST /voices/delete"
  target               = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_route" "stories_prepare" {
  api_id               = aws_apigatewayv2_api.http.id
  route_key            = "POST /stories/prepare"
  target               = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_route" "stories_append" {
  api_id               = aws_apigatewayv2_api.http.id
  route_key            = "POST /stories/{id}"
  target               = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_route" "stories_status" {
  api_id               = aws_apigatewayv2_api.http.id
  route_key            = "GET /stories/{id}/status"
  target               = "integrations/${aws_apigatewayv2_integration.lambda.id}"
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

resource "aws_iam_role_policy_attachment" "lambda_basic_exec" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
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

# -----------------------------
# IAM Policy for Lambda (read secret + config)
# -----------------------------
data "aws_iam_policy_document" "lambda_read" {
  # SSM Parameter
  statement {
    actions   = ["ssm:GetParameter", "ssm:GetParameters"]
    resources = [aws_ssm_parameter.config.arn]
  }

  # Secrets Manager (App secret)
  statement {
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [aws_secretsmanager_secret.app_secret.arn]
  }

  # SQS (enqueue requests)
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [var.sqs_queue_arn]
  }

  # DynamoDB (voices + stories)
  statement {
    actions = [
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:GetItem"
    ]
    resources = [
      var.voices_table_arn,
      var.stories_table_arn
    ]
  }

  # S3 (playlist skeletons)
  statement {
    actions   = ["s3:PutObject"]
    resources = ["${var.s3Bucket_arn}/*"]
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

  # ✅ M2 Non-Functional Defaults
  timeout     = 10      # 10s timeout
  memory_size = 512     # 512 MB memory
  ephemeral_storage {
    size = 512         # 512 MB ephemeral storage
  }

  # ✅ FIXED - Remove merge() function
  environment {
    variables = {
      CONFIG_PARAM          = aws_ssm_parameter.config.name
      SECRET_ARN            = aws_secretsmanager_secret.app_secret.arn
      ENABLE_BACKEND_WIRING = var.env != "dev" ? "true" : "false"
    }
  }

  # Attach Lambda to VPC (private subnets + SG)
  vpc_config {
    subnet_ids         = var.private_subnets
    security_group_ids = [var.lambda_sg_id]
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_basic_exec,
    aws_iam_role_policy_attachment.lambda_insights_exec,
    aws_iam_role_policy_attachment.attach_lambda_read
  ]
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
# CloudWatch Alarms (optional but useful)
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

# # Private key (for signing test tokens in dev tools)
# resource "aws_secretsmanager_secret" "jwt_private" {
#   count = var.env == "dev" ? 1 : 0
#   name  = "${local.prefix}-jwt-private"
# }

# resource "aws_secretsmanager_secret_version" "jwt_private_ver" {
#   count        = var.env == "dev" ? 1 : 0
#   secret_id    = aws_secretsmanager_secret.jwt_private[0].id
#   secret_string = var.jwt_private_key
# }

# # JWKS (public key set)
# resource "aws_secretsmanager_secret" "mock_jwks" {
#   count = var.env == "dev" ? 1 : 0 
#   name  = "${local.prefix}-jwks"
# }

# resource "aws_secretsmanager_secret_version" "mock_jwks_v" {
#   count = var.env == "dev" ? 1 : 0 
#   secret_id = aws_secretsmanager_secret.mock_jwks[0].id
#   secret_string = jsonencode({
#     keys = [
#       {
#         kty = "RSA"
#         kid = "2025-09-dev"
#         use = "sig"
#         alg = "RS256"
#         n   = var.JWKS
#         e   = "AQAB"
#       }
#     ]
#   })
# }






