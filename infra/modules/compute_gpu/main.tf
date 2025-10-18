# SSM Parameters for runtime tuning
resource "aws_ssm_parameter" "mock_min_ms" {
  name  = "/${var.prefix}/cpu_mock_min_ms"
  type  = "String"
  value = tostring(var.mock_min_ms)
  
  tags = var.tags
}

resource "aws_ssm_parameter" "mock_max_ms" {
  name  = "/${var.prefix}/cpu_mock_max_ms"
  type  = "String"
  value = tostring(var.mock_max_ms)
  
  tags = var.tags
}

# CPU Mock Lambda Function
resource "aws_lambda_function" "cpu_mock" {
  function_name = "${var.prefix}-cpu-mock"
  role          = var.cpu_mock_role_arn
  runtime       = "python3.11"
  handler       = "lambda_function.lambda_handler"
  timeout       = 30
  memory_size   = 128

  # Use external file instead of inline code
  filename         = data.archive_file.cpu_mock.output_path
  source_code_hash = data.archive_file.cpu_mock.output_base64sha256

  environment {
    variables = {
      SQS_QUEUE_URL        = var.sqs_queue_url
      STORIES_TABLE_NAME   = var.stories_table_name
      MOCK_MIN_MS_PARAM    = aws_ssm_parameter.mock_min_ms.name
      MOCK_MAX_MS_PARAM    = aws_ssm_parameter.mock_max_ms.name
    }
  }

  tags = var.tags
}

# Create ZIP from external Python files
data "archive_file" "cpu_mock" {
  type        = "zip"
  output_path = "${path.module}/cpu_mock_lambda.zip"

  source {
    content  = file("${path.module}/lambda_function.py")
    filename = "lambda_function.py"
  }
}

# SQS Event Source Mapping (REAL-TIME PROCESSING)
resource "aws_lambda_event_source_mapping" "cpu_mock_sqs_trigger" {
  event_source_arn = var.sqs_queue_arn
  function_name    = aws_lambda_function.cpu_mock.arn
  
  batch_size                         = 5
  maximum_batching_window_in_seconds = 1
  enabled                            = true

  tags = var.tags
}

# CloudWatch Event Rule to trigger Lambda periodically (every 1 minute)
resource "aws_cloudwatch_event_rule" "cpu_mock_trigger" {
  name                = "${var.prefix}-cpu-mock-trigger"
  description         = "Trigger CPU Mock Lambda periodically"
  schedule_expression = "rate(1 minute)"
  
  tags = var.tags
}

resource "aws_cloudwatch_event_target" "cpu_mock_target" {
  rule = aws_cloudwatch_event_rule.cpu_mock_trigger.name
  arn  = aws_lambda_function.cpu_mock.arn
}

resource "aws_lambda_permission" "allow_cloudwatch" {
  statement_id  = "AllowExecutionFromCloudWatch"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.cpu_mock.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.cpu_mock_trigger.arn
}

# CloudWatch Log Group for Lambda
resource "aws_cloudwatch_log_group" "cpu_mock" {
  name              = "/aws/lambda/${aws_lambda_function.cpu_mock.function_name}"
  retention_in_days = 7
  
  tags = var.tags
}