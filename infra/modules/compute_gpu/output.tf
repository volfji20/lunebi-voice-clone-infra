output "cpu_mock_lambda_arn" {
  description = "ARN of the CPU mock Lambda function"
  value       = aws_lambda_function.cpu_mock.arn
}

output "cpu_mock_lambda_name" {
  description = "Name of the CPU mock Lambda function"
  value       = aws_lambda_function.cpu_mock.function_name
}

output "cpu_mock_cloudwatch_rule_arn" {
  description = "ARN of the CloudWatch Event rule that triggers the Lambda"
  value       = aws_cloudwatch_event_rule.cpu_mock_trigger.arn
}

output "mock_min_ms_parameter" {
  description = "SSM parameter name for mock minimum processing time"
  value       = aws_ssm_parameter.mock_min_ms.name
}

output "mock_max_ms_parameter" {
  description = "SSM parameter name for mock maximum processing time"
  value       = aws_ssm_parameter.mock_max_ms.name
}

output "cpu_mock_log_group_name" {
  description = "Name of the CloudWatch Log Group for CPU mock Lambda"
  value       = aws_cloudwatch_log_group.cpu_mock.name
}