resource "aws_dynamodb_table" "voices" {
  name         = "${var.project}-${var.env}-${var.region}-voices"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "voice_id"

  attribute {
    name = "voice_id"
    type = "S"
  }
}


resource "aws_dynamodb_table" "stories" {
  name         = "${var.project}-${var.env}-${var.region}-stories"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "story_id"

  attribute {
    name = "story_id"
    type = "S"
  }
}
