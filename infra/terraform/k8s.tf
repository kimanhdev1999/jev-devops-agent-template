locals {
  executor_k8s_group = "${var.name}-rollback-executor"
}

resource "kubernetes_namespace_v1" "app" {
  count = var.enable_cluster ? 1 : 0

  metadata {
    name = var.app_namespace
  }

  depends_on = [module.eks]
}

# The executor's entire write surface: read the Deployment and its ReplicaSets,
# and patch that ONE Deployment (what `kubectl rollout undo` does). No delete,
# no create, no access to Secrets, nothing outside this namespace.
resource "kubernetes_role_v1" "rollback" {
  count = var.enable_cluster ? 1 : 0

  metadata {
    name      = "rollback-executor"
    namespace = kubernetes_namespace_v1.app[0].metadata[0].name
  }

  rule {
    api_groups     = ["apps"]
    resources      = ["deployments"]
    resource_names = [var.app_name]
    verbs          = ["get", "patch"]
  }

  rule {
    api_groups = ["apps"]
    resources  = ["replicasets"]
    verbs      = ["get", "list"]
  }
}

resource "kubernetes_role_binding_v1" "rollback" {
  count = var.enable_cluster ? 1 : 0

  metadata {
    name      = "rollback-executor"
    namespace = kubernetes_namespace_v1.app[0].metadata[0].name
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Role"
    name      = kubernetes_role_v1.rollback[0].metadata[0].name
  }

  subject {
    kind      = "Group"
    name      = local.executor_k8s_group
    api_group = "rbac.authorization.k8s.io"
  }
}

# Installs the healthy v1 (fresh on every ./cluster.sh up, so each session
# starts healthy). The demo breaks it out-of-band with
# `helm upgrade --reuse-values --set version=v2 --set breakDb=true`,
# so later plans ignore value drift instead of "fixing" the incident.
resource "helm_release" "demo_shop" {
  count = var.enable_cluster ? 1 : 0

  name      = var.app_name
  namespace = kubernetes_namespace_v1.app[0].metadata[0].name
  chart     = "${path.module}/../../charts/demo-shop"

  values = [yamlencode({
    version = "v1"
    breakDb = false
  })]

  wait    = true
  timeout = 300

  lifecycle {
    ignore_changes = [values, set]
  }

  # Fluent Bit (from the observability add-on) must be running before the
  # first log lines, or they're lost.
  depends_on = [module.eks, aws_cloudwatch_log_group.application]
}
