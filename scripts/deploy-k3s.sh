#!/usr/bin/env bash
# =============================================================================
# deploy-k3s.sh — Build, push to k3s local registry, and deploy
#
# Usage:
#   ./scripts/deploy-k3s.sh <k3s-server-ip> [image-tag]
#
# Prerequisites on the k3s server:
#   k3s with the built-in registry enabled:
#     /etc/rancher/k3s/registries.yaml must contain the mirror config (see below)
#
# Example:
#   ./scripts/deploy-k3s.sh 192.168.1.100 v1.0.0
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------
K3S_SERVER_IP="${1:?Usage: $0 <k3s-server-ip> [image-tag]}"
IMAGE_TAG="${2:-latest}"
IMAGE_NAME="vessel-routing-client"
REGISTRY="${K3S_SERVER_IP}:5000"
FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "============================================"
echo " vessel-routing-client k3s deployment"
echo " Server  : ${K3S_SERVER_IP}"
echo " Image   : ${FULL_IMAGE}"
echo "============================================"

# ---------------------------------------------------------------------------
# Step 1 — Ensure local registry is running on the k3s server
# ---------------------------------------------------------------------------
echo ""
echo "[1/5] Ensuring local registry is running on k3s server..."
ssh "root@${K3S_SERVER_IP}" bash <<'REMOTE'
if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^registry$'; then
  echo "Starting local Docker registry on port 5000..."
  docker run -d --name registry --restart=always -p 5000:5000 registry:2
else
  echo "Registry already running."
fi
REMOTE

# ---------------------------------------------------------------------------
# Step 2 — Build Docker image locally
# ---------------------------------------------------------------------------
echo ""
echo "[2/5] Building Docker image..."
docker build -t "${FULL_IMAGE}" "${PROJECT_DIR}"

# ---------------------------------------------------------------------------
# Step 3 — Push image to k3s server registry
# ---------------------------------------------------------------------------
echo ""
echo "[3/5] Pushing image to ${REGISTRY}..."
# Allow insecure registry for local k3s
if ! grep -q "${K3S_SERVER_IP}:5000" /etc/docker/daemon.json 2>/dev/null; then
  echo "NOTE: If push fails, add to /etc/docker/daemon.json on this machine:"
  echo '  {"insecure-registries": ["'"${K3S_SERVER_IP}:5000"'"]}'
fi
docker push "${FULL_IMAGE}"

# ---------------------------------------------------------------------------
# Step 4 — Configure k3s to trust the local registry (idempotent)
# ---------------------------------------------------------------------------
echo ""
echo "[4/5] Configuring k3s registry mirror on server..."
ssh "root@${K3S_SERVER_IP}" bash <<REMOTE
mkdir -p /etc/rancher/k3s
cat > /etc/rancher/k3s/registries.yaml <<EOF
mirrors:
  "${K3S_SERVER_IP}:5000":
    endpoint:
      - "http://${K3S_SERVER_IP}:5000"
EOF
echo "Registry config written."
REMOTE

# ---------------------------------------------------------------------------
# Step 5 — Apply k8s manifests
# ---------------------------------------------------------------------------
echo ""
echo "[5/5] Applying Kubernetes manifests..."

# Patch the deployment image to use the registry image
PATCHED_DEPLOYMENT=$(mktemp)
sed "s|image: vessel-routing-client:latest|image: ${FULL_IMAGE}|g" \
  "${PROJECT_DIR}/k8s/deployment.yaml" > "${PATCHED_DEPLOYMENT}"

# Apply in order
kubectl apply -f "${PROJECT_DIR}/k8s/namespace.yaml"
kubectl apply -f "${PROJECT_DIR}/k8s/secret.yaml"
kubectl apply -f "${PATCHED_DEPLOYMENT}"
kubectl apply -f "${PROJECT_DIR}/k8s/service.yaml"
kubectl apply -f "${PROJECT_DIR}/k8s/nodeport.yaml"
kubectl apply -f "${PROJECT_DIR}/k8s/hpa.yaml"

rm -f "${PATCHED_DEPLOYMENT}"

# ---------------------------------------------------------------------------
# Wait for rollout
# ---------------------------------------------------------------------------
echo ""
echo "Waiting for rollout to complete..."
kubectl rollout status deployment/vessel-routing-client -n vessel-routing --timeout=120s

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
NODE_PORT=$(kubectl get svc vessel-routing-client-external -n vessel-routing \
  -o jsonpath='{.spec.ports[0].nodePort}' 2>/dev/null || echo "30800")

echo ""
echo "============================================"
echo " Deployment complete!"
echo " API available at:"
echo "   http://${K3S_SERVER_IP}:${NODE_PORT}/health"
echo "   http://${K3S_SERVER_IP}:${NODE_PORT}/auth/token"
echo "   http://${K3S_SERVER_IP}:${NODE_PORT}/route"
echo "   Swagger UI: http://${K3S_SERVER_IP}:${NODE_PORT}/docs"
echo "============================================"
