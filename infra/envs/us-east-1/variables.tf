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

variable "mode" {
  description = "Operation mode: test or prod"
  type        = string
  default     = "test"
  validation {
    condition     = contains(["test", "prod"], var.mode)
    error_message = "Mode must be either 'test' or 'prod'."
  }
}

variable "stories_ttl_days" {
  description = "TTL for stories table in days"
  type        = number
  default     = 30
}

variable "queue_long_poll_seconds" {
  description = "SQS long polling duration in seconds"
  type        = number
  default     = 20
}

variable "queue_max_receive_count" {
  description = "Max receive attempts before moving to DLQ"
  type        = number
  default     = 5
}

variable "enable_cpu_mock_consumer" {
  description = "Whether to enable CPU mock consumer (Test Mode)"
  type        = bool
  default     = true
}

variable "alarm_email" {
  description = "Email for CloudWatch alarm notifications"
  type        = string
  default     = null
}

# Environment-specific cost controls
variable "monthly_budget_usd" {
  type        = number
  description = "Monthly budget for US-East-1 environment"
  default     = 500
}

variable "alert_emails" {
  type        = list(string)
  description = "List of email addresses for budget and cost alerts"
  default     = ["devops@lunebi.com", "alerts@lunebi.com"]
}

variable "enable_cost_optimization" {
  type        = bool
  description = "Enable all cost optimization features"
  default     = true
}


variable "enable_gpu_workers" {
  description = "Enable GPU worker fleet"
  type        = bool
  default     = true
}


# GPU Fleet Toggles
variable "gpu_asg_min" {
  description = "GPU ASG minimum instances"
  type        = number
  default     = 0
}

variable "gpu_asg_desired" {
  description = "GPU ASG desired instances"
  type        = number
  default     = 0
}

variable "gpu_asg_max" {
  description = "GPU ASG maximum instances"
  type        = number
  default     = 2
}

variable "gpu_use_spot_only" {
  description = "Use Spot instances only"
  type        = bool
  default     = true
}

variable "gpu_enable_warm_pool" {
  description = "Enable warm pool"
  type        = bool
  default     = false
}

# ============================================================================
# COST CONTROL & BUDGETING VARIABLES
# ============================================================================

variable "cost_guardrails_enabled" {
  description = "Enable strict cost control guardrails and budget alarms"
  type        = bool
  default     = true
}

variable "max_monthly_gpu_budget" {
  description = "Maximum monthly GPU cost budget in USD"
  type        = number
  default     = 1000
  
  validation {
    condition     = var.max_monthly_gpu_budget >= 100
    error_message = "Budget must be at least $100 to allow for basic operation."
  }
}

variable "budget_alert_email" {
  description = "Email address to receive budget alerts"
  type        = string
  default     = "alerts@lunebi.com"
  
  validation {
    condition     = can(regex("^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$", var.budget_alert_email))
    error_message = "Must be a valid email address."
  }
}

# ============================================================================
# TEST MODE COST CONTROLS
# ============================================================================

variable "test_mode_max_instances" {
  description = "Maximum GPU instances allowed in test mode (strict cost control)"
  type        = number
  default     = 2
  
  validation {
    condition     = var.test_mode_max_instances >= 0 && var.test_mode_max_instances <= 2
    error_message = "Test mode cannot exceed 2 instances for cost safety."
  }
}

variable "test_mode_manual_scaling_desired" {
  description = "Desired instances in test mode (must be 0 for cost savings)"
  type        = number
  default     = 0
  
  validation {
    condition     = var.test_mode_manual_scaling_desired == 0
    error_message = "Test mode must have desired=0 to prevent idle GPU costs."
  }
}

# ============================================================================
# PRODUCTION MODE COST CONTROLS
# ============================================================================

variable "prod_mode_max_gpu_instances" {
  description = "Maximum GPU instances allowed in production mode"
  type        = number
  default     = 10
  
  validation {
    condition     = var.prod_mode_max_gpu_instances >= 1 && var.prod_mode_max_gpu_instances <= 50
    error_message = "Production mode must have between 1 and 50 instances."
  }
}

variable "prod_mode_min_gpu_instances" {
  description = "Minimum GPU instances in production mode"
  type        = number
  default     = 1
  
  validation {
    condition     = var.prod_mode_min_gpu_instances >= 0
    error_message = "Minimum instances cannot be negative."
  }
}

variable "prod_mode_desired_gpu_instances" {
  description = "Desired GPU instances in production mode"
  type        = number
  default     = 2
  
  validation {
    condition     = var.prod_mode_desired_gpu_instances >= var.prod_mode_min_gpu_instances && var.prod_mode_desired_gpu_instances <= var.prod_mode_max_gpu_instances
    error_message = "Desired instances must be between min and max."
  }
}

# ============================================================================
# SPOT INSTANCE CONFIGURATION
# ============================================================================

variable "spot_fallback_enabled" {
  description = "Enable Spot instance fallback in test mode"
  type        = bool
  default     = true
}

# GPU Worker AMI ID (from Packer build)
variable "gpu_worker_ami_id" {
  description = "AMI ID for GPU workers built by Packer"
  type        = string
  default     = ""
}

# GPU Worker Version
variable "gpu_worker_version" {
  description = "Version tag for GPU workers"
  type        = string
  default     = "1.0.0"
}

variable "stories_table_name" {
  description = "stories_table_name"
  type = string
  
}
