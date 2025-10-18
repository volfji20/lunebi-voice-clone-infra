variable "prefix" {
  description = "Resource prefix (project-env-region)"
  type        = string
}

variable "project" {
  description = "Project name"
  type        = string
}

variable "env" {
  description = "Environment name"
  type        = string
}

variable "stories_ttl_days" {
  description = "TTL for stories table in days"
  type        = number
  default     = 30
}

variable "kms_key_arn" {
  description = "KMS key ARN for encryption (optional - creates one if not provided)"
  type        = string
  default     = null
}

variable "sqs_queue_arn" {
  description = "ARN of the SQS queue for message processing"
  type        = string
}

variable "stories_bucket_arn" {
  description = "ARN of the S3 bucket for story segments and playlists"
  type        = string
}

variable "enable_cpu_mock" {
  description = "Whether to enable CPU mock consumer role (Test Mode)"
  type        = bool
  default     = true
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

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}