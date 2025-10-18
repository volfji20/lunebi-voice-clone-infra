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
      }
    ]
  })

  tags = var.tags
}

data "aws_caller_identity" "current" {}

locals {
  kms_key_arn = var.kms_key_arn != null ? var.kms_key_arn : aws_kms_key.dynamodb[0].arn
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
  name = "${var.prefix}-gpu-worker"

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
          "sqs:ChangeMessageVisibility"
        ]
        Resource = [var.sqs_queue_arn]
      },
      # DynamoDB: GetItem (voices), UpdateItem (stories)
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
      # S3: PutObject to stories/${story_id}/* only
      {
        Sid    = "S3StorySegmentsWrite"
        Effect = "Allow"
        Action = [
          "s3:PutObject"
        ]
        Resource = ["${var.stories_bucket_arn}/stories/*"]
      },
      # KMS: Encrypt/Decrypt for DynamoDB and S3
      {
        Sid    = "KMSAccess"
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey"
        ]
        Resource = [local.kms_key_arn]
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