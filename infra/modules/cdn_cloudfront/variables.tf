# -----------------------------
# Project / Environment
# -----------------------------
variable "project" {
  description = "Project name"
  type        = string
}

variable "env" {
  description = "Environment (e.g., dev, prod)"
  type        = string
}

variable "region" {
  description = "AWS region (e.g., us-east-1, eu-central-1)"
  type        = string
}

# -----------------------------
# CDN / API Domains
# -----------------------------
variable "cdn_domain" {
  description = "Domain name for CloudFront CDN distribution (e.g., cdn.example.com)"
  type        = string
}

variable "api_domain" {
  description = "Domain name for API endpoint (e.g., api.example.com)"
  type        = string
}

# -----------------------------
# Signed URL Public Key
# -----------------------------
variable "signed_url_public_key_path" {
  description = "Path to public key PEM file for CloudFront signed URLs"
  type        = string
}

# -----------------------------
# Origin Storage Bucket
# -----------------------------
variable "stories_bucket_domain_name" {
  description = "Domain name of the stories S3 bucket"
  type        = string
}


# -----------------------------
# Existing CloudFront Distributions (optional, if reusing)
# -----------------------------
variable "existing_cdn_distribution_id" {
  description = "ID of an existing CloudFront distribution for CDN (if reusing instead of creating new)"
  type        = string
  default     = ""
}

# -----------------------------
# ACM Certificates (for validation only)
# -----------------------------
variable "cdn_cert_arn" {
  description = "ARN of the ACM certificate for CDN domain (validation only, not attached)"
  type        = string
  default     = ""
}

variable "api_cert_arn" {
  description = "ARN of the ACM certificate for API domain (validation only, not attached)"
  type        = string
  default     = ""
}

# -----------------------------
# Tags
# -----------------------------
variable "tags" {
  description = "Tags to apply to CloudFront resources"
  type        = map(string)
  default     = {}
}

variable "web_acl_id" {
  description = "Web Acl Id"
  type        = string
}


variable "cloudfront_distribution_cdn" {
  description = "existing oac id"
  type        = string
}