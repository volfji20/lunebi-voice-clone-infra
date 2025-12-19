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

output "stories_kms_key_arn" {
  description = "ARN of the KMS key used for S3 encryption"
  value       = aws_kms_key.stories_key.arn
}

output "stories_bucket_ssm_parameter" {
  description = "SSM parameter name for stories bucket"
  value       = aws_ssm_parameter.stories_bucket.name
}

output "stories_kms_key_ssm_parameter" {
  description = "SSM parameter name for KMS key ID"
  value       = aws_ssm_parameter.stories_kms_key_id.name
}

output "stories_bucket_arn_ssm_parameter" {
  description = "SSM parameter name for bucket ARN"
  value       = aws_ssm_parameter.stories_bucket_arn.name
}