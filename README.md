# Smart Agent

A powerful AI agent chatbot that leverages external tools to augment its intelligence rather than being constrained by built-in capabilities, enabling more accurate, verifiable, and adaptable problem-solving capabilities for practical application development.

## Overview

Smart Agent represents a breakthrough in AI agent capabilities by combining three key technologies:

1. **Claude 3.7 Sonnet with Think Tool**: The core innovation is the discovery that Claude 3.7 Sonnet's "Think" Tool unlocks powerful reasoning capabilities even without explicit thinking mode. This tool grounds the agent's reasoning process, enabling it to effectively use external tools - a capability that pure reasoning models typically struggle with.

2. **Model Context Protocol (MCP)**: Acting as a standardized "USB-C for tools," MCP provides a consistent interface for integrating and managing external tools. This standardization makes it straightforward to extend the agent's capabilities through new tools.

3. **OpenAI Agents Framework**: This robust framework orchestrates the agent's interactions, managing the flow between reasoning and tool use to create a seamless experience.

The combination of these technologies creates an agent that can reason effectively while using tools to extend its capabilities beyond what's possible with traditional language models alone.

## Key Features

- **Grounded Reasoning**: The Think Tool enables the agent to pause, reflect, and ground its reasoning process
- **Tool Augmentation**: Extends capabilities through external tools rather than being limited to built-in knowledge
- **Standardized Tool Integration**: MCP provides a consistent interface for adding new tools
- **Verifiable Problem-Solving**: Tools provide factual grounding that makes solutions more accurate and verifiable
- **Adaptable Intelligence**: Easily extend capabilities by adding new tools without retraining the model

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
1. Create a `data` directory for the tool
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

3. Create a data directory for the tool:
   ```bash
   mkdir -p python_repl_storage
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

### Running the Required Tool Services

Before running Smart Agent, you need to start the MCP tool services which are required for the agent to function properly:

```bash
# Start the MCP tool services in a terminal
./launch-tools.sh

# This will keep running in the terminal
# Leave this terminal open and use a new terminal for the next steps
```

The tool services need to stay running while you use Smart Agent. You can stop them with Ctrl+C when you're done.

#### Tool Service Options

The launch-tools.sh script supports several options:

```bash
# Customize the Python REPL data directory
./launch-tools.sh --python-repl-data=my_python_data

# Customize the Python REPL port
./launch-tools.sh --python-repl-port=8888

# Disable launching the Python REPL service
./launch-tools.sh --no-python-repl
```

### Command Line Interface

Once the tool services are running, open a new terminal and run:

```bash
# Run the Smart Agent CLI
smart-agent chat

# Run with custom API key
smart-agent chat --api-key your_api_key

# Run with custom base URL
smart-agent chat --api-base-url https://custom-api-url.com
```

### Using Docker

If you don't want to install the package locally, you can use the Docker image. Note that you still need to run the tool services first:

```bash
# First terminal: Start the tool services
./launch-tools.sh

# Second terminal: Run Smart Agent using Docker with environment variables from .env file
docker run --rm -it --env-file .env --network host ghcr.io/ddkang1/smart-agent:latest

# Run with custom API key
docker run --rm -it -e CLAUDE_API_KEY=your_api_key --network host ghcr.io/ddkang1/smart-agent:latest

# Run with custom command
docker run --rm -it -e CLAUDE_API_KEY=your_api_key --network host ghcr.io/ddkang1/smart-agent:latest chat --langfuse-host https://custom-langfuse.com
```

The `--network host` flag is important as it allows the Docker container to connect to the tool services running on your host machine.

### Using the Convenience Script

A convenience script is provided to make it easier to run the Docker image:

```bash
# First terminal: Start the tool services
./launch-tools.sh

# Second terminal: Run the script (will use .env file if it exists)
./run-docker.sh

# Pass additional arguments to the smart-agent command
./run-docker.sh chat --langfuse-host https://custom-langfuse.com
```

### Using Docker Compose (All-in-One Solution)

For a complete setup including both the Smart Agent and all required tool services, you can use Docker Compose:

```bash
# Start all services
docker-compose up

# Run in detached mode
docker-compose up -d

# Stop all services
docker-compose down
```

Docker Compose is the simplest option as it handles starting all services for you, but it will restart the tool services each time you run it.

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
