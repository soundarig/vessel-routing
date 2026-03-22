#!/bin/bash
# =============================================================================
# create-secrets.sh — Collect secrets, write base64 to secret.yaml, apply to k8s
#
# Usage:
#   ./scripts/create-secrets.sh
# =============================================================================
set -e

NAMESPACE="vesops"
SECRET_NAME="vessel-routing-secrets"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SECRET_FILE="${PROJECT_DIR}/k8s/dev/secrets.yaml"

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
[ -z "${OAUTH_CLIENT_ID}" ] && { log_error "OAUTH_CLIENT_ID cannot be empty"; exit 1; }

read -s -p "  OAUTH_CLIENT_SECRET : " OAUTH_CLIENT_SECRET
echo ""
[ -z "${OAUTH_CLIENT_SECRET}" ] && { log_error "OAUTH_CLIENT_SECRET cannot be empty"; exit 1; }

echo ""

# ---------------------------------------------------------------------------
# Collect inbound API credentials
# ---------------------------------------------------------------------------
log_info "Inbound API credentials (used by callers to authenticate with this service)"
echo ""

read -p "  API_USERNAME        : " API_USERNAME
[ -z "${API_USERNAME}" ] && { log_error "API_USERNAME cannot be empty"; exit 1; }

read -s -p "  API_PASSWORD        : " API_PASSWORD
echo ""
[ -z "${API_PASSWORD}" ] && { log_error "API_PASSWORD cannot be empty"; exit 1; }

# Generate bcrypt hash
log_info "Generating bcrypt hash for API_PASSWORD..."
API_PASSWORD_HASH=$(python3 -c "from passlib.hash import bcrypt; print(bcrypt.hash('${API_PASSWORD}'))" 2>/dev/null)
[ -z "${API_PASSWORD_HASH}" ] && { log_error "Failed to generate bcrypt hash. Run: pip install passlib[bcrypt]"; exit 1; }
log_info "bcrypt hash generated."

echo ""

# ---------------------------------------------------------------------------
# SQL Server connection details (for ports database)
# ---------------------------------------------------------------------------
log_info "SQL Server connection details (for ports database — leave blank to skip)"
echo ""
read -p "  DB_HOST (e.g. 192.168.1.10 or sqlserver.example.com, leave blank to skip) : " DB_HOST
if [ -n "${DB_HOST}" ]; then
    read -p "  DB_PORT (default: 1433, leave blank to skip)                              : " DB_PORT
    DB_PORT="${DB_PORT:-1433}"
    read -p "  DB_USER (e.g. sa, leave blank to skip)                                   : " DB_USER
    read -s -p "  DB_PASSWORD                                                              : " DB_PASSWORD
    echo ""
    read -p "  DB_NAME (e.g. EDNaviGas, leave blank to skip)                            : " DB_NAME
fi
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
# Confirm
# ---------------------------------------------------------------------------
echo "============================================"
echo " Summary"
echo "  OAUTH_CLIENT_ID     : ${OAUTH_CLIENT_ID}"
echo "  OAUTH_CLIENT_SECRET : ****"
echo "  API_USERNAME        : ${API_USERNAME}"
echo "  API_PASSWORD_HASH   : (bcrypt)"
echo "  JWT_SECRET_KEY      : ****"
echo "  DB_HOST             : $([ -n "${DB_HOST}" ] && echo "${DB_HOST}" || echo "not set")"
echo "============================================"
echo ""
read -p "Write to ${SECRET_FILE} and apply to namespace '${NAMESPACE}'? [y/N] " CONFIRM
if [[ "${CONFIRM}" != "y" && "${CONFIRM}" != "Y" ]]; then
    log_warn "Aborted. No changes made."
    exit 0
fi

# ---------------------------------------------------------------------------
# Base64 encode all values
# ---------------------------------------------------------------------------
b64() { echo -n "$1" | base64 | tr -d '\n'; }

B64_OAUTH_CLIENT_ID=$(b64 "${OAUTH_CLIENT_ID}")
B64_OAUTH_CLIENT_SECRET=$(b64 "${OAUTH_CLIENT_SECRET}")
B64_API_USERNAME=$(b64 "${API_USERNAME}")
B64_API_PASSWORD_HASH=$(b64 "${API_PASSWORD_HASH}")
B64_JWT_SECRET_KEY=$(b64 "${JWT_SECRET_KEY}")
B64_DB_HOST=$(b64 "${DB_HOST}")
B64_DB_PORT=$(b64 "${DB_PORT:-1433}")
B64_DB_USER=$(b64 "${DB_USER}")
B64_DB_PASSWORD=$(b64 "${DB_PASSWORD}")
B64_DB_NAME=$(b64 "${DB_NAME}")

# ---------------------------------------------------------------------------
# Write secrets.yaml with real base64 values
# ---------------------------------------------------------------------------
log_info "Writing base64-encoded secrets to ${SECRET_FILE}..."
log_info "PROJECT_DIR resolved to: ${PROJECT_DIR}"

# Ensure directory exists
mkdir -p "$(dirname "${SECRET_FILE}")"

cat > "${SECRET_FILE}" <<EOF
# Auto-generated by create-secrets.sh — DO NOT commit this file with real values
apiVersion: v1
kind: Secret
metadata:
  name: ${SECRET_NAME}
  namespace: ${NAMESPACE}
type: Opaque
data:
  OAUTH_CLIENT_ID: ${B64_OAUTH_CLIENT_ID}
  OAUTH_CLIENT_SECRET: ${B64_OAUTH_CLIENT_SECRET}
  API_USERNAME: ${B64_API_USERNAME}
  API_PASSWORD_HASH: ${B64_API_PASSWORD_HASH}
  JWT_SECRET_KEY: ${B64_JWT_SECRET_KEY}
  DB_HOST: ${B64_DB_HOST}
  DB_PORT: ${B64_DB_PORT}
  DB_USER: ${B64_DB_USER}
  DB_PASSWORD: ${B64_DB_PASSWORD}
  DB_NAME: ${B64_DB_NAME}
EOF

log_info "secret.yaml updated at ${SECRET_FILE}"
log_info "File size: $(wc -c < "${SECRET_FILE}") bytes"
log_warn "DO NOT commit this file — it contains real credentials!"

# Ensure .gitignore covers the secret file
GITIGNORE="${PROJECT_DIR}/.gitignore"
GITIGNORE_ENTRY="k8s/dev/secrets.yaml"
if [ ! -f "${GITIGNORE}" ]; then
    echo "${GITIGNORE_ENTRY}" > "${GITIGNORE}"
    log_info "Created .gitignore with secret.yaml entry"
elif ! grep -q "${GITIGNORE_ENTRY}" "${GITIGNORE}"; then
    echo "${GITIGNORE_ENTRY}" >> "${GITIGNORE}"
    log_info "Added ${GITIGNORE_ENTRY} to .gitignore"
fi

echo ""
log_info "Run ./scripts/deploy.sh to apply and deploy."