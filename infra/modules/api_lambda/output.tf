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
