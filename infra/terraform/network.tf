data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, 2)
}

# Public subnets only, no NAT gateway: nodes get public IPs and reach ECR,
# CloudWatch and Docker Hub directly. That saves ~$1/day of NAT charges for a
# one-day demo. Do NOT copy this layout to production.
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.21"

  name = var.name
  cidr = var.vpc_cidr
  azs  = local.azs

  public_subnets          = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, i)]
  map_public_ip_on_launch = true

  enable_nat_gateway   = false
  enable_dns_hostnames = true
  enable_dns_support   = true

  public_subnet_tags = {
    "kubernetes.io/role/elb" = 1
  }
}
