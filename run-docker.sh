#!/bin/bash

# Run Smart Agent using Docker

# Check if .env file exists and load it
if [ -f .env ]; then
    echo "Loading environment variables from .env file..."
    export $(grep -v '^#' .env | xargs)
fi

# Check if CLAUDE_API_KEY is set
if [ -z "$CLAUDE_API_KEY" ]; then
    echo "Error: CLAUDE_API_KEY is not set. Please set it in your .env file or provide it as an environment variable."
    exit 1
fi

# Run the Docker container
echo "Starting Smart Agent Docker container..."
docker run --rm -it \
    --network host \
    -e CLAUDE_API_KEY="$CLAUDE_API_KEY" \
    -e CLAUDE_BASE_URL="${CLAUDE_BASE_URL:-http://0.0.0.0:4000}" \
    -e API_PROVIDER="${API_PROVIDER:-proxy}" \
    -e AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-}" \
    -e AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-}" \
    -e AWS_REGION="${AWS_REGION:-us-west-2}" \
    -e LANGFUSE_PUBLIC_KEY="${LANGFUSE_PUBLIC_KEY:-}" \
    -e LANGFUSE_SECRET_KEY="${LANGFUSE_SECRET_KEY:-}" \
    -e LANGFUSE_HOST="${LANGFUSE_HOST:-https://cloud.langfuse.com}" \
    -e MCP_THINK_TOOL_REPO="${MCP_THINK_TOOL_REPO:-git+https://github.com/ddkang1/mcp-think-tool}" \
    -e MCP_SEARCH_TOOL_REPO="${MCP_SEARCH_TOOL_REPO:-git+https://github.com/ddkang1/ddg-mcp}" \
    -e MCP_PYTHON_TOOL_URL="${MCP_PYTHON_TOOL_URL:-http://localhost:8000/sse}" \
    ghcr.io/ddkang1/smart-agent:latest "$@"
