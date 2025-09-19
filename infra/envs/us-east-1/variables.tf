#############################################
# Global project/environment
#############################################
variable "project" {
  description = "Project name (used for tagging and naming)"
  type        = string
}

variable "env" {
  description = "Environment name (e.g. dev, staging, prod)"
  type        = string
}

variable "region" {
  description = "AWS region for resources (must match S3 + VPC region)"
  type        = string
}

#############################################
# IAM Role
#############################################
variable "iam_role" {
  description = "IAM role ARN for app access"
  type        = string
}

#############################################
# S3 Storage
#############################################
variable "stories_bucket_name" {
  description = "Name of the S3 bucket for stories"
  type        = string
}

variable "expire_segments_days" {
  description = "Number of days before expiring .m4s segment files"
  type        = number
  default     = 7
}

variable "transition_final_days" {
  description = "Number of days before transitioning finals to STANDARD_IA"
  type        = number
  default     = 30
}

#############################################
# CDN / CloudFront
#############################################
variable "cdn_domain" {
  description = "CDN domain (e.g. cdn.lunebi.com)"
  type        = string
}

variable "api_domain" {
  description = "API domain (e.g. api.lunebi.com)"
  type        = string
}

variable "signed_url_public_key_path" {
  description = "Path to public key file for signed URLs"
  type        = string
}

variable "cdn_cert_arn" {
  description = "ARN of ACM certificate for CDN domain"
  type        = string
}

variable "api_cert_arn" {
  description = "ARN of ACM certificate for API domain"
  type        = string
}

variable "existing_cdn_distribution_id" {
  description = "If reusing an existing CloudFront distribution, provide its ID"
  type        = string
  default     = null
}

#############################################
# Networking (VPC + Endpoints)
#############################################
variable "vpc_id" {
  description = "ID of the VPC"
  type        = string
}

variable "private_route_table_ids" {
  description = "List of private route table IDs for VPC endpoints"
  type        = list(string)
}

variable "iam_role_policy" {
  type        = string
  description = "IAM role"
}


# -----------------------------
# Lambda / API
# -----------------------------
variable "lambda_runtime" {
  type        = string
  description = "Lambda runtime"
  default     = "nodejs18.x"
}


variable "jwt_authorizer_enabled" {
  type        = bool
  description = "Enable JWT authorizer on API Gateway routes"
  default     = false
}

variable "secret_value" {
  type        = string
  description = "Initial secret value for application"
  default     = "changeme"
}

variable "config_value" {
  type        = string
  description = "Initial configuration JSON string for SSM parameter"
  default     = "{\"feature_x\":true}"
}


variable "lambda_function_arn" {
  description = "ARN of the Lambda function deployed via CI/CD"
  type        = string
}

variable "lambda_function_name" {
  description = "Name of the Lambda function deployed via CI/CD"
  type        = string
}
