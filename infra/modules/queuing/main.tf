resource "aws_sqs_queue" "queue" {
  name                      = "${var.project}-${var.env}-${var.region}-queue"
  delay_seconds             = 0
  fifo_queue                = false
  visibility_timeout_seconds = 30

  tags = {
    Name    = "${var.project}-${var.env}-${var.region}-queue"
    Project = var.project
    Env     = var.env
    Region  = var.region
  }
}