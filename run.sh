#!/bin/bash

# Run Smart Agent

# Create the required directories if they don't exist
mkdir -p config
mkdir -p python_repl_storage

# Check if example files exist and create configs if needed
./setup-env.sh

# Check if we need to run the local LiteLLM proxy
BASE_URL=$(grep "base_url:" config/config.yaml | awk '{print $2}' | tr -d '"'"'" )

# Run the services using Docker Compose
echo "Starting Smart Agent services..."

# Only include LiteLLM proxy if using a local URL
if [[ "$BASE_URL" == *"localhost"* ]] || [[ "$BASE_URL" == *"127.0.0.1"* ]] || [[ "$BASE_URL" == *"0.0.0.0"* ]] || [[ "$BASE_URL" == *"litellm-proxy"* ]]; then
    echo "Using local LiteLLM proxy at $BASE_URL"
    docker-compose --profile litellm up
else
    echo "Using remote API at $BASE_URL, skipping local LiteLLM proxy"
    docker-compose up
fi
