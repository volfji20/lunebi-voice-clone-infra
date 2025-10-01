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
variable "iam_role_name" {
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

variable "signed_url_public_key" {
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


# -------------------------
# Secrets & Config
# -------------------------
variable "secret_value" {
  description = "Initial secret value for Secrets Manager (overwritten later by app/CI)"
  type        = string
  default     = "changeme"
}

variable "config_value" {
  description = "Initial JSON config string for SSM parameter"
  type        = string
  default     = "{\"feature_x\":true}"
}

# -------------------------
# Feature toggles
# -------------------------
variable "jwt_authorizer_enabled" {
  description = "Enable JWT authorizer on API Gateway"
  type        = bool
  default     = false
}

# -----------------------------
# JWT Auth variables
# -----------------------------
variable "jwt_issuer" {
  description = "JWT issuer (e.g., Cognito User Pool URL or mock JWKS URL)"
  type        = string
}
variable "jwt_audience" {
  description = "JWT audience for API Gateway authorizer"
  type        = string
  default     = ""  # optional if you want to make it optional
}


