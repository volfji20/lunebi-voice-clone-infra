output "sqs_queue_url" {
  description = "The URL of the SQS queue"
  value       = aws_sqs_queue.queue.url
}

output "sqs_queue_arn" {
  description = "The ARN of the SQS queue"
  value       = aws_sqs_queue.queue.arn
}

output "sqs_queue_name" {
  description = "The name of the SQS queue"
  value       = aws_sqs_queue.queue.name
}
