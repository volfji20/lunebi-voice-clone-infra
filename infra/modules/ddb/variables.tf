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

variable "voices_table_name" {
  description = "Name of the DynamoDB voices table"
  type        = string
  default     = ""
}

variable "stories_table_name" {
  description = "Name of the DynamoDB stories table"
  type        = string
  default     = ""
}
