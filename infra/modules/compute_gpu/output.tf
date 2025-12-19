output "cpu_mock_lambda_arn" {
  description = "ARN of the CPU mock Lambda function"
  value = try(aws_lambda_function.cpu_mock[0].arn, null)
}

output "cpu_mock_lambda_name" {
  description = "Name of the CPU mock Lambda function"
  value = try(aws_lambda_function.cpu_mock[0].function_name, null)
}

output "mock_min_ms_parameter" {
  description = "SSM parameter name for mock minimum processing time"
  value = try(aws_ssm_parameter.mock_min_ms[0].name, null)
}

output "mock_max_ms_parameter" {
  description = "SSM parameter name for mock maximum processing time"
  value = try(aws_ssm_parameter.mock_max_ms[0].name, null)
}

# infra/modules/compute_gpu/outputs.tf mein ye add karo:

output "gpu_asg_name" {
  description = "GPU Auto Scaling Group name"
  value       = try(aws_autoscaling_group.gpu_workers[0].name, "")
}

output "test_mode_alerts_topic_arn" {
  description = "Test mode alerts SNS topic ARN"
  value       = try(aws_sns_topic.test_mode_alerts[0].arn, "")
}

