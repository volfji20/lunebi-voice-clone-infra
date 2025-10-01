output "s3_vpc_endpoint_id" {
  description = "ID of the S3 Gateway VPC endpoint"
  value       = aws_vpc_endpoint.s3.id
}

output "dynamodb_vpc_endpoint_id" {
  description = "ID of the DynamoDB Gateway VPC endpoint"
  value       = aws_vpc_endpoint.dynamodb.id
}

output "sqs_vpc_endpoint_id" {
  description = "ID of the SQS Interface VPC endpoint"
  value       = aws_vpc_endpoint.sqs.id
}

output "vpc_endpoints_sg_id" {
  description = "Security Group ID for VPC Endpoints"
  value       = aws_security_group.vpce_sg.id
}

output "private_subnets" {
  description = "List of private subnet IDs"
  value       = aws_subnet.private[*].id
}

output "lambda_sg_id" {
  description = "Security Group ID for Lambda"
  value       = aws_security_group.lambda.id
}
