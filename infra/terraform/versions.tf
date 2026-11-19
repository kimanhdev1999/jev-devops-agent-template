terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.95" # terraform-aws-modules/eks v20 requires aws < 6.0
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.36"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.17"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.7"
    }
  }

  # Partial config: terraform init -backend-config=backend.hcl
  # (copy backend.hcl.example and set your state bucket).
  backend "s3" {}
}
