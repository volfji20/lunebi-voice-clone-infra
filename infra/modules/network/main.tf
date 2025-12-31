terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

# -----------------------------
# VPC
# -----------------------------
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags = {
    Name    = "${var.project}-${var.env}-vpc"
    Project = var.project
    Env     = var.env
  }
}

# -----------------------------
# Public Subnet
# -----------------------------
resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.public_subnet_cidr
  availability_zone       = "us-east-1a"
  map_public_ip_on_launch = true
  tags = {
    Name    = "${var.project}-${var.env}-public-subnet"
    Project = var.project
    Env     = var.env
  }
}

# -----------------------------
# Private Subnet
# -----------------------------
resource "aws_subnet" "private" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.private_subnet_cidr
  availability_zone       = "us-east-1a"
  map_public_ip_on_launch = false
  tags = {
    Name    = "${var.project}-${var.env}-private-subnet"
    Project = var.project
    Env     = var.env
  }
}

# -----------------------------
# Internet Gateway
# -----------------------------
resource "aws_internet_gateway" "igw" {
  vpc_id = aws_vpc.main.id
  tags = {
    Name    = "${var.project}-${var.env}-igw"
    Project = var.project
    Env     = var.env
  }
}


# -----------------------------
# Route Tables
# -----------------------------
# Public route table
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  tags = {
    Name    = "${var.project}-${var.env}-public-rt"
    Project = var.project
    Env     = var.env
  }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.igw.id
}

# Private route table
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
  tags = {
    Name    = "${var.project}-${var.env}-private-rt"
    Project = var.project
    Env     = var.env
  }
}

resource "aws_route_table_association" "private" {
  subnet_id      = aws_subnet.private.id
  route_table_id = aws_route_table.private.id
}

# -----------------------------
# VPC Endpoints
# -----------------------------
# S3 (Gateway)
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]

  tags = {
    Name    = "${var.project}-${var.env}-s3-vpce"
    Project = var.project
    Env     = var.env
  }
}

# DynamoDB (Gateway)
resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]

  tags = {
    Name    = "${var.project}-${var.env}-dynamodb-vpce"
    Project = var.project
    Env     = var.env
  }
}



resource "aws_security_group" "gpu_worker" {
  name        = "${var.project}-gpu-worker-sg"
  description = "Security group for GPU worker instances"
  vpc_id      = aws_vpc.main.id

  # Only OUTBOUND rules needed - FREE
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "${var.project}-${var.env}-gpu-worker-sg"
    Project = var.project
    Env     = var.env
  }
}

# ssm_endpoints.tf
# SSM VPC Endpoints for Private Subnet Access

# -----------------------------
# Security Group for VPC Endpoints
# -----------------------------
resource "aws_security_group" "vpc_endpoint" {
  name        = "${var.project}-${var.env}-vpc-endpoint-sg"
  description = "Security group for VPC endpoints (SSM, EC2, Logs)"
  vpc_id      = aws_vpc.main.id

  # Inbound HTTPS from private subnet only
  ingress {
    description = "HTTPS from private subnet"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [aws_subnet.private.cidr_block]  # Restrict to private subnet
  }

  # Allow responses back
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "${var.project}-${var.env}-vpc-endpoint-sg"
    Project = var.project
    Env     = var.env
    Cost    = "Optimized"
  }
}

# -----------------------------
# ESSENTIAL SSM Endpoints (Required for Session Manager)
# -----------------------------
# 1. SSM Endpoint (core service) - $7.29/month
resource "aws_vpc_endpoint" "ssm" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.region}.ssm"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private.id]  # Creates 1 ENI
  private_dns_enabled = true
  
  security_group_ids = [
    aws_security_group.vpc_endpoint.id
  ]

  tags = {
    Name    = "${var.project}-${var.env}-ssm-vpce"
    Project = var.project
    Env     = var.env
    Type    = "Interface"
    Cost    = "$7.29/month"
  }
}

# 2. SSM Messages Endpoint (required) - $7.29/month
resource "aws_vpc_endpoint" "ssm_messages" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.region}.ssmmessages"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private.id]  # Creates 1 ENI
  private_dns_enabled = true
  
  security_group_ids = [
    aws_security_group.vpc_endpoint.id
  ]

  tags = {
    Name    = "${var.project}-${var.env}-ssm-messages-vpce"
    Project = var.project
    Env     = var.env
    Type    = "Interface"
    Cost    = "$7.29/month"
  }
}

# 3. EC2 Messages Endpoint (required) - $7.29/month
resource "aws_vpc_endpoint" "ec2_messages" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.region}.ec2messages"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private.id]  # Creates 1 ENI
  private_dns_enabled = true
  
  security_group_ids = [
    aws_security_group.vpc_endpoint.id
  ]

  tags = {
    Name    = "${var.project}-${var.env}-ec2-messages-vpce"
    Project = var.project
    Env     = var.env
    Type    = "Interface"
    Cost    = "$7.29/month"
  }
}

# -----------------------------
# OPTIONAL: CloudWatch Logs Endpoint
# -----------------------------
# Uncomment if using CloudWatch agent for logs
# resource "aws_vpc_endpoint" "logs" {
#   vpc_id              = aws_vpc.main.id
#   service_name        = "com.amazonaws.${var.region}.logs"
#   vpc_endpoint_type   = "Interface"
#   subnet_ids          = [aws_subnet.private.id]
#   private_dns_enabled = true
#   
#   security_group_ids = [
#     aws_security_group.vpc_endpoint.id
#   ]
#
#   tags = {
#     Name    = "${var.project}-${var.env}-logs-vpce"
#     Project = var.project
#     Env     = var.env
#     Type    = "Optional"
#     Cost    = "$7.29/month"
#   }
# }


# SQS VPC Endpoint
resource "aws_vpc_endpoint" "sqs" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.region}.sqs"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private.id]
  private_dns_enabled = true
  
  security_group_ids = [
    aws_security_group.vpc_endpoint.id
  ]

  tags = {
    Name    = "${var.project}-${var.env}-sqs-vpce"
    Project = var.project
    Env     = var.env
  }
}