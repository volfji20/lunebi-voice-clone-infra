output "stories_bucket_id" {
  value       = aws_s3_bucket.stories.id
  description = "ID of the stories S3 bucket"
}

output "stories_bucket_arn" {
  value       = aws_s3_bucket.stories.arn
  description = "ARN of the stories S3 bucket"
}

output "stories_bucket_domain_name" {
  description = "Domain name of the stories bucket"
  value       = aws_s3_bucket.stories.bucket_regional_domain_name
}
