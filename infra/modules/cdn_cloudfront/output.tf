# -----------------------------
# Outputs
# -----------------------------

# For CloudFront, the ACM cert must be passed in via variable, not discoverable via data source
output "cdn_cert_arn" {
  value = var.cdn_cert_arn
}


# Outputs
output "cdn_cert_status" {
  value = data.aws_acm_certificate.cdn.status
}

output "api_cert_status" {
  value = data.aws_acm_certificate.api.status
}

# cdn/outputs.tf
output "oac_id" {
  value = aws_cloudfront_origin_access_control.s3_oac.id
}

output "oac_name" {
  value = aws_cloudfront_origin_access_control.s3_oac.name
}

output "cloudfront_distribution_arn" {
  description = "ARN of the CloudFront distribution"
  value       = aws_cloudfront_distribution.stories.arn
}

