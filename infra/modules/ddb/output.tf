output "voices_table_arn" {
  description = "The ARN of the Voices DynamoDB table"
  value       = aws_dynamodb_table.voices.arn
}

output "voices_table_name" {
  description = "The name of the Voices DynamoDB table"
  value       = aws_dynamodb_table.voices.name
}

output "stories_table_arn" {
  description = "The ARN of the Stories DynamoDB table"
  value       = aws_dynamodb_table.stories.arn
}

output "stories_table_name" {
  description = "The name of the Stories DynamoDB table"
  value       = aws_dynamodb_table.stories.name
}
