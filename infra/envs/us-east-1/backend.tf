terraform {
  backend "s3" {
    bucket         = "lunebi-prod-us-east-1-tfstate"
    key            = "terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "lunebi-prod-us-east-1-lock"
    encrypt        = true
  }
}
