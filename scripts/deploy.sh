#!/bin/bash

# Kubernetes deployment script for Smart Fly Data Extractor

set -e

# Prompt for environment
read -p "Enter deployment environment (dev/prod) [dev]: " DEPLOY_ENV
DEPLOY_ENV=${DEPLOY_ENV:-dev}
K8S_DIR="k8s/${DEPLOY_ENV}"
# Configuration
NAMESPACE="vesops"
IMAGE_NAME="vessel-routing"
IMAGE_TAG="${IMAGE_TAG:-latest}"
LOCAL_REGISTRY="localhost:5000"
REGISTRY_NAME="local-registry"
ENABLE_MONITORING="${ENABLE_MONITORING:-false}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."

    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl is not installed"
        exit 1
    fi

    if ! command -v docker &> /dev/null; then
        log_error "docker is not installed"
        exit 1
    fi

    if ! kubectl cluster-info &> /dev/null; then
        log_error "kubectl is not connected to a cluster"
        exit 1
    fi

    log_info "Prerequisites check passed"
}

# Check for local registry
check_local_registry() {
    if docker ps | grep -q $REGISTRY_NAME; then
        log_info "Local registry is running"
    else
        log_info "Starting local registry..."
        docker run -d -p 5000:5000 --name $REGISTRY_NAME --restart=always registry:2
        sleep 2
        log_info "Local registry started on port 5000"
    fi
}

# Build Docker image
build_image() {
    log_info "Building Docker image..."

    docker build -f Dockerfile.k8s -t ${IMAGE_NAME}:${IMAGE_TAG} .

    if [ $? -eq 0 ]; then
        log_info "Docker image built successfully"
    else
        log_error "Failed to build Docker image"
        exit 1
    fi
}

# Push image to local registry
push_to_local_registry() {
    # Safety check - ensure we're only pushing to local registry
    if [[ "${LOCAL_REGISTRY}" != "localhost:5000" ]]; then
        log_error "Safety check failed: LOCAL_REGISTRY is not localhost:5000"
        log_error "Current value: ${LOCAL_REGISTRY}"
        log_error "Aborting to prevent accidental remote push"
        exit 1
    fi

    log_info "Tagging image for local registry..."
    docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${LOCAL_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}

    log_info "Pushing image to local registry (localhost:5000 only)..."
    docker push ${LOCAL_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}

    if [ $? -eq 0 ]; then
        log_info "Image pushed to local registry successfully"

        # Verify image in registry
        log_info "Verifying image in registry..."
        curl -s http://localhost:5000/v2/_catalog | grep -q "vessel-routing" && \
        log_info "Image verified in local registry" || \
        log_warn "Could not verify image in registry"
    else
        log_error "Failed to push image to local registry"
        exit 1
    fi
}

# Create namespace
create_namespace() {
    log_info "Creating namespace..."

    kubectl apply -f $K8S_DIR/namespace.yaml

    if [ $? -eq 0 ]; then
        log_info "Namespace created/updated successfully"
    else
        log_error "Failed to create namespace"
        exit 1
    fi
}

# Deploy secrets (with warning)
deploy_secrets() {
    log_warn "Deploying secrets..."
    log_warn "WARNING: Update the secrets in $K8S_DIR/secrets.yaml with your actual base64-encoded values!"

    kubectl apply -f $K8S_DIR/secrets.yaml -n ${NAMESPACE}

    if [ $? -eq 0 ]; then
        log_info "Secrets deployed successfully"
    else
        log_error "Failed to deploy secrets"
        exit 1
    fi
}

# Update kustomization for monitoring
update_kustomization() {
    if [ "$ENABLE_MONITORING" = true ]; then
        # Add monitoring resources to kustomization
        if ! grep -q "monitoring-optional.yaml" $K8S_DIR/kustomization.yaml; then
            sed -i.bak '/- pdb.yaml/a\
- monitoring-optional.yaml' $K8S_DIR/kustomization.yaml
        fi
    fi

    # Update image reference to use local registry
    sed -i.bak "s|name: vessel-routing|name: ${LOCAL_REGISTRY}/vessel-routing|g" $K8S_DIR/kustomization.yaml
    sed -i.bak "s|newTag: latest|newTag: ${IMAGE_TAG}|g" $K8S_DIR/kustomization.yaml
}

# Deploy application
deploy_app() {
    log_info "Deploying application..."

    # Update kustomization for local registry and monitoring
    update_kustomization

    kubectl apply -k $K8S_DIR/ -n ${NAMESPACE}

    if [ $? -eq 0 ]; then
        log_info "Application deployed successfully"
    else
        log_error "Failed to deploy application"
        exit 1
    fi

    # Restore kustomization file if modified
    if [ -f $K8S_DIR/kustomization.yaml.bak ]; then
        mv $K8S_DIR/kustomization.yaml.bak $K8S_DIR/kustomization.yaml
    fi
}

# Wait for deployment
wait_for_deployment() {
    log_info "Waiting for deployment to be ready..."

    kubectl wait --for=condition=available --timeout=300s deployment/vessel-routing -n ${NAMESPACE}

    if [ $? -eq 0 ]; then
        log_info "Deployment is ready"
    else
        log_error "Deployment failed to become ready"
        exit 1
    fi
}

# Show deployment status
show_status() {
    log_info "Deployment status:"

    echo ""
    kubectl get pods -n ${NAMESPACE} -l app=vessel-routing
    echo ""
    kubectl get services -n ${NAMESPACE}
    echo ""
    kubectl get ingress -n ${NAMESPACE}
    echo ""

    log_info "To check logs, run:"
    echo "kubectl logs -f deployment/vessel-routing -n ${NAMESPACE}"

    log_info "To access the application:"
    echo "kubectl port-forward service/vessel-routing-service 8300:8300 -n ${NAMESPACE}"

    log_info "Local registry info:"
    echo "Registry URL: http://localhost:5000"
    echo "Image: ${LOCAL_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"

    if [ "$ENABLE_MONITORING" = true ]; then
        log_info "Monitoring resources deployed successfully"
    else
        log_warn "Monitoring resources skipped (Prometheus Operator not found)"
        log_warn "To enable monitoring: install Prometheus Operator and redeploy"
    fi
}

# Main deployment function
main() {
    log_info "Starting deployment of FlyVahna Data Extractor to Kubernetes..."

    check_prerequisites
    check_local_registry
    build_image
    push_to_local_registry
    create_namespace
    deploy_secrets
    deploy_app
    wait_for_deployment
    show_status

    log_info "Deployment completed successfully!"
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --tag)
            IMAGE_TAG="$2"
            shift 2
            ;;
        --namespace)
            NAMESPACE="$2"
            shift 2
            ;;
        --enable-monitoring)
            ENABLE_MONITORING=true
            shift
            ;;
        --help)
            echo "Usage: $0 [--tag TAG] [--namespace NAMESPACE] [--enable-monitoring]"
            echo ""
            echo "Options:"
            echo "  --tag TAG            Image tag (default: latest)"
            echo "  --namespace NAMESPACE Kubernetes namespace (default: vesops)"
            echo "  --enable-monitoring  Force enable monitoring (requires Prometheus Operator)"
            echo "  --help               Show this help message"
            echo ""
            echo "Note: This script uses a local Docker registry at localhost:5000"
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Run main function
main