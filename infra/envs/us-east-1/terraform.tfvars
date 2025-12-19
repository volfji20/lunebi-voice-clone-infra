# -----------------------------
# Project / Environment / Region
# -----------------------------
project = "lunebi"
env     = "prod"
region  = "us-east-1"

# -----------------------------
# CDN / API Domains
# -----------------------------
cdn_domain = "cdn.lunebi.com"
api_domain = "api.lunebi.com"

# -----------------------------
# Signed URLs
# -----------------------------

# -----------------------------
# ACM Certificates (CDN + API)
# -----------------------------
cdn_cert_arn = "arn:aws:acm:us-east-1:579897422848:certificate/2252db57-bf9d-4c85-bbc8-fd4d6d4ce94e"
api_cert_arn = "arn:aws:acm:us-east-1:579897422848:certificate/fbd2b0f4-0b03-41b8-93b5-05b9c329391f"

# -----------------------------
# Existing CloudFront Distributions
# -----------------------------
existing_cdn_distribution_id = "E1T7A0PP1OXWZJ"

# -----------------------------
# IAM / Storage Settings
# -----------------------------
iam_role_name        = "lunebi-runtime-prop-role-oqc7t7tz"

expire_segments_days  = 7
transition_final_days = 90


stories_bucket_name="voiceclone-stories-prod-us-east-1"



# App secrets & configs
secret_value = "super-secret-key"
config_value = "some-config-value"

# Features
jwt_authorizer_enabled = false

jwt_issuer   = "https://mock.lunebi.dev"


long_poll_seconds     = 20
max_receive_count     = 5



# Cost Control Configuration


# Environment Budget
monthly_budget_usd          = 500
alert_emails                = ["devops@lunebi.com", "alerts@lunebi.com"]
enable_cost_optimization    = true

# Test Mode Configuration
mode                    = "test"
enable_cpu_mock_consumer = true
enable_gpu_workers      = true
gpu_asg_min             = 0
gpu_asg_desired         = 0
gpu_asg_max             = 2
gpu_use_spot_only       = true
gpu_enable_warm_pool    = false

# Cost Control & Budgeting
cost_guardrails_enabled     = true
max_monthly_gpu_budget      = 1000
budget_alert_email          = "alerts@lunebi.com"

# Test Mode - Strict Cost Controls
test_mode_max_instances     = 2
test_mode_manual_scaling_desired = 0

# Production Mode - Balanced Cost/Performance  
prod_mode_max_gpu_instances = 10
prod_mode_min_gpu_instances = 1
prod_mode_desired_gpu_instances = 2

spot_fallback_enabled = true

stories_table_name = "lunebi-prod-us-east-1-stories"