# Smart Agent

A powerful AI agent chatbot that leverages external tools to augment its intelligence rather than being constrained by built-in capabilities, enabling more accurate, verifiable, and adaptable problem-solving capabilities for practical AI application development.

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

## Installation & Usage

### Option 1: Using Docker Compose (Easiest)

The simplest way to get started with Smart Agent is using Docker Compose, which handles all the setup for you:

```bash
# Clone the repository
git clone https://github.com/ddkang1/smart-agent.git
cd smart-agent

# Create and edit the .env file with your API keys
cp .env.example .env
nano .env  # Edit with your favorite editor

# Start all services with Docker Compose
docker-compose up

# To run in detached mode
docker-compose up -d

# To stop all services
docker-compose down
```

This approach starts both the Smart Agent and all required tool services in one command, making it the easiest option for beginners.

### Option 2: Using Docker with Separate Tool Services

If you need more control over the tool services:

```bash
# Clone the repository
git clone https://github.com/ddkang1/smart-agent.git
cd smart-agent

# Create and edit the .env file
cp .env.example .env
nano .env  # Edit with your favorite editor

# First terminal: Start the tool services
./launch-tools.sh

# Second terminal: Run Smart Agent using Docker with environment variables from .env file
docker run --rm -it --env-file .env --network host ghcr.io/ddkang1/smart-agent:latest

# Run with custom API key
docker run --rm -it -e CLAUDE_API_KEY=your_api_key --network host ghcr.io/ddkang1/smart-agent:latest
```

The `--network host` flag is important as it allows the Docker container to connect to the tool services running on your host machine.

A convenience script is also provided to make it easier to run the Docker image:

```bash
# After starting the tool services in another terminal
./run-docker.sh

# Pass additional arguments to the smart-agent command
./run-docker.sh chat --langfuse-host https://custom-langfuse.com
```

### Option 3: Install from PyPI

For more customization, you can install the package from PyPI:

```bash
# Install the package
pip install smart-agent

# Create a directory for your project
mkdir my-smart-agent
cd my-smart-agent

# Download the example environment file and launch script
curl -O https://raw.githubusercontent.com/ddkang1/smart-agent/main/.env.example
curl -O https://raw.githubusercontent.com/ddkang1/smart-agent/main/launch-tools.sh

# Rename and edit the environment file
mv .env.example .env
nano .env  # Edit with your favorite editor

# Make the launch script executable
chmod +x launch-tools.sh

# Create a directory for Python REPL storage
mkdir -p python_repl_storage

# First terminal: Start the tool services
./launch-tools.sh

# Second terminal: Run the Smart Agent CLI
smart-agent chat

# Run with custom options
smart-agent chat --api-key your_api_key
smart-agent chat --api-base-url https://custom-api-url.com
```

### Option 4: Clone the Repository (Development)

For development or full customization:

```bash
# Clone the repository
git clone https://github.com/ddkang1/smart-agent.git
cd smart-agent

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install the package in development mode
pip install -e .

# Create and edit the .env file
cp .env.example .env
nano .env  # Edit with your favorite editor

# First terminal: Start the tool services
./launch-tools.sh

# Second terminal: Run the Smart Agent CLI
smart-agent chat
```

## Environment Configuration

Smart Agent uses environment variables for configuration. These can be set in a `.env` file or passed directly to the CLI.

### Required Variables

- `CLAUDE_API_KEY`: Your Claude API key

### Optional Variables

- `MODEL_NAME`: The model name to use (default: `claude-3-7-sonnet-20250219`)
- `CLAUDE_BASE_URL`: Base URL for the Claude API (default: `http://0.0.0.0:4000` for proxy mode)
- `API_PROVIDER`: API provider to use (options: `anthropic`, `bedrock`, `proxy`, default: `proxy`)

### AWS Bedrock Configuration (if using bedrock provider)

- `AWS_ACCESS_KEY_ID`: Your AWS access key
- `AWS_SECRET_ACCESS_KEY`: Your AWS secret key
- `AWS_REGION`: AWS region (default: `us-west-2`)

### Langfuse Configuration (optional)

- `LANGFUSE_PUBLIC_KEY`: Your Langfuse public key
- `LANGFUSE_SECRET_KEY`: Your Langfuse secret key
- `LANGFUSE_HOST`: Langfuse host (default: `https://cloud.langfuse.com`)

### MCP Tool Configuration

#### Tool Repositories
- `MCP_THINK_TOOL_REPO`: Repository for the Think tool (default: `git+https://github.com/ddkang1/mcp-think-tool`)
- `MCP_SEARCH_TOOL_REPO`: Repository for the Search tool (default: `git+https://github.com/ddkang1/ddg-mcp`)
- `MCP_PYTHON_TOOL_REPO`: Repository/image for the Python REPL tool (default: `ghcr.io/ddkang1/mcp-py-repl:latest`)

#### Tool URLs
- `MCP_THINK_TOOL_URL`: URL for the Think tool SSE endpoint (default: `http://localhost:8001/sse`)
- `MCP_SEARCH_TOOL_URL`: URL for the Search tool SSE endpoint (default: `http://localhost:8002/sse`)
- `MCP_PYTHON_TOOL_URL`: URL for the Python REPL tool SSE endpoint (default: `http://localhost:8000/sse`)

#### Tool Enable Flags
- `ENABLE_THINK_TOOL`: Enable the Think tool (default: `true`)
- `ENABLE_SEARCH_TOOL`: Enable the Search tool (default: `true`)
- `ENABLE_PYTHON_TOOL`: Enable the Python REPL tool (default: `true`)

## Advanced Configuration

### Tool Service Options

When using the `launch-tools.sh` script, you can customize the tool services with these options:

```bash
# Python REPL Tool options
./launch-tools.sh --python-repl-data=my_python_data
./launch-tools.sh --python-repl-port=8888
./launch-tools.sh --no-python-repl

# Think Tool options
./launch-tools.sh --think-tool-port=8001
./launch-tools.sh --think-tool-repo=git+https://github.com/custom/think-tool
./launch-tools.sh --no-think-tool

# Search Tool options
./launch-tools.sh --search-tool-port=8002
./launch-tools.sh --search-tool-repo=git+https://github.com/custom/search-tool
./launch-tools.sh --no-search-tool

# Combine options as needed
./launch-tools.sh --python-repl-port=8888 --think-tool-port=8889 --search-tool-port=8890
```

## Development

### Setup Development Environment

If you want to contribute to Smart Agent or modify it for your own needs:

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
