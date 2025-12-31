# -----------------------------
# Providers
# -----------------------------
provider "aws" {
  region = var.region
}

# CloudFront / ACM certs must be in us-east-1
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}


# -----------------------------
# CloudFront (CDN + API)
# -----------------------------
module "cdn_cloudfront" {
  source = "../../modules/cdn_cloudfront"

  providers = {
    aws           = aws
    aws.us_east_1 = aws.us_east_1
  }

  project = var.project
  env     = var.env
  region  = var.region

  # Required inputs
  cdn_domain                 = var.cdn_domain
  api_domain                 = var.api_domain

  signed_url_public_key = var.signed_url_public_key

  # ACM certs (validation only, not attached)
  cdn_cert_arn = var.cdn_cert_arn
  api_cert_arn = var.api_cert_arn

  tags = {
    Owner   = "DevOps"
    Purpose = "CDN"
  }
  stories_bucket_domain_name = module.storage.stories_bucket_domain_name
  web_acl_id      = null
  cloudfront_distribution_cdn = ""
  
}


# -----------------------------
# Storage (S3 + lifecycle + policy)
# -----------------------------
module "storage" {
  source = "../../modules/storage"

  project = var.project
  env     = var.env
  region  = var.region


  expire_segments_days  = var.expire_segments_days
  transition_final_days = var.transition_final_days
  stories_bucket_name   = var.stories_bucket_name

  # Pass VPC Endpoint from network module
  s3_vpc_endpoint_id = module.network.s3_vpc_endpoint_id

  iam_role_name = var.iam_role_name
  oac_arn = module.cdn_cloudfront.oac_arn

}


module "network" {
  source = "../../modules/network"

  project                  = var.project
  env                      = var.env
  region               = var.region
  vpc_cidr                 = "10.0.0.0/16"
  public_subnet_cidr       = "10.0.1.0/24"
  private_subnet_cidr      = "10.0.2.0/24"
  availability_zone        = "${var.region}a" 

}

# -----------------------------
# API (Lambda + API Gateway)
# -----------------------------
module "api_lambda" {
  source = "../../modules/api_lambda"

  # Core naming
  project = var.project
  env     = var.env
  region  = var.region

  # Secrets & Config
  secret_value = var.secret_value
  config_value = var.config_value

  # Feature toggle
  jwt_authorizer_enabled = var.jwt_authorizer_enabled

  # Custom domain certificate
  api_cert_arn = var.api_cert_arn


  # JWT Authorizer config (required when enabled)
  jwt_issuer   = var.jwt_issuer

  sqs_queue_arn = module.queuing.queue_arn
  voices_table_arn = module.ddb.voices_table_arn

  stories_table_arn = module.ddb.stories_table_arn
  s3Bucket_arn = module.storage.stories_bucket_arn
  domain_name = var.api_domain
  jwt_private_key = "" 
  JWKS            = ""
  ddb_kms_key_arn = module.ddb.kms_key_arn
  s3_bucket_name = var.stories_bucket_name
  sqs_queue_url = module.queuing.queue_url
  stories_table_name = module.ddb.stories_table_name
  voices_table_name = module.ddb.voices_table_name
  stories_kms_key_arn = module.storage.stories_kms_key_arn

}

# -----------------------------
# DynamoDB (Tables + IAM roles)
# -----------------------------
module "ddb" {
  source = "../../modules/ddb"

  prefix          = "${var.project}-${var.env}-${var.region}"
  project         = var.project
  env             = var.env
  stories_ttl_days = var.stories_ttl_days
  kms_key_arn     = null  # Let DDB module create its own KMS key
  region          = var.region
  
  # Observability - pass empty for now, will be connected later
  critical_alarm_actions = []
  
  # IAM role dependencies
  sqs_queue_arn    = module.queuing.queue_arn
  stories_bucket_arn = module.storage.stories_bucket_arn
  enable_cpu_mock  = var.enable_cpu_mock_consumer
  api_lambda_role_arn = module.api_lambda.api_lambda_role_arn
  cpu_mock_role_arn = module.ddb.cpu_mock_role_arn

  tags = {
    Project     = var.project
    Environment = var.env
    Region      = var.region
    Module      = "dynamodb"
  }
}
# CPU Mock Consumer Module (Test Mode only)
module "compute_gpu" {
  source = "../../modules/compute_gpu"

  gpu_worker_ami_id           = var.gpu_worker_ami_id
  gpu_worker_instance_profile = module.ddb.gpu_worker_instance_profile_name
  gpu_worker_sg_id            = module.network.gpu_worker_security_group_id

  # Mode Configuration
  mode                    = var.mode
  enable_gpu_workers      = var.enable_gpu_workers
  stories_table_name      = var.stories_table_name
  # GPU Fleet Configuration
  gpu_asg_min             = var.gpu_asg_min
  gpu_asg_desired         = var.gpu_asg_desired
  gpu_asg_max             = var.gpu_asg_max
  gpu_use_spot_only       = var.gpu_use_spot_only
  gpu_enable_warm_pool    = var.gpu_enable_warm_pool
  gpu_worker_role_name    = module.ddb.gpu_worker_role_name
  
  # Cost Control & Budgeting
  cost_guardrails_enabled     = var.cost_guardrails_enabled
  max_monthly_gpu_budget      = var.max_monthly_gpu_budget
  budget_alert_email          = var.budget_alert_email

  # Test Mode Cost Controls
  test_mode_max_gpu_instances = var.test_mode_max_instances
  test_mode_manual_scaling_desired = var.test_mode_manual_scaling_desired

  # Production Mode Cost Controls
  prod_mode_max_gpu_instances = var.prod_mode_max_gpu_instances
  prod_mode_min_gpu_instances = var.prod_mode_min_gpu_instances
  prod_mode_desired_gpu_instances = var.prod_mode_desired_gpu_instances

  # SQS Configuration for Autoscaling
  sqs_queue_name          = module.queuing.queue_name
  sqs_queue_url           = module.queuing.queue_url
  sqs_queue_arn           = module.queuing.queue_arn
  
  # Test Mode Alerts
  test_mode_alert_arns    = []  # Empty for now, or create SNS topic
  
  # CPU Mock Configuration (only for test mode)
  enable_cpu_mock_consumer = var.enable_cpu_mock_consumer
  mock_min_ms             = 300
  mock_max_ms             = 800
  
  # IAM Configuration
  cpu_mock_role_arn       = module.ddb.cpu_mock_role_arn
  cdn_stories             = module.cdn_cloudfront.distribution_id
  private_subnet_ids      = module.network.private_subnet_ids
  # Project/Environment
  project                 = var.project
  env                     = var.env
  region                  = var.region
  prefix                  = "${var.project}-${var.env}-${var.region}"

  tags = {
    Project     = var.project
    Environment = var.env
    Region      = var.region
    Module      = "compute_gpu"
  }
}


module "queuing" {
  source = "../../modules/queuing"
  
  # Basic Configuration
  prefix                 = "${var.project}-${var.env}-${var.region}"
  mode                   = var.mode
  long_poll_seconds      = var.queue_long_poll_seconds
  max_receive_count      = var.queue_max_receive_count
  message_retention_days = 4
  dlq_retention_days     = 14
  region                 = var.region
  api_gateway_id         = module.api_lambda.api_gateway_id
  gpu_asg_name           = module.compute_gpu.gpu_asg_name

  # Spot Configuration
  spot_fallback_enabled  = var.spot_fallback_enabled

  warning_alarm_actions  = []
  critical_alarm_actions = []
  
  # Remove all external IAM role dependencies
  api_lambda_role_arn    = ""  
  gpu_worker_role_arn    = "" 
  cpu_mock_role_arn      = "" 
  
  tags = {
    Project     = var.project
    Environment = var.env
    Region      = var.region
    Module      = "queuing"
  }
}