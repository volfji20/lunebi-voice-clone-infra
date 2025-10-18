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
  p95_sentence_synth_seconds = 500 / 1000
  visibility_timeout_seconds = max(30, ceil(2 * local.p95_sentence_synth_seconds))
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
        Effect = "Allow"
        Principal = {
          AWS = compact([
            var.api_lambda_role_arn,    # For API Lambda to send messages
            var.gpu_worker_role_arn,    # For GPU workers to receive messages
            var.cpu_mock_role_arn       # For CPU mock to receive messages
          ])
        }
        Action = [
          "sqs:SendMessage",           # API Lambda needs this
          "sqs:ReceiveMessage",        # Workers need this  
          "sqs:DeleteMessage",         # Workers need this
          "sqs:GetQueueAttributes",    # Workers need this
          "sqs:ChangeMessageVisibility" # Workers need this
        ]
        Resource = aws_sqs_queue.story_tasks.arn
      }
    ]
  })
}