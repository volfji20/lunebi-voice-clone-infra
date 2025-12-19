# SSM Parameter for p95 sentence synthesis time (runtime tunable)
resource "aws_ssm_parameter" "p95_sentence_synth" {
  name  = "/${var.prefix}/p95_sentence_synth_ms"
  type  = "String"
  value = "500"  # Default 500ms, will be tuned based on real metrics
  
  tags = var.tags
}

# Calculate visibility timeout using the formula: max(30s, 2 × p95_sentence_synth)
data "aws_ssm_parameter" "p95_sentence_synth" {
  name = aws_ssm_parameter.p95_sentence_synth.name
}

locals {
  p95_sentence_synth_seconds = tonumber(data.aws_ssm_parameter.p95_sentence_synth.value) / 1000
  visibility_timeout_seconds = max(30, ceil(2 * local.p95_sentence_synth_seconds)) + 5
}

resource "aws_ssm_parameter" "queue_url" {
  name  = "/${var.prefix}/queue_url"
  type  = "String"
  value = aws_sqs_queue.story_tasks.url
  
  tags = var.tags
}

# Dead Letter Queue
resource "aws_sqs_queue" "story_tasks_dlq" {
  name                      = "${var.prefix}-story-tasks-dlq"
  delay_seconds             = 0
  max_message_size          = 262144  # 256KB
  message_retention_seconds = var.dlq_retention_days * 24 * 3600  # Convert to seconds
  
  tags = merge(var.tags, {
    Purpose = "VoiceClone-StoryTasks-DLQ"
  })
}

# Main Queue with DLQ redrive
resource "aws_sqs_queue" "story_tasks" {
  name                      = "${var.prefix}-story-tasks"
  delay_seconds             = 0
  max_message_size          = 262144  # 256KB
  message_retention_seconds = var.message_retention_days * 24 * 3600  # 4 days in seconds
  receive_wait_time_seconds = var.long_poll_seconds  # Long polling 20s
  visibility_timeout_seconds = local.visibility_timeout_seconds  # Formula-based timeout
  
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.story_tasks_dlq.arn
    maxReceiveCount     = var.max_receive_count  # 5 attempts
  })

  tags = merge(var.tags, {
    Purpose = "VoiceClone-StoryTasks"
  })
}



# ========================
# OBSERVABILITY 
# ========================

# CloudWatch Alarms for SQS Observability
resource "aws_cloudwatch_metric_alarm" "old_message_age_warning" {
  alarm_name          = "${var.prefix}-sqs-old-message-age-warning"
  alarm_description   = "Messages are aging in queue - may need scaling"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "ApproximateAgeOfOldestMessage"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Maximum"
  threshold           = 10  # 10 seconds for warning
  # Remove external dependency - use empty list for now
  alarm_actions       = []
  
  dimensions = {
    QueueName = aws_sqs_queue.story_tasks.name
  }

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "old_message_age_critical" {
  count = var.mode == "prod" ? 1 : 0  # Only in production mode
  
  alarm_name          = "${var.prefix}-sqs-old-message-age-critical"
  alarm_description   = "CRITICAL: Messages are stuck in queue for too long"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "ApproximateAgeOfOldestMessage"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Maximum"
  threshold           = 60  # 60 seconds for critical (prod only)
  # Remove external dependency - use empty list for now
  alarm_actions       = []
  
  dimensions = {
    QueueName = aws_sqs_queue.story_tasks.name
  }

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "dlq_messages" {
  alarm_name          = "${var.prefix}-sqs-dlq-messages"
  alarm_description   = "CRITICAL: Messages are being sent to DLQ - check for processing failures"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300  # 5 minutes to avoid false positives
  statistic           = "Maximum"
  threshold           = 0
  # Remove external dependency - use empty list for now
  alarm_actions       = []
  
  dimensions = {
    QueueName = aws_sqs_queue.story_tasks_dlq.name
  }

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "queue_depth" {
  alarm_name          = "${var.prefix}-sqs-queue-depth"
  alarm_description   = "Queue depth is growing - may need to scale workers"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Maximum"
  threshold           = var.mode == "prod" ? 100 : 20  # Higher threshold in prod
  # Remove external dependency - use empty list for now
  alarm_actions       = []
  
  dimensions = {
    QueueName = aws_sqs_queue.story_tasks.name
  }

  tags = var.tags
}

# SQS Metrics Dashboard
resource "aws_cloudwatch_dashboard" "sqs_metrics" {
  dashboard_name = "${var.prefix}-sqs-dashboard"

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
            ["AWS/SQS", "ApproximateAgeOfOldestMessage", "QueueName", aws_sqs_queue.story_tasks.name],
            [".", "ApproximateNumberOfMessagesVisible", ".", "."],
            [".", "ApproximateNumberOfMessagesNotVisible", ".", "."]
          ]
          view    = "timeSeries"
          region  = var.region
          title   = "SQS Main Queue Metrics"
          period  = 60
          stat    = "Average"
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
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.story_tasks_dlq.name, { "label": "DLQ Messages" }]
          ]
          view    = "timeSeries"
          region  = var.region
          title   = "Dead Letter Queue"
          period  = 300
          stat    = "Maximum"
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/SQS", "NumberOfMessagesSent", "QueueName", aws_sqs_queue.story_tasks.name, { "label": "Messages Sent" }],
            [".", "NumberOfMessagesReceived", ".", ".", { "label": "Messages Received" }],
            [".", "NumberOfMessagesDeleted", ".", ".", { "label": "Messages Deleted" }]
          ]
          view    = "timeSeries"
          region  = var.region
          title   = "SQS Message Flow"
          period  = 60
          stat    = "Sum"
        }
      }
    ]
  })
}

# ADD THIS: SQS Queue Policy for IAM roles
resource "aws_sqs_queue_policy" "story_tasks" {
  queue_url = aws_sqs_queue.story_tasks.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowAllInAccount"
        Effect = "Allow"
        Principal = {
          AWS = "*"
        }
        Action = [
          "sqs:SendMessage",
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:ChangeMessageVisibility"
        ]
        Resource = aws_sqs_queue.story_tasks.arn
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }
        }
      }
    ]
  })
}

data "aws_caller_identity" "current" {}



# Enhanced CloudWatch Alarms for Production
resource "aws_cloudwatch_metric_alarm" "ttfa_p95_high" {
  count = var.mode == "prod" ? 1 : 0

  alarm_name          = "${var.prefix}-ttfa-p95-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 5     
  threshold           = 1500 
  
  metric_query {
    id = "m1"
    metric {
      metric_name = "TTFAMilliseconds" 
      namespace   = "Lunebi/Stories"    
      period      = 60
      stat        = "p95"
      dimensions = {
        AutoScalingGroupName = var.gpu_asg_name
      }
    }
    return_data = true
  }
  
  alarm_description = "TTFA p95 exceeds 1.5s over 5 minutes"
  alarm_actions     = var.critical_alarm_actions
  
  tags = var.tags
}


# OldestMessageAge > 10s Alarm (matches blueprint)
resource "aws_cloudwatch_metric_alarm" "sqs_oldest_message_age_high" {
  count = var.mode == "prod" ? 1 : 0

  alarm_name          = "${var.prefix}-sqs-oldest-message-age-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "ApproximateAgeOfOldestMessage"
  namespace           = "AWS/SQS"
  period              = "60"
  statistic           = "Average"
  threshold           = "10"          # > 10 seconds (matches blueprint)
  alarm_description   = "SQS oldest message age exceeds 10 seconds"
  alarm_actions       = var.critical_alarm_actions

  dimensions = {
    QueueName = split("/", aws_sqs_queue.story_tasks.url)[4]
  }

  tags = var.tags
}

# ----------------------------------------------------------------
# GPU Metric Alarms (Utilization & VRAM)
# ----------------------------------------------------------------

# GPU Utilization Alarm (> 90% for 2 minutes) - FIXED with correct metric name
resource "aws_cloudwatch_metric_alarm" "gpu_utilization_high" {
  count = var.mode == "prod" ? 1 : 0

  alarm_name          = "${var.prefix}-gpu-utilization-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2  # 2 minutes total (2 periods × 60s)
  metric_name         = "utilization_gpu"  # ✅ CORRECT: From NVIDIA agent
  namespace           = "CWAgent"          # ✅ CORRECT: CloudWatch Agent namespace
  period              = 60                 # 60-second periods
  statistic           = "Average"
  threshold           = 90                 # > 90% utilization
  alarm_description   = "GPU utilization exceeds 90% for 2 minutes"
  alarm_actions       = var.critical_alarm_actions

  dimensions = {
    AutoScalingGroupName = var.gpu_asg_name
  }

  tags = var.tags
}

# API 5xx Errors Alarm (placeholder - requires API Gateway)
resource "aws_cloudwatch_metric_alarm" "api_5xx_percentage_high" {
  count = var.mode == "prod" && var.api_gateway_id != null ? 1 : 0

  alarm_name          = "${var.prefix}-api-5xx-percentage-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  threshold           = "1"  # ✅ 1% threshold
  
  # Metric math to calculate percentage
  metric_query {
    id = "errors"
    metric {
      metric_name = "5XXError"  # Note: AWS uses 5XXError (uppercase XX)
      namespace   = "AWS/ApiGateway"
      period      = 300
      stat        = "Sum"
      dimensions  = {
        ApiName = var.api_gateway_id
      }
    }
  }
  
  metric_query {
    id = "requests"
    metric {
      metric_name = "Count"
      namespace   = "AWS/ApiGateway"
      period      = 300
      stat        = "Sum"
      dimensions  = {
        ApiName = var.api_gateway_id
      }
    }
  }
  
  metric_query {
    id          = "error_percentage"
    expression  = "(errors / requests) * 100"
    label       = "5xx Error Percentage"
    return_data = true
  }
  
  alarm_description = "API 5xx error rate exceeds 1%"
  alarm_actions     = var.critical_alarm_actions
  
  tags = var.tags
}