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
# Secrets & Config
# -------------------------
variable "secret_value" {
  description = "Initial secret value for application (overwritten later in Secrets Manager)"
  type        = string
  default     = "changeme"
}

variable "config_value" {
  description = "Initial configuration JSON string for SSM parameter"
  type        = string
  default     = "{\"feature_x\":true}"
}

variable "api_cert_arn" {
  description = "API Cert"
  type        = string
}