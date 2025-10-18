# -------------------------
# Core naming inputs
# -------------------------
variable "project" {
  description = "Project name used in resource naming (e.g. voices-stories)"
  type        = string
}

variable "env" {
  description = "Environment (e.g. dev, staging, prod)"
  type        = string
}

variable "region" {
  description = "AWS region for deployment"
  type        = string
}

# -------------------------
# Feature toggles
# -------------------------
variable "jwt_authorizer_enabled" {
  description = "Enable JWT authorizer on API Gateway routes"
  type        = bool
  default     = false
}

# -------------------------
# JWT Authorizer config
# -------------------------
variable "jwt_issuer" {
  description = "JWT token issuer (e.g. Cognito user pool URL or Auth0 domain)"
  type        = string
  default     = ""
}

variable "jwt_audience" {
  description = "List of JWT audiences expected in access tokens"
  type        = list(string)
  default     = []
}

# -------------------------
# Secrets & Config
# -------------------------
variable "secret_value" {
  description = "Initial secret value for application (will be updated via Secrets Manager later)"
  type        = string
  default     = "changeme"
}

variable "config_value" {
  description = "Initial configuration JSON string for SSM parameter (override in CI/CD if needed)"
  type        = string
  default     = "{\"feature_x\":true}"
}


# -------------------------
# API Certificate
# -------------------------
variable "api_cert_arn" {
  description = "ARN of ACM certificate for api.lunebi.com (must be in us-east-1)"
  type        = string
}

# -------------------------
# VPC Inputs
# -------------------------
variable "private_subnets" {
  description = "List of private subnet IDs for Lambda VPC config"
  type        = list(string)
}

variable "lambda_sg_id" {
  description = "Security Group ID to associate with the Lambda function"
  type        = string
}

variable "sqs_queue_arn" {
  description = "Sqs queue"
  type = string
  
}

variable "voices_table_arn" {
  description = "voices table"
  type = string
  
}

variable "stories_table_arn" {
  description = "voices table"
  type = string
  
}

variable "s3Bucket_arn" {
  description = "voices table"
  type = string
  
}
variable "JWKS" {
  description = "jwks_base64url"
  type = string
  
}
variable "domain_name" {
  description = "Domain name"
  type = string
  
}

variable "jwt_private_key" {
  description = "RSA private key (PEM). Provide via TF_VAR_jwt_private_key or var file. Sensitive."
  type        = string
  sensitive   = true
}

variable "ddb_kms_key_arn" {
  description = "ARN of the KMS key for encryption"
  type        = string
}

# =============================================================================
# MILESTONE 3 BACKEND SERVICE VARIABLES
# =============================================================================

variable "voices_table_name" {
  description = "Name of the DynamoDB table for voice enrollments"
  type        = string
}

variable "stories_table_name" {
  description = "Name of the DynamoDB table for story metadata" 
  type        = string
}

variable "sqs_queue_url" {
  description = "URL of the SQS queue for story tasks"
  type        = string
}

variable "s3_bucket_name" {
  description = "Name of the S3 bucket for story playlists and audio segments"
  type        = string
}
variable "stories_kms_key_arn" {
  
  description = "kms key"
  type = string
}