provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = var.name
      Purpose   = "jev-incident-demo"
      ManagedBy = "terraform"
    }
  }
}

# While enable_cluster = false these resolve to null; that's fine because no
# Kubernetes/Helm resources exist then (cluster.sh removes them first).
# Both providers authenticate to the new cluster with a short-lived token from
# `aws eks get-token`, so the machine running terraform needs the AWS CLI.
provider "kubernetes" {
  host                   = try(module.eks[0].cluster_endpoint, null)
  cluster_ca_certificate = try(base64decode(module.eks[0].cluster_certificate_authority_data), null)

  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", local.cluster_name, "--region", var.region]
  }
}

provider "helm" {
  kubernetes {
    host                   = try(module.eks[0].cluster_endpoint, null)
    cluster_ca_certificate = try(base64decode(module.eks[0].cluster_certificate_authority_data), null)

    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", local.cluster_name, "--region", var.region]
    }
  }
}
