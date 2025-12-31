# -------------------------
# API Gateway outputs
# -------------------------
output "api_gateway_id" {
  description = "ID of the API Gateway HTTP API"
  value       = aws_apigatewayv2_api.http.id
}

output "api_gateway_invoke_url" {
  description = "Invoke URL for the API Gateway stage"
  value       = aws_apigatewayv2_stage.default.invoke_url
}

# -------------------------
# Secrets & Config
# -------------------------
output "secret_name" {
  description = "Name of the application secret in Secrets Manager"
  value       = aws_secretsmanager_secret.app_secret.name
}

output "config_parameter_name" {
  description = "Name of the SSM parameter for app config"
  value       = aws_ssm_parameter.config.name
}


# In your api_lambda module (modules/api_lambda/outputs.tf)
output "lambda_role_arn" {
  description = "ARN of the Lambda execution role"
  value       = aws_iam_role.lambda_exec.arn
}

output "lambda_function_name" {
  description = "Name of the Lambda function"
  value       = aws_lambda_function.app.function_name
}

output "lambda_function_arn" {
  description = "ARN of the Lambda function"
  value       = aws_lambda_function.app.arn
}

output "api_lambda_role_arn" {
  description = "ARN of the API Lambda execution role"
  value       = aws_iam_role.lambda_exec.arn
}