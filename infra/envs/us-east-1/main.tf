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
  region                   = var.region
  vpc_cidr                 = "10.0.0.0/16"
  public_subnet_cidr       = "10.0.1.0/24"
  private_subnet_cidr      = "10.0.2.0/24"
  availability_zone        = var.region
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

  # Networking (pass these from your environment)
  private_subnets = module.network.private_subnets
  lambda_sg_id   = module.network.lambda_sg_id

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

module "queuing" {
  source = "../../modules/queuing"
  
  prefix                 = "${var.project}-${var.env}-${var.region}"
  mode                   = var.mode
  long_poll_seconds      = var.queue_long_poll_seconds
  max_receive_count      = var.queue_max_receive_count
  message_retention_days = 4
  dlq_retention_days     = 14
  region                 = var.region
  
  # Observability
  warning_alarm_actions  = []
  critical_alarm_actions = []
  
  # IAM Role ARNs for SQS policy
  api_lambda_role_arn    = module.api_lambda.lambda_role_arn
  gpu_worker_role_arn    = module.ddb.gpu_worker_role_arn
  cpu_mock_role_arn      = var.enable_cpu_mock_consumer ? module.ddb.cpu_mock_role_arn : ""
  
  tags = {
    Project     = var.project
    Environment = var.env
    Region      = var.region
    Module      = "queuing"
  }
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

  tags = {
    Project     = var.project
    Environment = var.env
    Region      = var.region
    Module      = "dynamodb"
  }
}
# CPU Mock Consumer Module (Test Mode only)
module "compute_gpu" {
  count = var.enable_cpu_mock_consumer ? 1 : 0
  
  source = "../../modules/compute_gpu"

  prefix              = "${var.project}-${var.env}-${var.region}"
  sqs_queue_url       = module.queuing.queue_url
  stories_table_name  = module.ddb.stories_table_name
  cpu_mock_role_arn   = module.ddb.cpu_mock_role_arn
  mock_min_ms         = 300
  mock_max_ms         = 800
  sqs_queue_arn = module.queuing.queue_arn

  tags = {
    Project     = var.project
    Environment = var.env
    Region      = var.region
    Module      = "cpu_mock"
  }
}

#home