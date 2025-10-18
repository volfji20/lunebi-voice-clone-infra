variable "prefix" {
  description = "Resource prefix (project-env-region)"
  type        = string
}

variable "mode" {
  description = "Operation mode: test or prod"
  type        = string
  default     = "test"
}

variable "long_poll_seconds" {
  description = "SQS long polling duration in seconds"
  type        = number
  default     = 20
}

variable "max_receive_count" {
  description = "Max receive attempts before moving to DLQ"
  type        = number
  default     = 5
}

variable "message_retention_days" {
  description = "Message retention in days"
  type        = number
  default     = 4
}

variable "dlq_retention_days" {
  description = "DLQ message retention in days"
  type        = number
  default     = 14
}

variable "warning_alarm_actions" {
  description = "ARNs for warning alarm actions"
  type        = list(string)
  default     = []
}

variable "critical_alarm_actions" {
  description = "ARNs for critical alarm actions"
  type        = list(string)
  default     = []
}

variable "region" {
  description = "AWS region for the resources"
  type        = string
  default     = "us-east-1"
}

# Add these missing variables for SQS policy
variable "api_lambda_role_arn" {
  description = "ARN of the API Lambda role"
  type        = string
}

variable "gpu_worker_role_arn" {
  description = "ARN of the GPU worker role"
  type        = string
}

variable "cpu_mock_role_arn" {
  description = "ARN of the CPU mock role"
  type        = string
  default     = ""  # Optional for test mode
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}