# ============================================================================
# PROJECT & ENVIRONMENT VARIABLES
# ============================================================================

variable "project" {
  description = "Project name (e.g., voiceclone)"
  type        = string
  default     = "voiceclone"
}

variable "env" {
  description = "Environment (e.g., prod, test, dev)"
  type        = string
  default     = "test"
}

variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "prefix" {
  description = "Resource name prefix (project-env-region)"
  type        = string
  default     = "voiceclone-test-us-east-1"
}

variable "tags" {
  description = "Common tags for all resources"
  type        = map(string)
  default = {
    Project     = "voiceclone"
    Environment = "test"
    ManagedBy   = "terraform"
  }
}

# ============================================================================
# DEPLOYMENT MODE CONFIGURATION
# ============================================================================

variable "mode" {
  description = "Deployment mode: 'test' or 'prod'"
  type        = string
  default     = "test"

  validation {
    condition     = contains(["test", "prod"], var.mode)
    error_message = "Mode must be either 'test' or 'prod'."
  }
}

variable "enable_cpu_mock_consumer" {
  description = "Enable CPU mock consumer for test mode"
  type        = bool
  default     = true
}

variable "enable_gpu_workers" {
  description = "Enable GPU worker fleet"
  type        = bool
  default     = true
}

# ============================================================================
# GPU FLEET TOGGLES (Blueprint Naming Convention)
# ============================================================================

variable "gpu_asg_min" {
  description = "GPU ASG minimum instances: test: 0; prod: ≥1"
  type        = number
  default     = 0
}

variable "gpu_asg_desired" {
  description = "GPU ASG desired instances: test: 0; prod: small baseline (e.g., 1–2)"
  type        = number
  default     = 0
}

variable "gpu_asg_max" {
  description = "GPU ASG maximum instances: test: 1–2; prod: sized for peak"
  type        = number
  default     = 2
}

variable "gpu_use_spot_only" {
  description = "Use Spot instances only (true for test mode)"
  type        = bool
  default     = true
}

variable "gpu_enable_warm_pool" {
  description = "Enable warm pool for faster scaling (false for test mode)"
  type        = bool
  default     = false
}

# ============================================================================
# GPU INSTANCE CONFIGURATION
# ============================================================================

variable "gpu_instance_type" {
  description = "Default GPU instance type"
  type        = string
  default     = "g6.xlarge"
}

variable "gpu_worker_ami_id" {
  description = "Custom GPU worker AMI ID (for blue/green deployments)"
  type        = string
  default     = ""
}

variable "gpu_worker_version" {
  description = "GPU worker AMI version for blue/green deployments"
  type        = string
  default     = "1.0.0"
}

# ============================================================================
# PRODUCTION MODE SPECIFIC SETTINGS
# ============================================================================

variable "prod_mode_min_gpu_instances" {
  description = "Minimum number of GPU instances in production mode"
  type        = number
  default     = 1
}

variable "prod_mode_max_gpu_instances" {
  description = "Maximum number of GPU instances in production mode"
  type        = number
  default     = 10
}

variable "prod_mode_desired_gpu_instances" {
  description = "Desired number of GPU instances in production mode"
  type        = number
  default     = 2
}

variable "prod_on_demand_base_capacity" {
  description = "On-Demand base capacity in production mode"
  type        = number
  default     = 1
}

variable "prod_on_demand_percentage_above_base" {
  description = "On-Demand percentage above base capacity in production mode"
  type        = number
  default     = 20
}

# ============================================================================
# TEST MODE SPECIFIC SETTINGS
# ============================================================================

variable "test_mode_max_gpu_instances" {
  description = "Maximum number of GPU instances in test mode"
  type        = number
  default     = 2
}

variable "test_mode_manual_scaling_desired" {
  description = "Manual scaling desired capacity in test mode"
  type        = number
  default     = 0
}

variable "spot_fallback_enabled" {
  description = "Enable Spot instance fallback in test mode"
  type        = bool
  default     = true
}

# ============================================================================
# WARM POOL CONFIGURATION
# ============================================================================

variable "enable_warm_pool" {
  description = "Enable warm pool for production mode"
  type        = bool
  default     = false
}

variable "warm_pool_min_size" {
  description = "Minimum warm pool size"
  type        = number
  default     = 1
}

variable "warm_pool_max_prepared_capacity" {
  description = "Maximum prepared capacity for warm pool"
  type        = number
  default     = 2
}

# ============================================================================
# NETWORKING VARIABLES
# ============================================================================

variable "vpc_id" {
  description = "VPC ID for security groups and networking"
  type        = string
  default     = ""
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs for GPU workers"
  type        = list(string)
  default     = []
}

variable "gpu_worker_sg_id" {
  description = "Security group ID for GPU workers"
  type        = string
  default     = ""
}

# ============================================================================
# QUEUE & STORAGE CONFIGURATION
# ============================================================================

variable "sqs_queue_url" {
  description = "SQS queue URL for story tasks"
  type        = string
  default     = ""
}

variable "sqs_queue_arn" {
  description = "SQS queue ARN for story tasks"
  type        = string
  default     = ""
}

variable "stories_bucket" {
  description = "S3 bucket name for stories"
  type        = string
  default     = ""
}

variable "stories_table_name" {
  description = "DynamoDB stories table name"
  type        = string
  default     = "lunebi-prod-us-east-1-stories"
}

variable "voices_table_name" {
  description = "DynamoDB voices table name"
  type        = string
  default     = ""
}

# ============================================================================
# CPU MOCK CONFIGURATION (TEST MODE ONLY)
# ============================================================================

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

variable "cpu_mock_role_arn" {
  description = "IAM role ARN for CPU mock Lambda"
  type        = string
  default     = ""
}

# ============================================================================
# SECURITY & IAM CONFIGURATION
# ============================================================================

variable "gpu_worker_instance_profile_name" {
  description = "IAM instance profile name for GPU workers"
  type        = string
  default     = ""
}

# ============================================================================
# AUTOSCALING & OBSERVABILITY CONFIGURATION
# ============================================================================

variable "critical_alarm_actions" {
  description = "SNS topic ARN for critical alarm notifications"
  type        = list(string)
  default = []
}

variable "sqs_backlog_threshold" {
  description = "SQS backlog threshold for scaling"
  type        = number
  default     = 30
}

variable "scale_in_cooldown" {
  description = "Scale-in cooldown period in seconds"
  type        = number
  default     = 300
}

variable "ttfa_p95_threshold" {
  description = "TTFA p95 threshold for SLO alarms"
  type        = number
  default     = 1.5
}

# ============================================================================
# SCHEDULED SCALING ACTIONS
# ============================================================================

variable "scheduled_scaling_actions" {
  description = "List of scheduled scaling actions for known traffic spikes"
  type = list(object({
    name            = string
    min_size        = number
    max_size        = number
    desired_capacity = number
    recurrence      = string
  }))
  default = [
    {
      name            = "business-hours-weekdays"
      min_size        = 2
      max_size        = 8
      desired_capacity = 3
      recurrence      = "0 9 * * 1-5"  # 9 AM UTC on weekdays
    },
    {
      name            = "weekend-morning"
      min_size        = 1
      max_size        = 6
      desired_capacity = 2
      recurrence      = "0 11 * * 0,6" # 11 AM UTC on weekends
    }
  ]
}

# ============================================================================
# CLOUDFRONT & CDN CONFIGURATION
# ============================================================================

variable "cloudfront_distribution_id" {
  description = "CloudFront distribution ID for segment 404 monitoring"
  type        = string
  default     = ""
}

variable "api_gateway_id" {
  description = "API Gateway ID for 5xx error monitoring"
  type        = string
  default     = ""
}

# ============================================================================
# LOGGING & MONITORING
# ============================================================================

variable "cloudwatch_log_group" {
  description = "CloudWatch log group name for GPU workers"
  type        = string
  default     = "/aws/ec2/voiceclone-gpu-workers"
}

variable "aws_region" {
  description = "AWS region for CloudWatch metrics"
  type        = string
  default     = "us-east-1"
}

# ============================================================================
# BLUE/GREEN DEPLOYMENT VARIABLES
# ============================================================================

variable "active_deployment_color" {
  description = "Active deployment color: 'blue' or 'green'"
  type        = string
  default     = "blue"

  validation {
    condition     = contains(["blue", "green"], var.active_deployment_color)
    error_message = "Active deployment color must be 'blue' or 'green'."
  }
}

variable "enable_blue_green_deployment" {
  description = "Enable blue/green deployment infrastructure"
  type        = bool
  default     = false
}

# ============================================================================
# COST CONTROL & BUDGETING
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
}

variable "budget_alert_email" {
  description = "Email address to receive budget alerts"
  type        = string
  default     = "alerts@lunebi.com"
}

# ============================================================================
# LIFECYCLE & RETENTION
# ============================================================================

variable "stories_ttl_days" {
  description = "TTL in days for stories table"
  type        = number
  default     = 30
}

variable "queue_visibility_seconds" {
  description = "SQS message visibility timeout in seconds"
  type        = number
  default     = 60
}

variable "queue_long_poll_seconds" {
  description = "SQS long polling duration in seconds"
  type        = number
  default     = 20
}

variable "queue_max_receive_count" {
  description = "SQS max receive count before DLQ"
  type        = number
  default     = 5
}

variable "sqs_queue_name" {
  description = "sqs queue name"
  type = string
  
}

variable "test_mode_alert_arns" {
  description = "SNS topic ARNs for test mode alerts"
  type        = list(string)
  default     = []  # Empty list by default - alerts will be created but won't trigger notifications
}

# ============================================================================
# RISK & MITIGATIONS - MISSING VARIABLES
# ============================================================================

variable "gpu_asg_name" {
  description = "GPU Auto Scaling Group name (for alarms without circular dependency)"
  type        = string
  default     = ""
}

variable "cpu_mock_fallback_enabled" {
  description = "Enable automatic CPU mock fallback when Spot capacity is unavailable"
  type        = bool
  default     = true
}

variable "spot_interruption_handling" {
  description = "How to handle Spot interruption: 'shutdown_graceful', 'activate_mock_fallback', 'notify_only'"
  type        = string
  default     = "activate_mock_fallback"
  
  validation {
    condition     = contains(["shutdown_graceful", "activate_mock_fallback", "notify_only"], var.spot_interruption_handling)
    error_message = "Spot interruption handling must be one of: shutdown_graceful, activate_mock_fallback, notify_only."
  }
}

variable "enable_sqs_schema_validation" {
  description = "Enable SQS message schema validation to prevent schema drift"
  type        = bool
  default     = true
}

variable "sqs_schema_version" {
  description = "SQS message schema version for contract testing"
  type        = string
  default     = "1.0.0"
}

variable "key_name" {
  description = "SSH key pair name"
  type        = string
  default     = ""
}

variable "gpu_worker_instance_profile" {
  description = "IAM instance profile for GPU workers"
  type        = string
}

variable "cdn_stories" {
  description = "cloudfront distribution stories id"
  type = string
}

variable "gpu_worker_role_name" {
  description = "IAM role"
  type = string
}