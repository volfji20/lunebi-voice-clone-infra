locals {
  prefix = "${var.project}-${var.env}-${var.region}"
}

data "aws_caller_identity" "current" {}
##################################################
# AWS KMS KEY 
##################################################
resource "aws_kms_key" "stories_key" {
  description             = "KMS key for voiceclone stories bucket"
  deletion_window_in_days = 10
  enable_key_rotation     = true

  policy = jsonencode({
    Version = "2012-10-17"
    Id      = "KeyPolicyForCloudFrontAndIAMRole"
    Statement = [
      # Default root account access
      {
        Sid      = "AllowRootAccount"
        Effect   = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
        }
        Action   = "kms:*"
        Resource = "*"
      },

      # Allow CloudFront OAC to use the key for decryption
      {
        Sid      = "AllowCloudFrontOACDecrypt"
        Effect   = "Allow"
        Principal = {
          Service = "cloudfront.amazonaws.com"
        }
        Action = [
          "kms:Decrypt",
          "kms:DescribeKey"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = var.cloudfront_distribution_arn
          }
        }
      },

      # Allow IAM role (from your app) via VPCe
      {
        Sid      = "AllowIAMRoleDecryptViaVPCE"
        Effect   = "Allow"
        Principal = {
          AWS = var.iam_role
        }
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey*",
          "kms:DescribeKey"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:sourceVpce" = var.s3_vpc_endpoint_id
          }
        }
      }
    ]
  })
}



##################################################
# Lunebi Stories Bucket 
##################################################
resource "aws_s3_bucket" "stories" {
  bucket = var.stories_bucket_name

  tags = {
    Name        = "${local.prefix}"
    Environment = var.env
  }
}

# Block Public Access
resource "aws_s3_bucket_public_access_block" "stories" {
  bucket = aws_s3_bucket.stories.id

  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "stories" {
  bucket = aws_s3_bucket.stories.id

  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.stories_key.arn
      sse_algorithm     = "aws:kms"
    }
  }
}


resource "aws_s3_bucket_lifecycle_configuration" "stories" {
  bucket = aws_s3_bucket.stories.id

  # Expire all .m4s (7 days)
  rule {
    id     = "expire-m4s"
    status = "Enabled"

    filter {
      prefix = "stories/m4s/"
    }

    expiration {
      days = 7
    }
  }

  # Expire all .m3u8 (30 days)
  rule {
    id     = "expire-m3u8"
    status = "Enabled"

    filter {
      prefix = "stories/m3u8/"
    }

    expiration {
      days = 30
    }
  }

  # Finals retained (transition to STANDARD_IA after 30 days)
  rule {
    id     = "retain-finals"
    status = "Enabled"

    filter {
      prefix = "stories/finals/"
    }

    transition {
      days          = var.transition_final_days
      storage_class = "STANDARD_IA"
    }
  }
}



##################################################
# Stories Bucket Policy (OAC + IAM Role)
##################################################
resource "aws_s3_bucket_policy" "stories_policy" {
  bucket = aws_s3_bucket.stories.id

  policy = jsonencode({
    Version = "2012-10-17"
    Id      = "PolicyForCloudFrontAndIAMRole"
    Statement = [
      {
        Sid       = "AllowExistingCloudFront"
        Effect    = "Allow"
        Principal = { "Service" = "cloudfront.amazonaws.com" }
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.stories.arn}/*"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = var.cloudfront_distribution_arn
          }
        }
      },
      {
        Sid       = "AllowIAMRoleAccessViaVPCE"
        Effect    = "Allow"
        Principal = { "AWS" = var.iam_role }
        Action    = ["s3:GetObject","s3:PutObject"]
        Resource  = "${aws_s3_bucket.stories.arn}/*"
        Condition = {
          StringEquals = {
            "aws:sourceVpce" = var.s3_vpc_endpoint_id
          }
        }
      }
    ]
  })

  depends_on = [
    aws_s3_bucket.stories,
    var.s3_vpc_endpoint_id
  ]
}


##################################################
# IAM ROLE POLICY
##################################################

resource "aws_iam_role_policy" "app_access" {
  role = var.iam_role_policy

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject","s3:PutObject"]
        Resource = "${aws_s3_bucket.stories.arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = [
          "kms:Encrypt","kms:Decrypt","kms:ReEncrypt*",
          "kms:GenerateDataKey*","kms:DescribeKey"
        ]
        Resource = aws_kms_key.stories_key.arn
      }
    ]
  })

  depends_on = [
    aws_s3_bucket.stories,
    aws_kms_key.stories_key
  ]
}





