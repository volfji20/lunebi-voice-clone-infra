# modules/network/outputs.tf

# VPC and Subnets
output "vpc_id" {
  value = aws_vpc.main.id
}

output "private_subnet_ids" { 
  value = [aws_subnet.private.id] 
}

output "public_subnet_ids" { 
  value = [aws_subnet.public.id]  
}

# Security Groups
output "gpu_worker_security_group_id" {
  value = aws_security_group.gpu_worker.id
}

# VPC Endpoint IDs (ADD THESE)
output "s3_vpc_endpoint_id" {
  value = aws_vpc_endpoint.s3.id
}

output "dynamodb_vpc_endpoint_id" {
  value = aws_vpc_endpoint.dynamodb.id
}

# Route Tables
output "private_route_table_id" {
  value = aws_route_table.private.id
}

output "public_route_table_id" {
  value = aws_route_table.public.id
}