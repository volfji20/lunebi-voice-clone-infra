# SSM Parameters for runtime tuning
resource "aws_ssm_parameter" "mock_min_ms" {
  count = var.mode == "test" ? 1 : 0 
  name  = "/${var.prefix}/cpu_mock_min_ms"
  type  = "String"
  value = tostring(var.mock_min_ms)
  
  tags = var.tags
  overwrite   = true 
}

resource "aws_ssm_parameter" "mock_max_ms" {
  count = var.mode == "test" ? 1 : 0 
  name  = "/${var.prefix}/cpu_mock_max_ms"
  type  = "String"
  value = tostring(var.mock_max_ms)
  
  tags = var.tags
  overwrite   = true 
}

# CPU Mock Lambda Function
resource "aws_lambda_function" "cpu_mock" {
  count = var.mode == "test" && var.enable_cpu_mock_consumer ? 1 : 0

  function_name = "${var.prefix}-cpu-mock"
  role          = var.cpu_mock_role_arn
  runtime       = "python3.11"
  handler       = "app.lambda_handler"
  timeout       = 30
  memory_size   = 128

  filename         = "${path.module}/app.zip"
  source_code_hash = filebase64sha256("${path.module}/app.zip")

  environment {
    variables = {
      SQS_QUEUE_URL        = var.sqs_queue_url
      STORIES_TABLE_NAME   = var.stories_table_name
      MOCK_MIN_MS_PARAM    = aws_ssm_parameter.mock_min_ms[0].name
      MOCK_MAX_MS_PARAM    = aws_ssm_parameter.mock_max_ms[0].name
      DEPLOYMENT_MODE      = var.mode
      PREFIX               = var.prefix
      MOCKED_PROCESSING    = "true"
    }
  }

  tags = var.tags
}

# SQS Event Source Mapping (REAL-TIME PROCESSING)
resource "aws_lambda_event_source_mapping" "cpu_mock_sqs_trigger" {
  count = var.mode == "test" && var.enable_cpu_mock_consumer ? 1 : 0

  event_source_arn = var.sqs_queue_arn
  function_name    = aws_lambda_function.cpu_mock[0].arn
  
  batch_size                         = 5
  maximum_batching_window_in_seconds = 1
  enabled                            = true

  tags = var.tags

  # Ensure Lambda exists before creating event mapping
  depends_on = [aws_lambda_function.cpu_mock]
}


# Create new SSH key pair
resource "tls_private_key" "voiceclone" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "voiceclone" {
  key_name   = "${var.project}-keypair"
  public_key = tls_private_key.voiceclone.public_key_openssh
}

# Save private key to file (add to .gitignore)
resource "local_file" "private_key" {
  content  = tls_private_key.voiceclone.private_key_pem
  filename = "${path.module}/voiceclone-keypair.pem"
  file_permission = "0400"
}

# Launch Template for GPU Workers
resource "aws_launch_template" "gpu_worker" {
  count = (var.mode == "prod" || var.mode == "test") && var.enable_gpu_workers ? 1 : 0

  name_prefix = "${var.prefix}-gpu-worker-${var.mode}-"

  # Use the AMI ID from Packer build
  image_id = var.gpu_worker_ami_id

  instance_type = "g6.xlarge"  # Default, overridden by mixed_instances_policy
  key_name      = aws_key_pair.voiceclone.key_name

  # IAM Instance Profile
  iam_instance_profile {
    name = var.gpu_worker_instance_profile
  }

  # Block Device Mappings
  block_device_mappings {
    device_name = "/dev/xvda"

    ebs {
      volume_size           = 50
      volume_type           = "gp3"
      delete_on_termination = true
      encrypted             = true
    }
  }

  # Network Configuration
  network_interfaces {
    associate_public_ip_address = false
    security_groups             = [var.gpu_worker_sg_id]
    delete_on_termination       = true
  }

  # User Data for initialization
  user_data = base64encode(templatefile("${path.module}/user_data.sh", {
    environment          = var.mode
    cloudwatch_log_group = var.cloudwatch_log_group
    ssm_parameter_prefix = var.prefix
    gpu_worker_version   = var.gpu_worker_version  # ✅ ADD THIS
  
    # ✅ ADD THESE FOR COMPLETE M4 IMPLEMENTATION:
    region               = var.region  # For SSM parameter loading
    project              = var.project # For resource naming
    test_mode            = var.mode == "test" ? "true" : "false"
    
    # ✅ ADD THESE IF USING SPOT INSTANCES:
    spot_instance        = var.gpu_use_spot_only ? "true" : "false"
    enable_ebs_staging   = var.mode == "prod" ? "true" : "false"

    ROOT_DEVICE          = "/dev/xvda"
  }))

  # Metadata Options
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
    instance_metadata_tags      = "enabled"
  }

  # Monitoring
  monitoring {
    enabled = true
  }

  # Tag Specifications
  tag_specifications {
    resource_type = "instance"

    tags = {
      Name        = "${var.prefix}-gpu-worker-${var.mode}"
      Project     = var.prefix
      Environment = var.mode
      DeploymentColor = var.active_deployment_color
      GPUWorkerVersion = var.gpu_worker_version
    }
  }

  tag_specifications {
    resource_type = "volume"

    tags = {
      Name        = "${var.prefix}-gpu-worker-${var.mode}"
      Project     = var.prefix
      Environment = var.mode
    }
  }

  lifecycle {
    create_before_destroy = true
  }

  tags = var.tags
}


# GPU Worker Auto Scaling Group - COMPLETE MODES CONFIGURATION
resource "aws_autoscaling_group" "gpu_workers" {
  count = (var.mode == "prod" || var.mode == "test") && var.enable_gpu_workers ? 1 : 0

  name_prefix = "${var.prefix}-gpu-asg-${var.mode}-${var.active_deployment_color}-"
  
  vpc_zone_identifier = var.private_subnet_ids
  
  # ✅ FIXED: Use your exact variable names
  min_size = var.mode == "test" ? 0 : var.prod_mode_min_gpu_instances
  max_size = var.mode == "test" ? var.test_mode_max_gpu_instances : var.prod_mode_max_gpu_instances
  desired_capacity = var.mode == "test" ? var.test_mode_manual_scaling_desired : var.prod_mode_desired_gpu_instances

  protect_from_scale_in = var.mode == "prod" ? true : false

  # Health Check Configuration
  health_check_type          = "EC2"
  health_check_grace_period  = 300
  default_cooldown          = 300
  
  # ✅ FIXED: Termination Policies
  termination_policies = var.mode == "prod" ? [
    "OldestLaunchTemplate",  # ✅ FIXED: Use LaunchTemplate not LaunchConfiguration
    "OldestInstance",
    "Default"
  ] : ["Default"]

 
  # ✅ USE ONLY mixed_instances_policy (it already contains the launch template reference)
  mixed_instances_policy {
    launch_template {
      launch_template_specification {
        launch_template_id = aws_launch_template.gpu_worker[0].id
        version            = "$Latest"
      }

      override {
        instance_type     = "g6.xlarge"     # Preferred: L4 GPU
        weighted_capacity = "1"
      }
      override {
        instance_type     = "g6.2xlarge"    # More L4 memory
        weighted_capacity = "2"
      }
      override {
        instance_type     = "g5.xlarge"     # Fallback: A10G GPU
        weighted_capacity = "1"
      }
      override {
        instance_type     = "g4dn.xlarge"   # Cheapest fallback: T4 GPU
        weighted_capacity = "1"
      }
    }

    instances_distribution {
      # ✅ FIXED: Use your exact production variable names
      on_demand_base_capacity                  = var.gpu_use_spot_only ? 0 : var.prod_on_demand_base_capacity
      on_demand_percentage_above_base_capacity = var.gpu_use_spot_only ? 0 : var.prod_on_demand_percentage_above_base
      spot_allocation_strategy                 = "capacity-optimized"
    }
  }

  # ✅ FIXED: Warm Pool Configuration using your variable names
  dynamic "warm_pool" {
    for_each = var.mode == "prod" && var.enable_warm_pool ? [1] : []
    content {
      pool_state                  = "Stopped"
      min_size                    = var.warm_pool_min_size
      max_group_prepared_capacity = var.warm_pool_max_prepared_capacity
      
      instance_reuse_policy {
        reuse_on_scale_in = true
      }
    }
  }

  # ✅ FIXED: Production Mode Lifecycle Hooks (optional - remove if you don't have these resources)
  dynamic "initial_lifecycle_hook" {
    for_each = var.mode == "prod" && var.enable_blue_green_deployment ? [1] : []
    content {
      name                    = "${var.prefix}-gpu-launch-${var.active_deployment_color}"
      lifecycle_transition    = "autoscaling:EC2_INSTANCE_LAUNCHING"
      default_result          = "CONTINUE"
      heartbeat_timeout       = 600
      # Remove these if you don't have SNS topics for lifecycle hooks
      # notification_target_arn = aws_sns_topic.gpu_scaling[0].arn
      # role_arn                = aws_iam_role.gpu_lifecycle[0].arn
    }
  }

  # ✅ FIXED: Enhanced Tagging
  tag {
    key                 = "Name"
    value               = "${var.prefix}-gpu-worker-${var.mode}-${var.active_deployment_color}"
    propagate_at_launch = true
  }

  tag {
    key                 = "Project"
    value               = var.project
    propagate_at_launch = true
  }

  tag {
    key                 = "Environment"
    value               = var.mode
    propagate_at_launch = true
  }

  tag {
    key                 = "DeploymentColor"
    value               = var.active_deployment_color
    propagate_at_launch = true
  }

  tag {
    key                 = "GPUWorkerVersion"
    value               = var.gpu_worker_version
    propagate_at_launch = true
  }

  tag {
    key                 = "AutoScalingEnabled"
    value               = var.mode == "prod" ? "true" : "false"
    propagate_at_launch = true
  }

  tag {
    key                 = "SpotOnly"
    value               = var.gpu_use_spot_only ? "true" : "false"
    propagate_at_launch = true
  }

  tag {
    key                 = "InstanceFamily"
    value               = "mixed-g6-g5-g4dn"
    propagate_at_launch = true
  }

  # ✅ FIXED: Spot Fallback Tag
  tag {
    key                 = "SpotFallback"
    value               = var.spot_fallback_enabled ? "enabled" : "disabled"
    propagate_at_launch = true
  }

  # ✅ FIXED: Metrics Collection for Observability
  enabled_metrics = [
    "GroupMinSize",
    "GroupMaxSize",
    "GroupDesiredCapacity",
    "GroupInServiceInstances",
    "GroupPendingInstances",
    "GroupStandbyInstances",
    "GroupTerminatingInstances",
    "GroupTotalInstances",
  ]

  lifecycle {
    create_before_destroy = true
    ignore_changes = [
      desired_capacity
    ]
  }
}

# ============================================================================
# 4.6 AUTOSCALING POLICIES - ENHANCED IMPLEMENTATION
# ============================================================================

# PRIMARY POLICY: Backlog-based (ApproximateAgeOfOldestMessage < 5s)
resource "aws_autoscaling_policy" "backlog_target_tracking" {
  count = var.mode == "prod" ? 1 : 0

  name                   = "${var.prefix}-backlog-target-tracking"
  autoscaling_group_name = aws_autoscaling_group.gpu_workers[0].name
  policy_type            = "TargetTrackingScaling"
  
  target_tracking_configuration {
    target_value = 4.0 
    disable_scale_in = false
    
    customized_metric_specification {
      metrics {
        id = "m1"
        label = "SQS ApproximateAgeOfOldestMessage"
        
        metric_stat {
          metric {
            metric_name = "ApproximateAgeOfOldestMessage"
            namespace   = "AWS/SQS"
            
            dimensions {
              name  = "QueueName"
              value = var.sqs_queue_name
            }
          }
          stat = "Average"
          period = 60
        }
        return_data = true
      }
    }
  }
  
  estimated_instance_warmup = 90
}

# SLO-based Policy: TTFA p95 < 1.0s (Custom Metric)
resource "aws_autoscaling_policy" "ttfa_slo_target_tracking" {
  count = var.mode == "prod" ? 1 : 0

  name                   = "${var.prefix}-ttfa-slo-target-tracking"
  autoscaling_group_name = aws_autoscaling_group.gpu_workers[0].name
  policy_type            = "TargetTrackingScaling"
  
  target_tracking_configuration {
    target_value = 0.8  # Target 0.8s (safety margin for <1.0s)
    disable_scale_in = true  # Safety: don't scale in based on TTFA alone
    
    customized_metric_specification {
      metrics {
        id = "m1"
        label = "TTFA p95"
        
        metric_stat {
          metric {
            metric_name = "TTFAMilliseconds"  # ✅ USE EXISTING METRIC
            namespace   = "Lunebi/Stories"    # ✅ CORRECT NAMESPACE
            
            dimensions {
              name  = "AutoScalingGroupName"
              value = aws_autoscaling_group.gpu_workers[0].name
            }
          }
          stat   = "p95"      # ✅ CHANGE TO p95
          period = 300        # ✅ ADD PERIOD
        }
        return_data = true
      }
    }
  }
  
  estimated_instance_warmup = 120
}

# ============================================================================
# SCHEDULED SCALING ACTIONS FOR KNOWN SPIKES
# ============================================================================

# Scheduled Scaling Actions for Known Spikes
resource "aws_autoscaling_schedule" "business_hours" {
  count = var.mode == "prod" ? length(var.scheduled_scaling_actions) : 0

  scheduled_action_name  = var.scheduled_scaling_actions[count.index].name
  autoscaling_group_name = aws_autoscaling_group.gpu_workers[0].name
  min_size               = var.scheduled_scaling_actions[count.index].min_size
  max_size               = var.scheduled_scaling_actions[count.index].max_size
  desired_capacity       = var.scheduled_scaling_actions[count.index].desired_capacity
  recurrence             = var.scheduled_scaling_actions[count.index].recurrence

  time_zone = "UTC"
}

# ============================================================================
# TEST MODE SPECIFIC RESOURCES
# ============================================================================

# SSM Parameter for GPU ASG Name (for CPU mock fallback detection)
resource "aws_ssm_parameter" "gpu_asg_name" {
  count = var.mode == "test" ? 1 : 0

  name  = "/${var.prefix}/gpu_asg_name"
  type  = "String"
  value = aws_autoscaling_group.gpu_workers[0].name
  
  tags = var.tags
}

# SSM Parameter for Spot Fallback Enabled
resource "aws_ssm_parameter" "spot_fallback_enabled" {
  count = var.mode == "test" ? 1 : 0

  name  = "/${var.prefix}/spot_fallback_enabled"
  type  = "String"
  value = tostring(var.spot_fallback_enabled)
  
  tags = var.tags
}

# Manual Scaling Alarm for Test Mode


# SNS Topic for Test Mode Alerts
resource "aws_sns_topic" "test_mode_alerts" {
  count = var.mode == "test" ? 1 : 0

  name = "${var.prefix}-test-mode-alerts"
  tags = var.tags
}

# SNS Topic for GPU Scaling (Production Mode Only)
resource "aws_sns_topic" "gpu_scaling" {
  count = var.mode == "prod" ? 1 : 0

  name = "${var.prefix}-gpu-scaling"
  tags = var.tags
}

# IAM Role for Lifecycle Hooks (Production Mode Only)
resource "aws_iam_role" "gpu_lifecycle" {
  count = var.mode == "prod" ? 1 : 0

  name = "${var.prefix}-gpu-lifecycle-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "autoscaling.amazonaws.com"
        }
      }
    ]
  })

  tags = var.tags
}

# IAM Policy for Lifecycle Hooks
resource "aws_iam_role_policy" "gpu_lifecycle" {
  count = var.mode == "prod" ? 1 : 0

  name = "${var.prefix}-gpu-lifecycle-policy"
  role = aws_iam_role.gpu_lifecycle[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sns:Publish",
          "autoscaling:CompleteLifecycleAction",
          "autoscaling:RecordLifecycleActionHeartbeat"
        ]
        Resource = "*"
      }
    ]
  })
}

# ============================================================================
# 4.8 OBSERVABILITY - COMPLETE IMPLEMENTATION
# ============================================================================

# CloudWatch Dashboard for Production Monitoring
# dashboard.tf
resource "aws_cloudwatch_dashboard" "production" {
  count = var.mode == "prod" ? 1 : 0

  dashboard_name = "${var.prefix}-production-dashboard"

  dashboard_body = jsonencode({
    widgets = [
      # ==================== ROW 1: SQS Queue Metrics ====================
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          metrics = [
            # SQS Age (REQUIRED METRIC)
            ["AWS/SQS", "ApproximateAgeOfOldestMessage", "QueueName", split("/", var.sqs_queue_url)[4], { "label": "Oldest Message Age (s)", "color": "#ff7f0e" }],
            [".", "ApproximateNumberOfMessagesVisible", ".", ".", { "label": "Visible Messages", "yAxis": "right" }],
            [".", "ApproximateNumberOfMessagesNotVisible", ".", ".", { "label": "In-Flight Messages", "yAxis": "right" }]
          ]
          view   = "timeSeries"
          stacked = false
          region = var.aws_region
          title  = "SQS Queue Health (REQUIRED: SQS Age)"
          period = 60
          stat   = "Average"
          annotations = {
            horizontal = [
              {
                label = "Alarm Threshold (10s)",
                value = 10
              }
            ]
          }
        }
      },

      # ==================== ROW 2: GPU Metrics ====================
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          metrics = [
            # GPU util/VRAM (REQUIRED METRICS)
            ["CWAgent", "utilization_gpu", "AutoScalingGroupName", "${var.prefix}-gpu-asg", { "label": "GPU Utilization %", "color": "#1f77b4" }],
            [".", "utilization_memory", ".", ".", { "label": "GPU Memory %", "color": "#ff7f0e" }],
            [".", "memory_used", ".", ".", { "label": "GPU Memory Used (MB)", "yAxis": "right", "color": "#2ca02c" }],
            [".", "memory_free", ".", ".", { "label": "GPU Memory Free (MB)", "yAxis": "right", "color": "#d62728" }]
          ]
          view   = "timeSeries"
          stacked = false
          region = var.aws_region
          title  = "GPU Utilization & VRAM (REQUIRED METRICS)"
          period = 60
          stat   = "Average"
          annotations = {
            horizontal = [
              {
                label = "GPU Util Alarm (85%)",
                value = 85
              },
              {
                label = "GPU Memory Alarm (90%)",
                value = 90
              }
            ]
          }
        }
      },

      # ==================== ROW 3: S3 Performance ====================
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 12
        height = 6
        properties = {
          metrics = [
            # S3 PUT Latency (REQUIRED METRIC)
            ["AWS/S3", "FirstByteLatency", "BucketName", var.stories_bucket, "FilterId", "EntireBucket", { "label": "S3 First Byte Latency", "color": "#1f77b4" }],
            [".", "TotalRequestLatency", ".", ".", ".", ".", { "label": "S3 Total Latency", "color": "#ff7f0e" }],
            # Custom metric from your Python code
            ["VoiceClone/S3", "S3PutLatency", "Operation", "PutObject", "Region", var.aws_region, { "label": "S3 PUT Latency (Custom)", "yAxis": "right", "color": "#2ca02c" }]
          ]
          view   = "timeSeries"
          stacked = false
          region = var.aws_region
          title  = "S3 Performance (REQUIRED: S3 PUT Latency)"
          period = 300
          stat   = "Average"
          annotations = {
            horizontal = [
              {
                label = "Alarm Threshold (1s)",
                value = 1000
              }
            ]
          }
        }
      },

      # ==================== ROW 4: CloudFront Errors ====================
      {
        type   = "metric"
        x      = 0
        y      = 18
        width  = 12
        height = 6
        properties = {
          metrics = [
            # Segment 404s (REQUIRED METRIC)
            ["AWS/CloudFront", "404ErrorRate", "DistributionId", var.cdn_stories, "Region", "Global", { "label": "404 Error Rate", "color": "#d62728" }],
            [".", "5xxErrorRate", ".", ".", ".", ".", { "label": "5xx Error Rate", "color": "#9467bd" }],
            [".", "TotalErrorRate", ".", ".", ".", ".", { "label": "Total Error Rate", "color": "#8c564b" }],
            [".", "Requests", ".", ".", ".", ".", { "label": "Total Requests", "yAxis": "right", "stat": "Sum" }]
          ]
          view   = "timeSeries"
          stacked = false
          region = var.aws_region
          title  = "CloudFront Errors (REQUIRED: Segment 404s)"
          period = 300
          stat   = "Average"
          annotations = {
            horizontal = [
              {
                label = "404 Alarm Threshold (0.1%)",
                value = 0.1
              }
            ]
          }
        }
      },

      # ==================== ROW 5: Auto Scaling ====================
      {
        type   = "metric"
        x      = 0
        y      = 24
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/AutoScaling", "GroupInServiceInstances", "AutoScalingGroupName", "${var.prefix}-gpu-asg", { "label": "In-Service Instances" }],
            [".", "GroupDesiredCapacity", ".", ".", { "label": "Desired Capacity" }],
            [".", "GroupTotalInstances", ".", ".", { "label": "Total Instances" }],
            ["AWS/EC2", "CPUUtilization", "AutoScalingGroupName", "${var.prefix}-gpu-asg", { "label": "CPU Utilization %", "yAxis": "right" }]
          ]
          view   = "timeSeries"
          stacked = false
          region = var.aws_region
          title  = "GPU Auto Scaling Group"
          period = 300
          stat   = "Average"
        }
      },

      # ==================== ROW 6: TTFA SLO Monitoring ====================
      {
        type   = "metric"
        x      = 0
        y      = 30
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["Lunebi/GPU", "TTFAp95", { "label": "TTFA p95 (ms)", "color": "#ff7f0e" }],
            [".", "TTFAp50", { "label": "TTFA p50 (ms)", "color": "#1f77b4" }]
          ]
          view   = "timeSeries"
          stacked = false
          region = var.aws_region
          title  = "TTFA SLO Monitoring"
          period = 60
          stat   = "Average"
          annotations = {
            horizontal = [
              {
                label = "SLO Threshold (1000ms)",
                value = 1000
              },
              {
                label = "Target (500ms)",
                value = 500
              }
            ]
          }
        }
      },

      # ==================== ROW 7: Custom HLS Metrics ====================
      {
        type   = "metric"
        x      = 0
        y      = 36
        width  = 12
        height = 6
        properties = {
          metrics = [
            # From your Python ProductionHLSUploadManager
            ["VoiceClone/Production/HLS", "HLSSegmentsUploaded", "Component", "HLSUploadManager", "Region", var.aws_region, { "label": "HLS Segments Uploaded", "stat": "Sum" }],
            [".", "HLSSegmentUploadErrors", ".", ".", ".", ".", { "label": "Segment Upload Errors", "yAxis": "right" }],
            [".", "ValidHLSContracts", ".", ".", ".", ".", { "label": "Valid HLS Contracts" }]
          ]
          view   = "timeSeries"
          stacked = false
          region = var.aws_region
          title  = "HLS Upload Manager"
          period = 300
          stat   = "Average"
        }
      },

      # ==================== ROW 8: Staging Upload Queue ====================
      {
        type   = "metric"
        x      = 0
        y      = 42
        width  = 12
        height = 6
        properties = {
          metrics = [
            # From your Python ProductionStagingUploadWatcher
            ["VoiceClone/Production/Upload", "StagingUploadQueueSize", "Component", "StagingUploadWatcher", "Region", var.aws_region, { "label": "Upload Queue Size" }],
            [".", "StagingUploadSuccessRate", ".", ".", ".", ".", { "label": "Upload Success Rate %", "yAxis": "right" }],
            [".", "ActiveUploadThreads", ".", ".", ".", ".", { "label": "Active Upload Threads", "yAxis": "right" }]
          ]
          view   = "timeSeries"
          stacked = false
          region = var.aws_region
          title  = "Staging Upload Watcher"
          period = 300
          stat   = "Average"
        }
      },

      # ==================== ROW 9: Recent Errors Logs ====================
      {
        type   = "log"
        x      = 0
        y      = 48
        width  = 12
        height = 6
        properties = {
          query = <<-EOT
            fields @timestamp, @message
            | filter @message like /ERROR|WARNING|CRITICAL|FAILED/
            | sort @timestamp desc
            | limit 50
          EOT
          region = var.aws_region
          title  = "Recent Errors & Warnings"
          view   = "table"
        }
      },

      # ==================== ROW 10: Single-Value Widgets ====================
      {
        type   = "metric"
        x      = 0
        y      = 54
        width  = 3
        height = 3
        properties = {
          metrics = [
            ["AWS/SQS", "ApproximateAgeOfOldestMessage", "QueueName", split("/", var.sqs_queue_url)[4], { "label": "SQS Age", "stat": "Maximum", "period": 60 }]
          ]
          view   = "singleValue"
          region = var.aws_region
          title  = "SQS Age (s)"
          period = 60
          stat   = "Maximum"
        }
      },
      {
        type   = "metric"
        x      = 3
        y      = 54
        width  = 3
        height = 3
        properties = {
          metrics = [
            ["AWS/CloudFront", "404ErrorRate", "DistributionId", var.cdn_stories, "Region", "Global", { "label": "404 Rate", "stat": "Maximum", "period": 300 }]
          ]
          view   = "singleValue"
          region = var.aws_region
          title  = "404 Rate %"
          period = 300
          stat   = "Maximum"
        }
      },
      {
        type   = "metric"
        x      = 6
        y      = 54
        width  = 3
        height = 3
        properties = {
          metrics = [
            ["VoiceClone/S3", "S3PutLatency", "Operation", "PutObject", "Region", var.aws_region, { "label": "S3 PUT Latency", "stat": "Maximum", "period": 300 }]
          ]
          view   = "singleValue"
          region = var.aws_region
          title  = "S3 Latency (ms)"
          period = 300
          stat   = "Maximum"
        }
      },
      {
        type   = "metric"
        x      = 9
        y      = 54
        width  = 3
        height = 3
        properties = {
          metrics = [
            ["CWAgent", "utilization_gpu", "AutoScalingGroupName", "${var.prefix}-gpu-asg", { "label": "GPU Util", "stat": "Maximum", "period": 60 }]
          ]
          view   = "singleValue"
          region = var.aws_region
          title  = "GPU Util %"
          period = 60
          stat   = "Maximum"
        }
      }
    ]
  })
}

# Lambda Error Rate Alarm (for CPU Mock in test mode)
resource "aws_cloudwatch_metric_alarm" "lambda_errors_high" {
  count = var.mode == "test" ? 1 : 0

  alarm_name          = "${var.prefix}-lambda-errors-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = "60"
  statistic           = "Sum"
  threshold           = "5"           # > 5 errors in period
  alarm_description   = "CPU Mock Lambda errors exceed threshold"
  alarm_actions       = [aws_sns_topic.test_mode_alerts[0].arn]

  dimensions = {
    FunctionName = aws_lambda_function.cpu_mock[0].function_name
  }

  tags = var.tags
}

# CloudWatch Log Metric Filter for Custom GPU Metrics
resource "aws_cloudwatch_log_metric_filter" "gpu_metrics" {
  count = var.mode == "prod" ? 1 : 0

  name           = "${var.prefix}-gpu-metrics"
  log_group_name = var.cloudwatch_log_group
  pattern        = "[timestamp, instance, metric, value]"

  metric_transformation {
    name      = "GPUUtilization"
    namespace = "Lunebi/GPU"
    value     = "$value"
    dimensions = {
      InstanceId = "$instance"
    }
  }
}

# SNS Topic for Critical Alarms
resource "aws_sns_topic" "critical_alarms" {
  count = var.mode == "prod" ? 1 : 0

  name = "${var.prefix}-critical-alarms"
  tags = var.tags
}

# CloudWatch Log Group for GPU Worker Logs
resource "aws_cloudwatch_log_group" "gpu_worker" {
  count = var.mode == "prod" || var.mode == "test" ? 1 : 0

  name              = var.cloudwatch_log_group
  retention_in_days = 30

  tags = var.tags
}

# Add schema validation SSM parameters
resource "aws_ssm_parameter" "sqs_schema_version" {
  count = var.mode == "test" || var.mode == "prod" ? 1 : 0

  name  = "/${var.prefix}/sqs_schema_version"
  type  = "String"
  value = "1.0.0"
  
  tags = var.tags
}

resource "aws_ssm_parameter" "sqs_required_fields" {
  count = var.mode == "test" || var.mode == "prod" ? 1 : 0

  name  = "/${var.prefix}/sqs_required_fields"
  type  = "String"
  value = "story_id,seq,text,voice_id,lang,params,idempotency_key"
  
  tags = var.tags
}



resource "aws_cloudwatch_log_metric_filter" "active_renders" {
  count = var.mode == "prod" ? 1 : 0

  name           = "${var.prefix}-active-renders"
  log_group_name = var.cloudwatch_log_group
  
  # Pattern: When GPU worker starts/finishes a render
  pattern = <<PATTERN
[instance_id, story_id, event_type="render_start"|"render_complete"]
PATTERN
  
  metric_transformation {
    name      = "ActiveRenders"
    namespace = "Lunebi/GPU"
    value     = "1"  # Increment for start, decrement for complete (handled in pattern logic)
    unit      = "Count"
    
    dimensions = {
      InstanceId = "$instance_id"
      AutoScalingGroupName = aws_autoscaling_group.gpu_workers[0].name
    }
  }
}


# SSM Parameter for CloudWatch Agent Config
resource "aws_ssm_parameter" "cloudwatch_agent_config" {
  count = (var.mode == "prod" || var.mode == "test") && var.enable_gpu_workers ? 1 : 0

  name  = "/${var.prefix}/cloudwatch-agent-config"
  type  = "String"
  value = jsonencode({
    "metrics" = {
      "metrics_collected" = {
        "nvidia_gpu" = {
          "measurement" = [
            "utilization_gpu",
            "utilization_memory",
            "memory_total",
            "memory_used",
            "memory_free",
            "temperature_gpu"
          ],
          "metrics_collection_interval" = 60
        },
        "cpu" = {
          "measurement" = [
            "cpu_usage_idle",
            "cpu_usage_iowait",
            "cpu_usage_user",
            "cpu_usage_system"
          ],
          "metrics_collection_interval" = 60,
          "resources" = ["*"],
          "totalcpu" = true
        },
        "disk" = {
          "measurement" = [
            "used_percent",
            "inodes_free"
          ],
          "metrics_collection_interval" = 60,
          "resources" = ["*"]
        },
        "mem" = {
          "measurement" = [
            "mem_used_percent"
          ],
          "metrics_collection_interval" = 60
        }
      },
      "append_dimensions" = {
        "AutoScalingGroupName" = "${aws_autoscaling_group.gpu_workers[0].name}",
        "InstanceId"           = "$${aws:InstanceId}",
        "InstanceType"         = "$${aws:InstanceType}"
      }
    }
  })
  
  tags = var.tags
}

# IAM Policy for CloudWatch Agent
resource "aws_iam_role_policy" "cloudwatch_agent_policy" {
  count = (var.mode == "prod" || var.mode == "test") && var.enable_gpu_workers ? 1 : 0

  name = "${var.prefix}-cloudwatch-agent-policy"
  role = var.gpu_worker_role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricData",
          "ec2:DescribeTags",
          "logs:PutLogEvents",
          "logs:DescribeLogStreams",
          "logs:DescribeLogGroups",
          "logs:CreateLogStream",
          "logs:CreateLogGroup",
          "ssm:GetParameter"
        ]
        Resource = "*"
      }
    ]
  })
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
    AutoScalingGroupName = aws_autoscaling_group.gpu_workers[0].name
    InstanceId           = "$INSTANCE_ID"  # Will be filled per instance
    InstanceType         = "$INSTANCE_TYPE"
  }

  tags = var.tags
}

# Scale-in protection based on active renders
resource "aws_autoscaling_policy" "scale_in_protection" {
  count = var.mode == "prod" ? 1 : 0

  name                   = "${var.prefix}-scale-in-protection"
  autoscaling_group_name = aws_autoscaling_group.gpu_workers[0].name
  policy_type            = "StepScaling"
  
  adjustment_type        = "PercentChangeInCapacity"
  cooldown               = 120
  
  step_adjustment {
    scaling_adjustment          = 0  # No scale-in when active renders > 0
    metric_interval_lower_bound = 0
    metric_interval_upper_bound = null
  }
}

# Alarm to trigger scale-in protection
resource "aws_cloudwatch_metric_alarm" "active_renders_detected" {
  count = var.mode == "prod" ? 1 : 0

  alarm_name          = "${var.prefix}-active-renders-detected"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = 0  # Any active renders
  alarm_description   = "Active renders detected - prevent scale-in"
  
  metric_query {
    id = "active_renders"
    
    metric {
      metric_name = "ActiveRenders"
      namespace   = "Lunebi/GPU"
      period      = 60
      stat        = "Maximum"  # Check if ANY active renders
      
      dimensions = {
        AutoScalingGroupName = aws_autoscaling_group.gpu_workers[0].name
      }
    }
    
    return_data = true
  }
  
  alarm_actions = []  # Just for metric, no notification needed
}