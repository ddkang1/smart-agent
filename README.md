# Smart Agent

A powerful AI agent framework with reasoning and tool use capabilities.

## Overview

Smart Agent is built on top of Claude 3.7 Sonnet and integrates with the "Think" Tool and Model Context Protocol (MCP) on top of the OpenAI Agents Framework. The goal is to create intelligent agents capable of handling tools with reasoning.

## Key Features

- **Enhanced Reasoning**: Optimized for tool use to ground the thinking process
- **Extensible Architecture**: Built on OpenAI Agents Framework
- **MCP Integration**: Leverages Model Context Protocol for advanced capabilities
- **Think Tool**: Enables deliberate reflection for better decision making
- **CLI Interface**: Easy to use command-line interface

## Installation

```bash
pip install smart-agent
```

## Getting Started

### Quick Setup

The easiest way to get started is to use the provided setup script:

```bash
# Make the script executable
chmod +x setup-env.sh

# Run the setup script
./setup-env.sh
```

This script will:
1. Create a `data` directory for the Python tool
2. Create a `.env` file from the example template
3. Prompt you for your OpenAI API key
4. Guide you on how to run the agent

### Manual Setup

If you prefer to set up manually:

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```

2. Edit the `.env` file with your API keys and configuration

3. Create a data directory for the Python tool:
   ```bash
   mkdir -p data
   ```

## Environment Configuration

Smart Agent uses environment variables for configuration. You can set these in several ways:

1. Create a `.env` file in your project directory (recommended for development)
2. Set environment variables directly in your shell
3. Pass them as command-line arguments

### Using .env File

Copy the example environment file and modify it with your credentials:

```bash
cp .env.example .env
```

Then edit the `.env` file with your API keys and configuration:

```
# OpenAI API Configuration
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_BASE_URL=https://api.openai.com/v1

# Langfuse Configuration (optional)
LANGFUSE_PUBLIC_KEY=your_langfuse_public_key_here
LANGFUSE_SECRET_KEY=your_langfuse_secret_key_here
LANGFUSE_HOST=https://cloud.langfuse.com

# MCP Tool Configuration
MCP_THINK_TOOL_REPO=git+https://github.com/ddkang1/mcp-think-tool
MCP_SEARCH_TOOL_REPO=git+https://github.com/ddkang1/ddg-mcp
MCP_PYTHON_TOOL_URL=http://localhost:8000/sse
```

## Usage

### Command Line Interface

```bash
# Run the Smart Agent CLI
smart-agent chat

# Run with custom API key
smart-agent chat --api-key your_api_key

# Run with custom base URL
smart-agent chat --api-base-url https://custom-api-url.com
```

### Using Docker

If you don't want to install the package locally, you can use the Docker image:

```bash
# Run using Docker with environment variables from .env file
docker run --rm -it --env-file .env ghcr.io/ddkang1/smart-agent:latest

# Run with custom API key
docker run --rm -it -e OPENAI_API_KEY=your_api_key ghcr.io/ddkang1/smart-agent:latest

# Run with custom command
docker run --rm -it -e OPENAI_API_KEY=your_api_key ghcr.io/ddkang1/smart-agent:latest chat --langfuse-host https://custom-langfuse.com
```

### Using the Convenience Script

A convenience script is provided to make it easier to run the Docker image:

```bash
# Make the script executable (first time only)
chmod +x run-docker.sh

# Run the script (will use .env file if it exists)
./run-docker.sh

# Pass additional arguments to the smart-agent command
./run-docker.sh chat --langfuse-host https://custom-langfuse.com
```

### Using Docker Compose

For a complete setup including the Python tool service, you can use Docker Compose:

```bash
# Start all services
docker-compose up

# Run in detached mode
docker-compose up -d

# Stop all services
docker-compose down
```

Make sure to create a `data` directory in your project root for the Python tool to store files:

```bash
mkdir -p data
```

## Development

### Setup Development Environment

```bash
# Clone the repository
git clone https://github.com/ddkang1/smart-agent.git
cd smart-agent

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install development dependencies
pip install -e ".[dev]"
```

### Running Tests

```bash
pytest
```

## License

MIT

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
