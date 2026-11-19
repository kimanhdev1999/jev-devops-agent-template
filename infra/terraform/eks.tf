module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.37"

  count = var.enable_cluster ? 1 : 0

  cluster_name    = var.name
  cluster_version = var.kubernetes_version

  # Public endpoint so the Lambdas (which run outside the VPC to avoid NAT) and
  # your laptop can reach the API server. Authentication is still IAM + access entries.
  cluster_endpoint_public_access = true

  # Cost trims for a cluster that is created/destroyed daily:
  # - no customer-managed KMS key (EKS still envelope-encrypts Secrets with an
  #   AWS-owned key); a new CMK per cycle would pile up keys pending deletion.
  # - no control-plane (api/audit/authenticator) logs; audit logs are the
  #   biggest CloudWatch cost and the demo doesn't read them.
  create_kms_key              = false
  cluster_encryption_config   = {}
  cluster_enabled_log_types   = []
  create_cloudwatch_log_group = false

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.public_subnets

  authentication_mode                      = "API"
  enable_cluster_creator_admin_permissions = true

  cluster_addons = {
    coredns                = {}
    kube-proxy             = {}
    vpc-cni                = { before_compute = true }
    eks-pod-identity-agent = {}
    # Container Insights + Fluent Bit -> /aws/containerinsights/<cluster>/application
    amazon-cloudwatch-observability = {}
  }

  eks_managed_node_groups = {
    default = {
      instance_types = [var.node_instance_type]
      capacity_type  = "ON_DEMAND"
      min_size       = var.node_count
      max_size       = var.node_count
      desired_size   = var.node_count
      subnet_ids     = module.vpc.public_subnets

      # Lets the CloudWatch agent / Fluent Bit DaemonSets on the nodes ship
      # metrics and logs. Node-role is the simplest option for a demo.
      iam_role_additional_policies = {
        cloudwatch = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
      }
    }
  }

  access_entries = merge(
    {
      # Analyzer: read-only, built-in view policy scoped to the app namespace.
      analyzer = {
        principal_arn = aws_iam_role.analyzer.arn
        policy_associations = {
          view = {
            policy_arn = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSViewPolicy"
            access_scope = {
              type       = "namespace"
              namespaces = [var.app_namespace]
            }
          }
        }
      }

      # Executor: no AWS-managed policy at all. It only gets the Kubernetes group
      # bound to the narrow Role in k8s.tf (patch one Deployment in one namespace).
      executor = {
        principal_arn     = aws_iam_role.executor.arn
        kubernetes_groups = [local.executor_k8s_group]
      }
    },
    {
      for i, arn in var.admin_principal_arns : "admin-${i}" => {
        principal_arn = arn
        policy_associations = {
          admin = {
            policy_arn   = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
            access_scope = { type = "cluster" }
          }
        }
      }
    }
  )
}
