# -----------------------------
# VPC Endpoints
# -----------------------------
output "s3_vpc_endpoint_id" {
  description = "ID of the S3 Gateway VPC endpoint"
  value       = aws_vpc_endpoint.s3.id
}

output "s3_vpc_endpoint_arn" {
  description = "ARN of the S3 Gateway VPC endpoint"
  value       = aws_vpc_endpoint.s3.arn
}

output "dynamodb_vpc_endpoint_id" {
  description = "ID of the DynamoDB Gateway VPC endpoint"
  value       = aws_vpc_endpoint.dynamodb.id
}

output "dynamodb_vpc_endpoint_arn" {
  description = "ARN of the DynamoDB Gateway VPC endpoint"
  value       = aws_vpc_endpoint.dynamodb.arn
}
