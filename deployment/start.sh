#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -euo pipefail

# Source the .env file
if [ -f "deployment/.env" ]; then
  echo "Sourcing .env file..."
  source deployment/.env
else
  echo ".env file not found. Please create one based on .env.example. Exiting."
  exit 1
fi

# --- Start: Specific check for problematic variables ---
# This check is added because complex multi-line variables (like CB_ENVS from another project)
# can cause syntax errors when sourced by bash if not properly escaped or handled.
# If you copied content from 'excluded/deployment/.env' into your 'deployment/.env',
# please ensure such variables are removed or correctly formatted for bash.
if [ -n "${CB_ENVS:-}" ]; then
  echo "
⚠️ WARNING: The 'CB_ENVS' variable was found in your deployment/.env file."
  echo "This variable contains complex multi-line content that can cause syntax errors."
  echo "It is likely from another project and is NOT needed for Sentinel AI."
  echo "Please remove 'CB_ENVS' from your deployment/.env file and try again."
  exit 1
fi
# --- End: Specific check for problematic variables ---

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
ensure_dir "${DATA_PATH}/nats"
ensure_dir "${DATA_PATH}/qdrant"
ensure_dir "${DATA_PATH}/postgres"
ensure_dir "${DATA_PATH}/portainer"
ensure_dir "${DATA_PATH}/traefik-certs"

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

check_and_create_network "frontend-network"
check_and_create_network "backend-network"

# Bring up Docker Compose stacks

# Traefik & portainer
docker compose \
  -p sentinel-infra \
  --env-file deployment/.env \
  -f deployment/docker-compose.infra.yml \
  up -d "$@"

# Base services (NATS, Qdrant, Postgres)
docker compose \
  -p sentinel-db \
  --env-file deployment/.env \
  -f deployment/docker-compose.db.yml \
  up -d "$@"

# Sentinel AI microservices (including web)
docker compose \
  -p sentinel-services \
  --env-file deployment/.env \
  -f deployment/docker-compose.services.yml \
  up -d "$@"





echo "\nSentinel AI deployment initiated. Check Docker logs for status."
echo "Traefik Dashboard: http://localhost:${TRAEFIK_DASHBOARD_PORT}"
echo "Portainer: http://localhost:${PORTAINER_PORT}"
echo "API: http://localhost:${TRAEFIK_HTTP_PORT}/api"
echo "Web UI: http://localhost:${TRAEFIK_HTTP_PORT}/web"