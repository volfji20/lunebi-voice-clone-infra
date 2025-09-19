terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

# -----------------------------
# VPC Endpoints for S3 and DynamoDB
# -----------------------------
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = var.vpc_id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = var.private_route_table_ids

  tags = {
    Name    = "${var.project}-${var.env}-${var.region}-s3-vpc-endpoint"
    Project = var.project
    Env     = var.env
  }
}

resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = var.vpc_id
  service_name      = "com.amazonaws.${var.region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = var.private_route_table_ids

  tags = {
    Name    = "${var.project}-${var.env}-${var.region}-dynamodb-vpc-endpoint"
    Project = var.project
    Env     = var.env
  }
}

