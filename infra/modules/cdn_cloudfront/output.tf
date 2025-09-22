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


output "oac_name" {
  value = aws_cloudfront_origin_access_control.s3_oac.name
}

# -----------------------------
# CloudFront / OAC Outputs
# -----------------------------
output "distribution_id" {
  description = "CloudFront Distribution ID for stories"
  value       = aws_cloudfront_distribution.stories.id
}

output "distribution_domain_name" {
  description = "CloudFront Distribution Domain Name for stories"
  value       = aws_cloudfront_distribution.stories.domain_name
}

output "oac_arn" {
  description = "IAM ARN of the CloudFront Origin Access Control (OAC)"
  value       = aws_cloudfront_origin_access_control.s3_oac.arn
}


