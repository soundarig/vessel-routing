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
if docker ps --format '{{.Ports}}' 2>/dev/null | grep -q '0.0.0.0:5000'; then
  echo "Registry already running on port 5000."
else
  echo "Starting local Docker registry on port 5000..."
  docker run -d --name registry --restart=always -p 5000:5000 registry:2
fi

# ---------------------------------------------------------------------------
# Step 2 — Build Docker image locally
# ---------------------------------------------------------------------------
echo ""
echo "[2/5] Building Docker image..."
docker build -t "${FULL_IMAGE}" "${PROJECT_DIR}"

# ---------------------------------------------------------------------------
# Step 3 — Push image to k3s server registry
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Step 3 — Configure insecure registry then push
# ---------------------------------------------------------------------------
echo ""
echo "[3/5] Configuring insecure registry and pushing image to ${REGISTRY}..."

# Add insecure registry to Docker daemon config if not already there
DAEMON_JSON="/etc/docker/daemon.json"
if ! grep -q "${K3S_SERVER_IP}:5000" "${DAEMON_JSON}" 2>/dev/null; then
  echo "Adding insecure registry to ${DAEMON_JSON}..."
  if [ -f "${DAEMON_JSON}" ]; then
    # File exists — merge insecure-registries entry using python
    python3 -c "
import json, sys
with open('${DAEMON_JSON}') as f:
    cfg = json.load(f)
regs = cfg.get('insecure-registries', [])
if '${K3S_SERVER_IP}:5000' not in regs:
    regs.append('${K3S_SERVER_IP}:5000')
cfg['insecure-registries'] = regs
with open('${DAEMON_JSON}', 'w') as f:
    json.dump(cfg, f, indent=2)
print('Updated daemon.json')
"
  else
    echo '{"insecure-registries": ["'"${K3S_SERVER_IP}:5000"'"]}' > "${DAEMON_JSON}"
    echo "Created daemon.json"
  fi
  echo "Restarting Docker daemon..."
  systemctl restart docker
  sleep 3
  echo "Docker restarted."
else
  echo "Insecure registry already configured."
fi

docker push "${FULL_IMAGE}"

# ---------------------------------------------------------------------------
# Step 4 — Configure k3s to trust the local registry (idempotent)
# ---------------------------------------------------------------------------
echo ""
echo "[4/5] Configuring k3s registry mirror..."
mkdir -p /etc/rancher/k3s
cat > /etc/rancher/k3s/registries.yaml <<EOF
mirrors:
  "${K3S_SERVER_IP}:5000":
    endpoint:
      - "http://${K3S_SERVER_IP}:5000"
EOF
echo "Registry config written."

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
