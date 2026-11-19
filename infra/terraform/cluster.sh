#!/usr/bin/env bash
# Turn the EKS part of the demo on/off while keeping everything else
# (Lambdas, secrets, Slack Function URL, alarm, log group) in place.
#
#   ./cluster.sh up       # create EKS + nodes + demo-shop v1   (~20 min, ~$0.20/h after)
#   ./cluster.sh down     # remove them again                   (~10 min, ~$0/h after)
#   ./cluster.sh status   # what's running right now
#
# Requires: AWS_PROFILE exported, terraform init already done.
set -euo pipefail
cd "$(dirname "$0")"

: "${AWS_PROFILE:?export AWS_PROFILE first (e.g. export AWS_PROFILE=will)}"
export AWS_REGION="${AWS_REGION:-ap-south-1}"

IN_CLUSTER_TARGETS=(
  -target=helm_release.demo_shop
  -target=kubernetes_role_binding_v1.rollback
  -target=kubernetes_role_v1.rollback
  -target=kubernetes_namespace_v1.app
)

cluster_name() { terraform output -raw cluster_name 2>/dev/null || echo "jev-incident-demo"; }

case "${1:-}" in
  up)
    ../../scripts/build_lambdas.sh
    terraform apply -var enable_cluster=true
    eval "$(terraform output -raw kubeconfig_command)"
    kubectl get pods -A -l app.kubernetes.io/name=demo-shop
    ;;

  down)
    # Step 1: delete in-cluster objects while the cluster (and the Kubernetes/
    # Helm providers' connection to it) still exists. Skipped if already gone.
    if terraform state list 2>/dev/null | grep -qE '^(helm_release|kubernetes_)'; then
      echo ">> step 1/2: removing in-cluster resources"
      terraform destroy -var enable_cluster=true "${IN_CLUSTER_TARGETS[@]}"
    fi
    # Step 2: remove EKS, node group, add-ons and access entries.
    echo ">> step 2/2: removing the EKS cluster"
    terraform apply -var enable_cluster=false
    ;;

  status)
    name="$(cluster_name)"
    if aws eks describe-cluster --name "$name" --query 'cluster.status' --output text 2>/dev/null; then
      aws eks list-nodegroups --cluster-name "$name" --output text
    else
      echo "cluster $name: not running (no EKS charges)"
    fi
    ;;

  *)
    echo "usage: $0 up|down|status" >&2
    exit 2
    ;;
esac
