output "queue_url" {
  description = "URL of the main SQS queue"
  value       = aws_sqs_queue.story_tasks.url
}

output "queue_name" {
  description = "URL of the main SQS queue"
  value       = aws_sqs_queue.story_tasks.name
}

output "queue_arn" {
  description = "ARN of the main SQS queue"
  value       = aws_sqs_queue.story_tasks.arn
}

output "dlq_url" {
  description = "URL of the Dead Letter Queue"
  value       = aws_sqs_queue.story_tasks_dlq.url
}

output "dlq_arn" {
  description = "ARN of the Dead Letter Queue"
  value       = aws_sqs_queue.story_tasks_dlq.arn
}

output "visibility_timeout_seconds" {
  description = "Calculated visibility timeout in seconds"
  value       = local.visibility_timeout_seconds
}

output "p95_sentence_synth_parameter" {
  description = "SSM parameter name for p95 sentence synthesis time"
  value       = aws_ssm_parameter.p95_sentence_synth.name
}

output "queue_url_ssm_parameter" {
  description = "SSM parameter name for queue URL"
  value       = aws_ssm_parameter.queue_url.name
}