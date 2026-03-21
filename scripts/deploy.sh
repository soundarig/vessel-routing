#!/bin/bash
# =============================================================================
# deploy.sh — Build, push to local registry, and deploy vessel-routing to k3s
#
# Run this ON the k3s server.
#
# Usage:
#   ./scripts/deploy.sh [--tag TAG] [--help]
#
# First-time setup: run create-secrets.sh once before deploying.
# =============================================================================
set -e

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
NAMESPACE="vesops"
IMAGE_NAME="vessel-routing"
IMAGE_TAG="${IMAGE_TAG:-latest}"
LOCAL_REGISTRY="localhost:5000"
REGISTRY_NAME="local-registry"
K8S_DIR="k8s/dev"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ---------------------------------------------------------------------------
# Parse args
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case $1 in
        --tag) IMAGE_TAG="$2"; shift 2 ;;
        --help)
            echo "Usage: $0 [--tag TAG]"
            echo "  --tag TAG   Image tag (default: latest)"
            exit 0 ;;
        *) log_error "Unknown option: $1"; exit 1 ;;
    esac
done

FULL_IMAGE="${LOCAL_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"

echo "============================================"
echo " vessel-routing deployment"
echo " Namespace : ${NAMESPACE}"
echo " Image     : ${FULL_IMAGE}"
echo "============================================"

# ---------------------------------------------------------------------------
# Check prerequisites
# ---------------------------------------------------------------------------
check_prerequisites() {
    log_info "Checking prerequisites..."
    command -v kubectl &>/dev/null || { log_error "kubectl not installed"; exit 1; }
    command -v docker  &>/dev/null || { log_error "docker not installed";  exit 1; }
    kubectl cluster-info &>/dev/null || { log_error "kubectl not connected to cluster"; exit 1; }
    log_info "Prerequisites check passed"
}

# ---------------------------------------------------------------------------
# Ensure local registry is running
# ---------------------------------------------------------------------------
check_local_registry() {
    if docker ps | grep -q "${REGISTRY_NAME}"; then
        log_info "Local registry is running"
    else
        log_info "Starting local registry..."
        docker run -d -p 5000:5000 --name "${REGISTRY_NAME}" --restart=always registry:2
        sleep 2
        log_info "Local registry started on port 5000"
    fi
}

# ---------------------------------------------------------------------------
# Build image
# ---------------------------------------------------------------------------
build_image() {
    log_info "Building Docker image..."
    docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" "${PROJECT_DIR}"
    log_info "Docker image built successfully"
}

# ---------------------------------------------------------------------------
# Push to local registry
# ---------------------------------------------------------------------------
push_to_local_registry() {
    log_info "Tagging image for local registry..."
    docker tag "${IMAGE_NAME}:${IMAGE_TAG}" "${FULL_IMAGE}"

    log_info "Pushing image to local registry..."
    docker push "${FULL_IMAGE}"

    log_info "Verifying image in registry..."
    curl -s http://localhost:5000/v2/_catalog | grep -q "${IMAGE_NAME}" && \
        log_info "Image verified in local registry" || \
        log_warn "Could not verify image in registry"
}

# ---------------------------------------------------------------------------
# Configure k3s registry mirror (idempotent)
# ---------------------------------------------------------------------------
configure_k3s_registry() {
    log_info "Configuring k3s registry mirror..."
    mkdir -p /etc/rancher/k3s
    cat > /etc/rancher/k3s/registries.yaml <<EOF
mirrors:
  "localhost:5000":
    endpoint:
      - "http://localhost:5000"
EOF
    log_info "k3s registry config written"
}

# ---------------------------------------------------------------------------
# Create namespace (skip if already exists — avoids Rancher webhook)
# ---------------------------------------------------------------------------
create_namespace() {
    log_info "Ensuring namespace '${NAMESPACE}' exists..."
    if kubectl get namespace "${NAMESPACE}" &>/dev/null; then
        log_info "Namespace '${NAMESPACE}' already exists"
    else
        kubectl create namespace "${NAMESPACE}"
        log_info "Namespace '${NAMESPACE}' created"
    fi
}

# ---------------------------------------------------------------------------
# Deploy via kustomize — patch image tag at deploy time
# ---------------------------------------------------------------------------
deploy_app() {
    log_info "Deploying application via kustomize..."

    # Patch kustomization image tag to match current build
    sed -i.bak "s|newTag: .*|newTag: ${IMAGE_TAG}|g" "${PROJECT_DIR}/${K8S_DIR}/kustomization.yaml"
    sed -i.bak "s|newName: .*|newName: ${LOCAL_REGISTRY}/${IMAGE_NAME}|g" "${PROJECT_DIR}/${K8S_DIR}/kustomization.yaml"

    kubectl apply -k "${PROJECT_DIR}/${K8S_DIR}/" -n "${NAMESPACE}"

    # Restore kustomization to avoid dirty git state
    if [ -f "${PROJECT_DIR}/${K8S_DIR}/kustomization.yaml.bak" ]; then
        mv "${PROJECT_DIR}/${K8S_DIR}/kustomization.yaml.bak" \
           "${PROJECT_DIR}/${K8S_DIR}/kustomization.yaml"
    fi

    log_info "Application deployed successfully"
}

# ---------------------------------------------------------------------------
# Wait for rollout
# ---------------------------------------------------------------------------
wait_for_deployment() {
    log_info "Waiting for deployment to be ready..."
    kubectl rollout status deployment/vessel-routing-client -n "${NAMESPACE}" --timeout=120s
    log_info "Deployment is ready"
}

# ---------------------------------------------------------------------------
# Show status
# ---------------------------------------------------------------------------
show_status() {
    echo ""
    kubectl get pods     -n "${NAMESPACE}" -l app=vessel-routing-client
    echo ""
    kubectl get services -n "${NAMESPACE}"
    echo ""

    NODE_PORT=$(kubectl get svc vessel-routing-client-external -n "${NAMESPACE}" \
        -o jsonpath='{.spec.ports[0].nodePort}' 2>/dev/null || echo "30830")
    SERVER_IP=$(hostname -I | awk '{print $1}')

    log_info "API available at:"
    echo "  http://${SERVER_IP}:${NODE_PORT}/health"
    echo "  http://${SERVER_IP}:${NODE_PORT}/auth/token"
    echo "  http://${SERVER_IP}:${NODE_PORT}/route"
    echo "  http://${SERVER_IP}:${NODE_PORT}/docs"

    log_info "To check logs:"
    echo "  kubectl logs -f deployment/vessel-routing-client -n ${NAMESPACE}"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    log_info "Starting deployment of vessel-routing..."

    check_prerequisites
    check_local_registry
    build_image
    push_to_local_registry
    configure_k3s_registry
    create_namespace
    deploy_app
    wait_for_deployment
    show_status

    log_info "Deployment completed successfully!"
}

main
