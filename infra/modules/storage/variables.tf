##################################################
# Variables
##################################################

variable "env" {
  description = "Deployment environment (e.g., dev, staging, prod)"
  type        = string
}

variable "region" {
  description = "AWS region"
  type        = string
}

variable "project" {
  description = "Project name prefix"
  type        = string
}

variable "kms_key_arn" {
  description = "Optional KMS key ARN. If empty, a new one is created."
  type        = string
  default     = ""
}

variable "stories_bucket_name" {
  description = "Name of the stories S3 bucket (must be globally unique)"
  type        = string
}

variable "expire_segments_days" {
  description = "Number of days before expiring transient story segments (.m4s, .m3u8)"
  type        = number
  default     = 7
}

variable "transition_final_days" {
  description = "Number of days before transitioning finals to STANDARD_IA"
  type        = number
  default     = 30
}

variable "iam_role_name" {
  description = "IAM role ARN allowed to access this bucket"
  type        = string
}

variable "s3_vpc_endpoint_id" {
  type        = string
  description = "The ID of the VPC endpoint for S3"
}

variable "oac_arn" {
  type = string
  description = "oac_iam_arn"
  
}