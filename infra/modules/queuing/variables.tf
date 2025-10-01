variable "project" {
  description = "Project name"
  type        = string
}

variable "env" {
  description = "Environment name (dev, prod, etc.)"
  type        = string
}

variable "region" {
  description = "AWS region"
  type        = string
}

variable "sqs_name" {
  description = "Name of the SQS queue"
  type        = string
  default     = ""
}

