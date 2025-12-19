# DynamoDB Table Outputs
output "voices_table_name" {
  description = "Name of the voices table"
  value       = aws_dynamodb_table.voices.name
}

output "voices_table_arn" {
  description = "ARN of the voices table"
  value       = aws_dynamodb_table.voices.arn
}

output "stories_table_name" {
  description = "Name of the stories table"
  value       = aws_dynamodb_table.stories.name
}

output "stories_table_arn" {
  description = "ARN of the stories table"
  value       = aws_dynamodb_table.stories.arn
}

# KMS Key Outputs
output "kms_key_arn" {
  description = "ARN of the KMS key used for encryption"
  value       = local.kms_key_arn
}

output "kms_key_id" {
  description = "ID of the KMS key used for encryption"
  value       = local.kms_key_arn != null ? element(split("/", local.kms_key_arn), length(split("/", local.kms_key_arn)) - 1) : null
}

# GPU Worker Role Outputs
output "gpu_worker_role_arn" {
  description = "ARN of the GPU worker role"
  value       = aws_iam_role.gpu_worker.arn
}

output "gpu_worker_role_name" {
  description = "Name of the GPU worker role"
  value       = aws_iam_role.gpu_worker.name
}

output "gpu_worker_instance_profile_name" {
  description = "Name of the GPU worker instance profile"
  value       = aws_iam_instance_profile.gpu_worker.name
}

# CPU Mock Role Outputs
output "cpu_mock_role_arn" {
  description = "ARN of the CPU mock role"
  value       = var.enable_cpu_mock ? aws_iam_role.cpu_mock[0].arn : null
}

output "cpu_mock_role_name" {
  description = "Name of the CPU mock role"
  value       = var.enable_cpu_mock ? aws_iam_role.cpu_mock[0].name : null
}

# Observability Outputs
output "dynamodb_dashboard_url" {
  description = "URL of the DynamoDB CloudWatch dashboard"
  value       = "https://${var.region}.console.aws.amazon.com/cloudwatch/home?region=${var.region}#dashboards:name=${aws_cloudwatch_dashboard.dynamodb_metrics.dashboard_name}"
}

# SSM parameter outputs
output "stories_table_ssm_parameter" {
  description = "SSM parameter name for stories table"
  value       = aws_ssm_parameter.stories_table.name
}

output "voices_table_ssm_parameter" {
  description = "SSM parameter name for voices table"
  value       = aws_ssm_parameter.voices_table.name
}

output "dynamodb_kms_key_ssm_parameter" {
  description = "SSM parameter name for DynamoDB KMS key"
  value       = aws_ssm_parameter.dynamodb_kms_key_arn.name
}