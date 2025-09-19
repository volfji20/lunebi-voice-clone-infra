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

  signed_url_public_key_path = abspath(var.signed_url_public_key_path)

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

  iam_role = var.iam_role

  expire_segments_days  = var.expire_segments_days
  transition_final_days = var.transition_final_days
  stories_bucket_name   = var.stories_bucket_name

  cloudfront_distribution_arn = module.cdn_cloudfront.cloudfront_distribution_arn
  # Pass VPC Endpoint from network module
  s3_vpc_endpoint_id = module.network.s3_vpc_endpoint_id

  iam_role_policy = var.iam_role_policy

}




# -----------------------------
# Networking (VPC Endpoints)
# -----------------------------
module "network" {
  source                  = "../../modules/network"
  project                 = var.project
  env                     = var.env
  region                  = var.region
  vpc_id                  = var.vpc_id
  private_route_table_ids = var.private_route_table_ids
}




