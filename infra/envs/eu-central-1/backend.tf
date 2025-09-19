terraform {
  backend "s3" {
    bucket         = "lunebi-prod-eu-central-1-tfstate"
    key            = "terraform.tfstate"
    region         = "eu-central-1"
    dynamodb_table = "lunebi-prod-eu-central-1-lock"
    encrypt        = true
  }
}
