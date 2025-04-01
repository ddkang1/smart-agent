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

## Installation and Usage

### Option 1: Using Docker Compose (Easiest)

The simplest way to run Smart Agent is using Docker Compose, which will automatically set up all the necessary tool services:

```bash
# Clone the repository
git clone https://github.com/ddkang1/smart-agent.git
cd smart-agent

# Create a .env file with your API keys (see .env.example)
cp .env.example .env
# Edit the .env file with your API keys

# Start Smart Agent and all tool services
docker-compose up
```

### Option 2: Using Docker with Separate Tool Services

If you prefer more control over the tool services:

```bash
# First terminal: Start the tool services
smart-agent launch-tools

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

# Start the tool services and launch the chat in one command
smart-agent chat --launch-tools

# Or start tools and chat separately
# First terminal: Start the tool services
smart-agent launch-tools

# Second terminal: Start the chat
smart-agent chat
```

### Option 4: Clone Repository (For Development)

For development or contributing to the project:

```bash
# Clone the repository
git clone https://github.com/ddkang1/smart-agent.git
cd smart-agent

# Install the package in development mode
pip install -e .

# Start the tool services and launch the chat in one command
smart-agent chat --launch-tools

# Or start tools and chat separately
# First terminal: Start the tool services
smart-agent launch-tools

# Second terminal: Start the chat
smart-agent chat
```

### Tool Management

Smart Agent provides two ways to launch and manage the required tool services:

#### Using the CLI (Recommended)

The Smart Agent CLI includes commands to manage tool services directly:

```bash
# Launch all tool services and keep them running
smart-agent launch-tools

# Launch tools with custom configuration
smart-agent launch-tools --tools-config /path/to/tools.yaml

# Disable specific tools
smart-agent launch-tools --no-python-repl --no-search-tool

# Start the chat and automatically launch required tools
smart-agent chat --launch-tools

# Start the chat with custom tool configuration
smart-agent chat --launch-tools --tools-config /path/to/tools.yaml
```

#### Using the Launch Script

Alternatively, you can use the provided shell script:

```bash
# Launch all tool services
./launch-tools.sh

# Launch with custom configuration
./launch-tools.sh --config=/path/to/tools.yaml

# Disable specific tools
./launch-tools.sh --no-python-repl --no-search-tool
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

### Tool Configuration

Smart Agent now supports YAML-based tool configuration, making it easier to manage and customize the tools used by the agent. The configuration file is located at `config/tools.yaml` by default.

```yaml
# Example tools.yaml configuration
tools:
  think_tool:
    name: "Think Tool"
    type: "sse"
    enabled: true
    env_prefix: "MCP_THINK_TOOL"
    repository: "git+https://github.com/ddkang1/mcp-think-tool"
    url: "http://localhost:8001/sse"
    description: "Enables the agent to pause, reflect, and ground its reasoning process"
```

#### Using the Tool Configuration

You can specify a custom tool configuration file when running the agent:

```bash
# Start the agent with a custom tool configuration
smart-agent chat --tools-config /path/to/your/tools.yaml

# Launch tools with a custom configuration
./launch-tools.sh --config=/path/to/your/tools.yaml
```

#### Adding New Tools

To add a new tool to Smart Agent, simply add a new entry to the `tools` section in the YAML file:

```yaml
tools:
  # Existing tools...
  
  my_custom_tool:
    name: "My Custom Tool"
    type: "sse"
    enabled: true
    env_prefix: "MCP_CUSTOM_TOOL"
    repository: "git+https://github.com/username/my-custom-tool"
    url: "http://localhost:8003/sse"
    description: "Description of what my custom tool does"
```

#### Environment Variable Override

You can override tool configuration using environment variables:

- `ENABLE_TOOL_NAME`: Enable or disable a tool (e.g., `ENABLE_THINK_TOOL=false`)
- `MCP_TOOL_NAME_REPO`: Override the tool repository (e.g., `MCP_THINK_TOOL_REPO=git+https://github.com/user/repo`)
- `MCP_TOOL_NAME_URL`: Override the tool URL (e.g., `MCP_THINK_TOOL_URL=http://localhost:9001/sse`)

The environment variables take precedence over the YAML configuration.

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
