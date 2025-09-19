terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
      configuration_aliases = [aws.us_east_1]
    }
  }
}

locals {
  prefix = "${var.project}-${var.env}-${var.region}"
}

# -----------------------------
# Cache Policies
# -----------------------------
resource "aws_cloudfront_cache_policy" "m3u8" {
  name        = "${local.prefix}-m3u8-policy"
  default_ttl = 3
  max_ttl     = 30
  min_ttl     = 0

  parameters_in_cache_key_and_forwarded_to_origin {
    cookies_config { cookie_behavior = "none" }
    headers_config { header_behavior = "none" }
    query_strings_config { query_string_behavior = "none" }

    enable_accept_encoding_brotli = true
    enable_accept_encoding_gzip   = true
  }
}

resource "aws_cloudfront_cache_policy" "segments" {
  name        = "${local.prefix}-segments-policy"
  default_ttl = 31536000
  max_ttl     = 31536000
  min_ttl     = 31536000

  parameters_in_cache_key_and_forwarded_to_origin {
    cookies_config { cookie_behavior = "none" }
    headers_config { header_behavior = "none" }
    query_strings_config { query_string_behavior = "none" }

    enable_accept_encoding_brotli = false
    enable_accept_encoding_gzip   = false
  }
}

# -----------------------------
# Signed URL Key Group
# -----------------------------
resource "aws_cloudfront_public_key" "signed_urls_key" {
  name        = "lunebi-${var.env}-public-key"
  comment     = "Public key for signed URLs"
  encoded_key = file(var.signed_url_public_key_path)
}

resource "aws_cloudfront_key_group" "signed_urls" {
  name  = "${local.prefix}-key-group"
  items = [aws_cloudfront_public_key.signed_urls_key.id]
}

# -----------------------------
# Lookup ACM Certs (cdn + api)
# -----------------------------
data "aws_acm_certificate" "cdn" {
  provider = aws.us_east_1
  domain      = var.cdn_domain
  most_recent = true
  statuses    = ["ISSUED", "PENDING_VALIDATION"]
}

data "aws_acm_certificate" "api" {
  provider = aws.us_east_1
  domain      = var.api_domain
  most_recent = true
  statuses    = ["ISSUED", "PENDING_VALIDATION"]
}

# -----------------------------
# Validate ACM certs
# -----------------------------
resource "null_resource" "validate_certs" {
  lifecycle {
    precondition {
      condition     = data.aws_acm_certificate.cdn.status == "ISSUED"
      error_message = "❌ CDN ACM cert not issued (status: ${data.aws_acm_certificate.cdn.status})."
    }

    precondition {
      condition     = data.aws_acm_certificate.api.status == "ISSUED"
      error_message = "❌ API ACM cert not issued (status: ${data.aws_acm_certificate.api.status})."
    }
  }
}


# -----------------------------
# Origin Access Control (OAC)
# -----------------------------
resource "aws_cloudfront_origin_access_control" "s3_oac" {
  name                              = "${local.prefix}-s3-oac"
  description                       = "OAC for stories S3 bucket"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "stories" {
  enabled         = true
  is_ipv6_enabled = true
  price_class     = "PriceClass_100"
  http_version    = "http2and3" # keep HTTP/3

  aliases = [var.cdn_domain]



  # --- NEW origin (with OAC) ---
  origin {
    domain_name              = var.stories_bucket_domain_name
    origin_id                = "stories-s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.s3_oac.id
  }

  default_cache_behavior {
    target_origin_id       = "stories-s3"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]

    cache_policy_id    = aws_cloudfront_cache_policy.m3u8.id
    trusted_key_groups = [aws_cloudfront_key_group.signed_urls.id]
    compress           = true
  }

  ordered_cache_behavior {
    path_pattern           = "*.m3u8"
    target_origin_id       = "stories-s3"
    viewer_protocol_policy = "redirect-to-https"

    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]

    cache_policy_id    = aws_cloudfront_cache_policy.m3u8.id
    trusted_key_groups = [aws_cloudfront_key_group.signed_urls.id]
    compress           = true
  }

  ordered_cache_behavior {
    path_pattern           = "*.m4s"
    target_origin_id       = "stories-s3"
    viewer_protocol_policy = "redirect-to-https"

    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]

    cache_policy_id    = aws_cloudfront_cache_policy.segments.id
    trusted_key_groups = [aws_cloudfront_key_group.signed_urls.id]
    compress           = false
  }


  #  Init Segment (init.mp4) 
  ordered_cache_behavior {
    path_pattern           = "init.mp4"
    target_origin_id       = "stories-s3"
    viewer_protocol_policy = "redirect-to-https"

    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]

    cache_policy_id    = aws_cloudfront_cache_policy.segments.id
    trusted_key_groups = [aws_cloudfront_key_group.signed_urls.id]
    compress           = false
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = data.aws_acm_certificate.cdn.arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  tags = {
    Name        = "${local.prefix}-stories-cdn"
    Environment = var.env
  }
}
