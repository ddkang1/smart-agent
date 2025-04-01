#!/bin/bash

# Setup environment for Smart Agent

# Create data directory if it doesn't exist
mkdir -p python_repl_storage
echo "Created directory for Python REPL tool: python_repl_storage"

# Check if .env file already exists
if [ -f .env ]; then
    echo ".env file already exists. Do you want to overwrite it? (y/N)"
    read answer
    if [[ ! "$answer" =~ ^[Yy]$ ]]; then
        echo "Keeping existing .env file."
        exit 0
    fi
fi

# Copy example .env file
cp .env.example .env
echo "Created .env file from example template"

# Prompt for Claude API key
echo -n "Enter your Claude API key: "
read -s claude_key
echo ""

if [ -n "$claude_key" ]; then
    # Update .env file with the provided key
    sed -i '' "s|your_claude_api_key_here|$claude_key|g" .env
    echo "Updated Claude API key in .env file"
fi

echo "Environment setup complete. You can now run Smart Agent using:"
echo "  - pip install -e . && smart-agent chat  # Local installation"
echo "  - ./run-docker.sh                       # Docker"
echo "  - docker-compose up                     # Docker Compose"
