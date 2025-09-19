# -----------------------------
# Project / Environment / Region
# -----------------------------
variable "project" {
  description = "Project name (e.g., lunebi)"
  type        = string
}

variable "env" {
  description = "Environment (e.g., dev, prod)"
  type        = string
}

variable "region" {
  description = "AWS region where VPC endpoints will be created"
  type        = string
}

# -----------------------------
# VPC / Subnets / Routes
# -----------------------------
variable "vpc_id" {
  description = "VPC ID where endpoints will be created"
  type        = string
}

variable "private_route_table_ids" {
  description = "List of private route table IDs for gateway endpoints"
  type        = list(string)
}
