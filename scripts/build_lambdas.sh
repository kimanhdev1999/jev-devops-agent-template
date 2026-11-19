#!/usr/bin/env bash
# Assemble the Lambda packages into infra/terraform/.build/src/<name>/ (what
# Terraform zips). Run before every `terraform apply`; cluster.sh does it for you.
#   analyzer: handler + agent/{incident,router,masking,integrations} + anthropic, pydantic
#   executor: handler + agent/integrations (stdlib + boto3 from the runtime only)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/infra/terraform/.build/src"
PY=${PYTHON:-python3}

build() {  # name, agent modules...
  local name=$1; shift
  local dir="$OUT/$name"
  rm -rf "$dir" && mkdir -p "$dir/agent"
  cp "$ROOT/lambdas/$name/handler.py" "$dir/"
  touch "$dir/agent/__init__.py"
  for m in "$@"; do cp "$ROOT/agent/$m.py" "$dir/agent/"; done
}

build analyzer incident router masking integrations
build executor integrations

# Linux x86_64 / CPython 3.12 wheels to match the Lambda runtime (pydantic-core is compiled).
"$PY" -m pip install --quiet --disable-pip-version-check \
  --platform manylinux2014_x86_64 --implementation cp --python-version 3.12 --only-binary=:all: \
  --target "$OUT/analyzer" "anthropic>=2.10" "pydantic>=2.6"
find "$OUT" -name '__pycache__' -prune -exec rm -rf {} +
du -sh "$OUT"/* | sed 's#'"$OUT"'/##'
