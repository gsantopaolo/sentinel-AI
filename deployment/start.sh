#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -euo pipefail

# Detect the absolute path of the directory this script resides in
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source the .env file (expected alongside this script)
if [ -f "$SCRIPT_DIR/.env" ]; then
  echo "Sourcing .env file..."
  source "$SCRIPT_DIR/.env"
else
  echo ".env file not found. Please create one based on .env.example. Exiting."
  exit 1
fi

# Resolve DATA_PATH relative to deployment directory if given as a relative path
if [[ "${DATA_PATH}" != /* ]]; then
  DATA_DIR="$SCRIPT_DIR/${DATA_PATH%/}"
else
  DATA_DIR="${DATA_PATH%/}"
fi

# Ensure DATA_PATH seen by docker compose is absolute (required for bind mounts in driver_opts)
export DATA_PATH="$DATA_DIR"

# Function to ensure directory exists and has correct permissions
ensure_dir() {
  dir_path=$1
  # Check if directory exists, create if not
  if [ ! -d "$dir_path" ]; then
    echo "Creating directory: $dir_path"
    mkdir -p "$dir_path"
  else
    echo "Directory already exists: $dir_path"
  fi
}

# Ensure data directories exist
ensure_dir "${DATA_DIR}/nats"
ensure_dir "${DATA_DIR}/qdrant"
ensure_dir "${DATA_DIR}/postgres"
ensure_dir "${DATA_DIR}/portainer"
ensure_dir "${DATA_DIR}/traefik-certs"

# Set permissive permissions so Docker containers can write to host-mounted volumes
echo "Setting write permissions on data directory tree (${DATA_DIR})"
chmod -R a+rwx "${DATA_DIR}"

# Ensure Docker networks exist, if not, create them as external
check_and_create_network() {
  network_name=$1
  if ! docker network ls --format "{{.Name}}" | grep -q "^$network_name$"; then
    echo "Creating external Docker network: $network_name"
    docker network create --driver bridge "$network_name"
  else
    echo "Docker network already exists: $network_name"
  fi
}

check_and_create_network "sentinel-frontend-network"
check_and_create_network "sentinel-backend-network"

# Bring up Docker Compose stacks

# Portainer
docker compose \
  -p sentinel-infra \
  --env-file "$SCRIPT_DIR/.env" \
  -f "$SCRIPT_DIR/docker-compose.infra.yml" \
  up -d "$@"

# Combined Base services (NATS, Qdrant, Postgres) and Sentinel AI microservices (including web)
docker compose \
  -p sentinel-services \
  --env-file "$SCRIPT_DIR/.env" \
  -f "$SCRIPT_DIR/docker-compose.services.yml" \
  up -d "$@"

echo " "
echo " "
echo "                                🕵️‍♂️🤖 Sentinel AI 🕵️‍♂️🤖"
echo "            deployment initiated. Check Docker logs via Portainer for status."
echo "   "
echo "                                   🔗 Links 🔗"
echo "   "
echo "  🌎  Sentinel-AI Web UI          http://localhost:8501"
echo "  🧩  OpenAPI Specs               http://localhost:8000/docs, http://localhost:8000/redoc"
echo "  🗃️ OpenAPI JSON Specs          http://localhost:8000/openapi.json"
echo "   "
echo "  🐳  Portainer Dashboard         http://localhost:${PORTAINER_PORT}"
echo "  🧠  Qdrant Dashboard            http://localhost:6333/dashboard"
echo "  🐘  Postgres Dashboard          http://localhost:16543"
echo "  ✉️  NATS Dashboard              http://localhost:8502"
echo "   "
echo " "
