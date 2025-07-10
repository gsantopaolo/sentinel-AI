#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Source the .env file
if [ -f "deployment/.env" ]; then
  echo "Sourcing .env file..."
  source deployment/.env
else
  echo ".env file not found. Exiting. Cannot tear down without .env."
  exit 1
fi

# Check for --volumes or -v flag
REMOVE_VOLUMES=""
for arg in "$@"; do
  if [ "$arg" == "--volumes" ] || [ "$arg" == "-v" ]; then
    REMOVE_VOLUMES="-v"
    echo "Volumes will be removed."
    break
  fi
done

echo "\nStopping and removing Sentinel AI Docker Compose stacks..."

# Stop and remove Docker Compose stacks


# Sentinel AI microservices (including web)
docker compose \
  -p sentinel-services \
  --env-file deployment/.env \
  -f deployment/docker-compose.services.yml \
  down ${REMOVE_VOLUMES}

# Base services (NATS, Qdrant, Postgres)
docker compose \
  -p sentinel-db \
  --env-file deployment/.env \
  -f deployment/docker-compose.db.yml \
  down ${REMOVE_VOLUMES}

# Traefik & portainer
docker compose \
  -p sentinel-infra \
  --env-file deployment/.env \
  -f deployment/docker-compose.infra.yml \
  down ${REMOVE_VOLUMES}






echo "\nSentinel AI cluster stopped and removed."

# Optionally remove Docker networks if they are no longer in use by other containers
# Note: This will only remove networks if they are not attached to any running containers.
# If you want to force remove them, you can use 'docker network rm sentinel-frontend-network sentinel-backend-network'
# but be cautious if other applications might be using them.

# check_and_remove_network() {
#   network_name=$1
#   if docker network ls --format "{{.Name}}" | grep -q "^$network_name$"; then
#     echo "Attempting to remove Docker network: $network_name"
#     docker network rm "$network_name" || echo "Network $network_name is still in use or could not be removed."
#   fi
# }

# check_and_remove_network "sentinel-frontend-network"
# check_and_remove_network "sentinel-backend-network"