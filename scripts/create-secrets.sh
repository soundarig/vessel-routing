#!/bin/bash
# =============================================================================
# create-secrets.sh — Interactively collect secrets and apply to k8s
#
# Usage:
#   ./scripts/create-secrets.sh
# =============================================================================
set -e

NAMESPACE="vesops"
SECRET_NAME="vessel-routing-secrets"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo "============================================"
echo " vessel-routing-client secret setup"
echo " Namespace : ${NAMESPACE}"
echo "============================================"
echo ""

# ---------------------------------------------------------------------------
# Collect ABB OAuth2 credentials
# ---------------------------------------------------------------------------
log_info "ABB OAuth2 credentials (outbound — used to call ABB routing API)"
echo ""

read -p "  OAUTH_CLIENT_ID     : " OAUTH_CLIENT_ID
if [ -z "${OAUTH_CLIENT_ID}" ]; then
    log_error "OAUTH_CLIENT_ID cannot be empty"
    exit 1
fi

read -s -p "  OAUTH_CLIENT_SECRET : " OAUTH_CLIENT_SECRET
echo ""
if [ -z "${OAUTH_CLIENT_SECRET}" ]; then
    log_error "OAUTH_CLIENT_SECRET cannot be empty"
    exit 1
fi

echo ""

# ---------------------------------------------------------------------------
# Collect inbound API credentials
# ---------------------------------------------------------------------------
log_info "Inbound API credentials (used by callers to authenticate with this service)"
echo ""

read -p "  API_USERNAME        : " API_USERNAME
if [ -z "${API_USERNAME}" ]; then
    log_error "API_USERNAME cannot be empty"
    exit 1
fi

read -s -p "  API_PASSWORD        : " API_PASSWORD
echo ""
if [ -z "${API_PASSWORD}" ]; then
    log_error "API_PASSWORD cannot be empty"
    exit 1
fi

# Generate bcrypt hash from the password
log_info "Generating bcrypt hash for API_PASSWORD..."
API_PASSWORD_HASH=$(python3 -c "from passlib.hash import bcrypt; print(bcrypt.hash('${API_PASSWORD}'))" 2>/dev/null)
if [ -z "${API_PASSWORD_HASH}" ]; then
    log_error "Failed to generate bcrypt hash. Is passlib installed? (pip install passlib[bcrypt])"
    exit 1
fi
log_info "bcrypt hash generated."

echo ""

# ---------------------------------------------------------------------------
# JWT secret
# ---------------------------------------------------------------------------
log_info "JWT signing secret"
echo ""
read -p "  JWT_SECRET_KEY (leave blank to auto-generate) : " JWT_SECRET_KEY
if [ -z "${JWT_SECRET_KEY}" ]; then
    JWT_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    log_info "Auto-generated JWT_SECRET_KEY."
fi

echo ""

# ---------------------------------------------------------------------------
# Confirm before applying
# ---------------------------------------------------------------------------
echo "============================================"
echo " Summary (secrets will NOT be shown)"
echo "  OAUTH_CLIENT_ID     : ${OAUTH_CLIENT_ID}"
echo "  OAUTH_CLIENT_SECRET : ****"
echo "  API_USERNAME        : ${API_USERNAME}"
echo "  API_PASSWORD_HASH   : (bcrypt)"
echo "  JWT_SECRET_KEY      : ****"
echo "============================================"
echo ""
read -p "Apply these secrets to namespace '${NAMESPACE}'? [y/N] " CONFIRM
if [[ "${CONFIRM}" != "y" && "${CONFIRM}" != "Y" ]]; then
    log_warn "Aborted. No changes made."
    exit 0
fi

# ---------------------------------------------------------------------------
# Apply to Kubernetes
# ---------------------------------------------------------------------------
log_info "Applying secret '${SECRET_NAME}' to namespace '${NAMESPACE}'..."

kubectl create secret generic "${SECRET_NAME}" \
    --namespace "${NAMESPACE}" \
    --from-literal=OAUTH_CLIENT_ID="${OAUTH_CLIENT_ID}" \
    --from-literal=OAUTH_CLIENT_SECRET="${OAUTH_CLIENT_SECRET}" \
    --from-literal=API_USERNAME="${API_USERNAME}" \
    --from-literal=API_PASSWORD_HASH="${API_PASSWORD_HASH}" \
    --from-literal=JWT_SECRET_KEY="${JWT_SECRET_KEY}" \
    --dry-run=client -o yaml | kubectl apply -f -

log_info "Secret applied successfully."
echo ""
log_info "To verify:"
echo "  kubectl get secret ${SECRET_NAME} -n ${NAMESPACE}"
echo "  kubectl describe secret ${SECRET_NAME} -n ${NAMESPACE}"
