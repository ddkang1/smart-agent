# Smart Agent

A powerful AI agent chatbot that leverages external tools to augment its intelligence rather than being constrained by built-in capabilities, enabling more accurate, verifiable, and adaptable problem-solving capabilities for practical AI application development.

## Overview

Smart Agent represents a breakthrough in AI agent capabilities by combining three key technologies:

1. **Claude 3.7 Sonnet with Think Tool**: The core innovation is the discovery that Claude 3.7 Sonnet's "Think" Tool unlocks powerful reasoning capabilities even without explicit thinking mode. This tool grounds the agent's reasoning process, enabling it to effectively use external tools - a capability that pure reasoning models typically struggle with.

2. **OpenAI Agents Framework**: This robust framework orchestrates the agent's interactions, managing the flow between reasoning and tool use to create a seamless experience.

The combination of these technologies creates an agent that can reason effectively while using tools to extend its capabilities beyond what's possible with traditional language models alone.

## Key Features

- **Grounded Reasoning**: The Think Tool enables the agent to pause, reflect, and ground its reasoning process
- **Tool Augmentation**: Extends capabilities through external tools rather than being limited to built-in knowledge
- **Verifiable Problem-Solving**: Tools provide factual grounding that makes solutions more accurate and verifiable
- **Adaptable Intelligence**: Easily extend capabilities by adding new tools without retraining the model

## Installation

```bash
# Install from PyPI
pip install smart-agent

# Install with monitoring support
pip install smart-agent[monitoring]

# Install from source
git clone https://github.com/ddkang1/smart-agent.git
cd smart-agent
pip install -e .
```

## Usage

### Basic Usage

```bash
# Start a chat with the Smart Agent
smart-agent chat

# Start with a specific OpenAI model
smart-agent chat --model gpt-4
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

# Disable all tools
smart-agent launch-tools --disable-tools

# Start the chat and automatically launch required tools
smart-agent chat --launch-tools

# Start the chat with custom tool configuration
smart-agent chat --launch-tools --tools-config /path/to/tools.yaml

# Start the chat with tools disabled
smart-agent chat --disable-tools
```

#### Using the Launch Script

Alternatively, you can use the provided shell script:

```bash
# Launch all tool services
./launch-tools.sh

# Launch with custom configuration
./launch-tools.sh --config=/path/to/tools.yaml
```

## Environment Configuration

Smart Agent uses environment variables for configuration. These can be set in a `.env` file or passed directly to the CLI.

### API Keys

- `CLAUDE_API_KEY`: Your Anthropic Claude API key
- `OPENAI_API_KEY`: Your OpenAI API key (required for OpenAI models)

### Model Configuration

- `SMART_AGENT_MODEL`: Default model to use (default: `claude-3-7-sonnet-20240229`)
- `SMART_AGENT_TEMPERATURE`: Temperature for model generation (default: `0.0`)

### Logging and Monitoring

- `SMART_AGENT_LOG_LEVEL`: Log level (default: `INFO`)
- `SMART_AGENT_LOG_FILE`: Log file path (default: None, logs to stdout)

### Langfuse Integration

- `LANGFUSE_PUBLIC_KEY`: Your Langfuse public key
- `LANGFUSE_SECRET_KEY`: Your Langfuse secret key
- `LANGFUSE_HOST`: Langfuse host (default: `https://cloud.langfuse.com`)

### Tool Configuration

Smart Agent uses a YAML-based tool configuration system. The configuration file is located at `config/tools.yaml` by default.

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
    module: "mcp_think_tool"
    server_module: "mcp_think_tool.server"
  
  # Docker container-based tool example
  python_tool:
    name: "Python REPL Tool"
    type: "sse"
    enabled: true
    env_prefix: "MCP_PYTHON_TOOL"
    repository: "ghcr.io/ddkang1/mcp-py-repl:latest"
    url: "http://localhost:8000/sse"
    description: "Allows execution of Python code in a secure environment"
    container: true
```

#### Tool Configuration Schema

Each tool in the YAML configuration can have the following properties:

| Property | Description | Required |
|----------|-------------|----------|
| `name` | Human-readable name | Yes |
| `type` | Tool type (e.g., "sse") | Yes |
| `enabled` | Whether the tool is enabled by default | Yes |
| `env_prefix` | Environment variable prefix for this tool | Yes |
| `repository` | Git repository or Docker image for the tool | Yes |
| `url` | URL for the tool's endpoint | Yes |
| `description` | Brief description of what the tool does | No |
| `module` | Python module name (for pip install and import) | For Python tools |
| `server_module` | Module to run for the server | For Python tools |
| `container` | Set to true if the tool runs in a Docker container | For container tools |

#### Environment Variable Override

You can override tool configuration using environment variables:

- `ENABLE_TOOL_NAME`: Enable or disable a tool (e.g., `ENABLE_THINK_TOOL=false`)
- `MCP_TOOL_NAME_REPO`: Override the tool repository (e.g., `MCP_THINK_TOOL_REPO=git+https://github.com/user/repo`)
- `MCP_TOOL_NAME_URL`: Override the tool URL (e.g., `MCP_THINK_TOOL_URL=http://localhost:9001/sse`)

The environment variables take precedence over the YAML configuration.

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
