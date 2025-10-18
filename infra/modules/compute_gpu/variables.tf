variable "prefix" {
  description = "Resource prefix (project-env-region)"
  type        = string
}

variable "sqs_queue_url" {
  description = "URL of the SQS queue to consume from"
  type        = string
}

variable "stories_table_name" {
  description = "Name of the stories DynamoDB table"
  type        = string
}

variable "cpu_mock_role_arn" {
  description = "ARN of the CPU mock IAM role"
  type        = string
}

variable "mock_min_ms" {
  description = "Minimum mock processing time in milliseconds"
  type        = number
  default     = 300
}

variable "mock_max_ms" {
  description = "Maximum mock processing time in milliseconds"
  type        = number
  default     = 800
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}
variable "sqs_queue_arn" {
  description = "queue arn"
  type = string
  
}