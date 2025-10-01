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
jwt_audience = "https://api.lunebi.com"
