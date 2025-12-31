# KMS Key for DynamoDB encryption (if not provided externally)
resource "aws_kms_key" "dynamodb" {
  count = var.kms_key_arn == null ? 1 : 0
  
  description             = "KMS key for ${var.prefix} DynamoDB encryption"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "Enable IAM User Permissions"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
        }
        Action   = "kms:*"
        Resource = "*"
      },
      {
        Sid    = "Allow GPU Worker Role"
        Effect = "Allow"
        Principal = {
          AWS = aws_iam_role.gpu_worker.arn
        }
        Action = [
          "kms:Decrypt",
          "kms:Encrypt",
          "kms:GenerateDataKey",
          "kms:GenerateDataKeyWithoutPlaintext",
          "kms:ReEncrypt*",
          "kms:DescribeKey"
        ]
        Resource = "*"
      },
      {
        Sid    = "Allow Lambda Roles"
        Effect = "Allow"
        Principal = {
          AWS = [
            var.api_lambda_role_arn,
            var.cpu_mock_role_arn
          ]
        }
        Action = [
          "kms:Decrypt",
          "kms:Encrypt",
          "kms:GenerateDataKey",
          "kms:GenerateDataKeyWithoutPlaintext",
          "kms:ReEncrypt*",
          "kms:DescribeKey"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:ViaService" = "dynamodb.${var.region}.amazonaws.com"
          }
        }
      }
    ]
  })

  tags = var.tags
}
data "aws_caller_identity" "current" {}

locals {
  kms_key_arn = "arn:aws:kms:us-east-1:${data.aws_caller_identity.current.account_id}:key/65420a1b-5c61-4e54-b5ba-5541f8ec1fe9"
}
# voices table - No TTL, deletion via /voices/delete only
resource "aws_dynamodb_table" "voices" {
  name         = "${var.prefix}-voices"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "voice_id"

  attribute {
    name = "voice_id"
    type = "S"
  }

  # Server-side encryption with KMS
  server_side_encryption {
    enabled     = true
    kms_key_arn = local.kms_key_arn
  }

  # Point-in-time recovery for backups
  point_in_time_recovery {
    enabled = true
  }

  tags = merge(var.tags, {
    Purpose = "VoiceClone-Voices-Table"
  })

  ttl {
  attribute_name = "expire_at"  # Terraform says "expire_at"
  enabled        = true
}

  # Explicitly NO TTL configured (as per blueprint)
}

# stories table - With TTL for automatic cleanup
resource "aws_dynamodb_table" "stories" {
  name         = "${var.prefix}-stories"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "story_id"

  attribute {
    name = "story_id"
    type = "S"
  }

  # TTL configuration for automatic expiration
  ttl {
    attribute_name = "expire_at"
    enabled        = true
  }

  # Server-side encryption with KMS
  server_side_encryption {
    enabled     = true
    kms_key_arn = local.kms_key_arn
  }

  # Point-in-time recovery for backups
  point_in_time_recovery {
    enabled = true
  }

  tags = merge(var.tags, {
    Purpose = "VoiceClone-Stories-Table"
  })
}

# GPU Worker Role - Defined now, used in M4
resource "aws_iam_role" "gpu_worker" {
  name = "${var.prefix}-gpu-worker-profile"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "gpu_worker" {
  name = "${var.prefix}-gpu-worker-policy"
  role = aws_iam_role.gpu_worker.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # SQS: Receive, Delete, ChangeMessageVisibility
      {
        Sid    = "SQSMessageProcessing"
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:ChangeMessageVisibility",
          "sqs:GetQueueAttributes",
          "sqs:GetQueueUrl",
          "sqs:SendMessage" 
        ]
        Resource = [var.sqs_queue_arn]
      },
      # DynamoDB: GetItem (voices), UpdateItem (stories)
      {
        Sid    = "DynamoDBVoicesRead"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:Query",
          "dynamodb:DescribeTable"
        ]
        Resource = [
          aws_dynamodb_table.voices.arn,
          "${aws_dynamodb_table.voices.arn}/index/*"
        ]
      },
      {
        Sid    = "DynamoDBStoriesUpdate"
        Effect = "Allow"
        Action = [
          "dynamodb:UpdateItem",
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:DescribeTable"
        ]
        Resource = [aws_dynamodb_table.stories.arn]
      },
      # S3: PutObject to stories/${story_id}/* only (with SSE-KMS)
      {
        Sid    = "S3StorySegmentsWrite"
        Effect = "Allow"
        Action = [
          "s3:GetObject",       # ✅ ADDED
          "s3:HeadObject",      # ✅ ADDED - FIX FOR 403 ERROR
          "s3:DeleteObject", 
          "s3:PutObject",
          "s3:PutObjectAcl"
        ]
        Resource = ["${var.stories_bucket_arn}/stories/*"]
      },
      # S3: Need GetBucketLocation for region detection
      {
        Sid    = "S3BucketInfo"
        Effect = "Allow"
        Action = [
          "s3:GetBucketLocation",
          "s3:ListBucket"
        ]
        Resource = [var.stories_bucket_arn]
      },
      # KMS: Full permissions for the specific KMS key
      {
        Sid    = "KMSAccess"
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:Encrypt",
          "kms:GenerateDataKey",
          "kms:GenerateDataKeyWithoutPlaintext",
          "kms:ReEncrypt*",
          "kms:DescribeKey"
        ]
        Resource = [local.kms_key_arn]
      },
      # KMS: Also need to allow these for key policy to work
      {
        Sid    = "KMSKeyAlias"
        Effect = "Allow"
        Action = [
          "kms:ListAliases",
          "kms:ListKeys"
        ]
        Resource = ["*"]
      },
      {
        Sid = "DynamoDBVoicesScan",
        Effect = "Allow",
        Action = [
          "dynamodb:Scan"
        ],
        Resource= [
          "*"
        ]
      },
      # CloudWatch Logs for monitoring
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogStreams"
        ]
        Resource = ["arn:aws:logs:*:*:*"]
      },
      # EC2 Instance Metadata (for IMDSv2)
      {
        Sid    = "EC2InstanceMetadata"
        Effect = "Allow"
        Action = [
          "ec2:DescribeInstances",
          "ec2:DescribeTags"
        ]
        Resource = ["*"]
      },
      # SSM: Required for Session Manager, parameter store, etc.
      {
        Sid    = "SSMAccess"
        Effect = "Allow"
        Action = [
          "ssm:DescribeParameters",
          "ssm:GetParameters",
          "ssm:GetParameter",
          "ssm:PutParameter",
          "ssm:DeleteParameter",
          "ssm:GetParametersByPath",
          "ssm:DescribeInstanceInformation",
          "ssm:CreateAssociation",
          "ssm:UpdateAssociation",
          "ssm:UpdateInstanceAssociationStatus",
          "ssm:ListAssociations",
          "ssm:ListInstanceAssociations",
          "ssm:DescribeAssociation",
          "ssmmessages:CreateControlChannel",
          "ssmmessages:CreateDataChannel",
          "ssmmessages:OpenControlChannel",
          "ssmmessages:OpenDataChannel",
          "ssm-guiconnect:*",
          "ec2messages:AcknowledgeMessage",
          "ec2messages:DeleteMessage",
          "ec2messages:FailMessage",
          "ec2messages:GetEndpoint",
          "ec2messages:GetMessages",
          "ec2messages:SendReply"
        ]
        Resource = ["*"]
      },
      # S3: For SSM documents and logs
      {
        Sid    = "SSMS3Access"
        Effect = "Allow"
        Action = [
          "s3:GetEncryptionConfiguration",
          "s3:PutEncryptionConfiguration"
        ]
        Resource = ["arn:aws:s3:::amazon-ssm-*", "arn:aws:s3:::aws-ssm-*"]
      }
    ]
  })
}

# Instance Profile for GPU Workers (EC2)
resource "aws_iam_instance_profile" "gpu_worker" {
  name = "${var.prefix}-gpu-worker-profile"
  role = aws_iam_role.gpu_worker.name

  tags = var.tags
}

# CPU Mock Role - Test Mode only
resource "aws_iam_role" "cpu_mock" {
  count = var.enable_cpu_mock ? 1 : 0
  name  = "${var.prefix}-cpu-mock"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "cpu_mock" {
  count = var.enable_cpu_mock ? 1 : 0
  name  = "${var.prefix}-cpu-mock-policy"
  role  = aws_iam_role.cpu_mock[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # SQS: Same as GPU workers - Receive, Delete, ChangeMessageVisibility
      {
        Sid    = "SQSMessageProcessing"
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:ChangeMessageVisibility",
          "sqs:GetQueueAttributes" 
        ]
        Resource = [var.sqs_queue_arn]
      },
      # DynamoDB: Same DDB writes as workers - GetItem (voices), UpdateItem (stories)
      {
        Sid    = "DynamoDBVoicesRead"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem"
        ]
        Resource = [aws_dynamodb_table.voices.arn]
      },
      {
        Sid    = "DynamoDBStoriesUpdate"
        Effect = "Allow"
        Action = [
          "dynamodb:UpdateItem"
        ]
        Resource = [aws_dynamodb_table.stories.arn]
      },
      # KMS: Encrypt/Decrypt for DynamoDB
      {
        Sid    = "KMSAccess"
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey"
        ]
        Resource = [local.kms_key_arn]
      },
      # CloudWatch Logs for Lambda
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = ["arn:aws:logs:*:*:*"]
      }
    ]
  })
}

# ========================
# OBSERVABILITY
# ========================

# DynamoDB Alarms
resource "aws_cloudwatch_metric_alarm" "dynamodb_throttles" {
  alarm_name          = "${var.prefix}-dynamodb-throttles"
  alarm_description   = "DynamoDB is being throttled - check capacity"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "ThrottledRequests"
  namespace           = "AWS/DynamoDB"
  period              = 60
  statistic           = "Sum"
  threshold           = 5
  alarm_actions       = var.critical_alarm_actions
  
  dimensions = {
    TableName = aws_dynamodb_table.voices.name
  }

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "stories_table_throttles" {
  alarm_name          = "${var.prefix}-dynamodb-stories-throttles"
  alarm_description   = "Stories table is being throttled"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "ThrottledRequests"
  namespace           = "AWS/DynamoDB"
  period              = 60
  statistic           = "Sum"
  threshold           = 5
  alarm_actions       = var.critical_alarm_actions
  
  dimensions = {
    TableName = aws_dynamodb_table.stories.name
  }

  tags = var.tags
}

# DynamoDB Metrics Dashboard
resource "aws_cloudwatch_dashboard" "dynamodb_metrics" {
  dashboard_name = "${var.prefix}-dynamodb-dashboard"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/DynamoDB", "ThrottledRequests", "TableName", aws_dynamodb_table.voices.name, { "label": "Voices Table Throttles" }],
            [".", ".", ".", aws_dynamodb_table.stories.name, { "label": "Stories Table Throttles" }]
          ]
          view    = "timeSeries"
          region  = var.region
          title   = "DynamoDB Throttled Requests"
          period  = 60
          stat    = "Sum"
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/DynamoDB", "ConsumedReadCapacityUnits", "TableName", aws_dynamodb_table.voices.name, { "label": "Voices Table Reads" }],
            [".", "ConsumedWriteCapacityUnits", ".", ".", { "label": "Voices Table Writes" }],
            [".", "ConsumedReadCapacityUnits", ".", aws_dynamodb_table.stories.name, { "label": "Stories Table Reads" }],
            [".", "ConsumedWriteCapacityUnits", ".", ".", { "label": "Stories Table Writes" }]
          ]
          view    = "timeSeries"
          region  = var.region
          title   = "DynamoDB Capacity Consumption"
          period  = 60
          stat    = "Sum"
        }
      }
    ]
  })
}

# SSM Parameter for stories table name
resource "aws_ssm_parameter" "stories_table" {
  name  = "/${var.prefix}/stories_table"
  type  = "String"
  value = aws_dynamodb_table.stories.name
  
  tags = var.tags
}

# SSM Parameter for voices table name
resource "aws_ssm_parameter" "voices_table" {
  name  = "/${var.prefix}/voices_table"
  type  = "String"
  value = aws_dynamodb_table.voices.name
  
  tags = var.tags
}

# SSM Parameter for KMS key ARN used for DynamoDB encryption
resource "aws_ssm_parameter" "dynamodb_kms_key_arn" {
  name  = "/${var.prefix}/dynamodb_kms_key_arn"
  type  = "String"
  value = local.kms_key_arn
  
  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "ssm_managed" {
  role       = aws_iam_role.gpu_worker.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# resource "aws_iam_role_policy_attachment" "s3_full" {
#   role       = aws_iam_role.gpu_worker.name
#   policy_arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
# }

resource "aws_iam_role_policy_attachment" "sqs_full" {
  role       = aws_iam_role.gpu_worker.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSQSFullAccess"
}

# resource "aws_iam_role_policy_attachment" "dynamodb_full" {
#   role       = aws_iam_role.gpu_worker.name
#   policy_arn = "arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess"
# }

# resource "aws_iam_role_policy_attachment" "cloudwatch_logs" {
#   role       = aws_iam_role.gpu_worker.name
#   policy_arn = "arn:aws:iam::aws:policy/CloudWatchLogsFullAccess"
# }