# Smart Agent

A powerful AI agent chatbot that leverages external tools to augment its intelligence rather than being constrained by built-in capabilities, enabling more accurate, verifiable, and adaptable problem-solving capabilities for practical AI application development.

## Features

- **Unified API Access**: Uses AsyncOpenAI client making it API provider agnostic
- **Integrated Tools**: Python REPL, browser automation, and more
- **Configuration-Driven**: Simple YAML configuration for all settings
- **LiteLLM Support**: Easily connect to Claude, GPT, and other models
- **CLI Interface**: Intuitive commands for all operations

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

## Model Context Protocol (MCP) Integration

Smart Agent is an AI assistant that integrates with the Model Context Protocol (MCP) to provide a unified interface for AI-powered tools and services.

### Key Features

- **Unified Tool Architecture**: All tools follow the Model Context Protocol for consistent integration
- **Flexible Deployment Options**: Run locally or connect to remote tools
- **Secure Tool Execution**: Docker isolation for tools that require it
- **Standardized Communication**: Server-Sent Events (SSE) for all tool interactions

### How Smart Agent Uses MCP

Smart Agent implements the MCP client-server architecture:

1. **Smart Agent (MCP Client)**: Acts as the client that connects to various tool servers
2. **Tool Servers (MCP Servers)**: Each tool exposes capabilities through the standardized protocol
3. **Supergateway**: Converts stdio-based tools to SSE endpoints following the MCP specification

This architecture allows Smart Agent to:
- Dynamically discover and use tools through the `tools/list` endpoint
- Invoke tool actions via the `tools/call` endpoint
- Maintain a consistent interface regardless of whether tools are local or remote

## Prerequisites

- Python 3.9+
- Node.js and npm (required for running tools via supergateway)
- Docker (for running LiteLLM proxy and container-based tools)
- Git (for installation from source)
- API keys for language models

## Installation

### Setting Up a Virtual Environment (Recommended)

It's best practice to use a virtual environment for Python projects:

```bash
# Create a virtual environment
python -m venv venv

# Activate the virtual environment
# On macOS/Linux:
source venv/bin/activate
# On Windows:
# venv\Scripts\activate

# Ensure pip is up to date
pip install --upgrade pip
```

### Installing Smart Agent

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

Smart Agent provides multiple ways to use the tool based on your needs:

### Quick Start (Single Session)

For development or quick testing, run Smart Agent with tools managed automatically:

```bash
# Run the interactive setup wizard
smart-agent setup --quick  # Setup (default is all options)

### After Quick Setup: Configure Your YAML Files

Quick setup just copies example files to your config directory. You'll need to edit these files manually to configure your environment:

1. **Edit `config/config.yaml`**:
2. **Edit `config/tools.yaml`**:
3. **Edit `config/litellm_config.yaml`**:

# Start required services (this must be done before chatting)
smart-agent start# Start all required services (both tools and proxy)

# Start chat session
smart-agent chat
```

Services must be explicitly started before chatting. The Smart Agent follows a 3-step procedure:
1. **Setup**: Configure your environment
2. **Start**: Launch the required services
3. **Chat**: Begin your conversation with the agent

### Development Mode (Persistent Services)

For development when you need tools to stay running between chat sessions:

```bash
# Terminal 1: First setup your configuration
smart-agent setup [--all|--quick|--config|--tools|--litellm]  # Setup (default is all options)

# Then launch tools and proxy services that keep running
smart-agent start [--all|--tools|--proxy]  # Use --tools or --proxy to start specific services

# Terminal 2: Start chat client that connects to running tools
smart-agent chat

# To stop or restart services
smart-agent stop           # Stop all services
smart-agent restart        # Restart all services
```

This approach is useful for development when you want to keep tools running between chat sessions.

### Production Mode (Remote Tool Services)

Connect to remote tool services running elsewhere (e.g., in production):

```bash
# Create configuration through the interactive wizard
smart-agent setup --quick  # Setup (default is all options)

# Edit config/tools.yaml to use remote URLs
# Example: url: "https://production-server.example.com/tool-name/sse"

# Start chat client - will automatically detect remote tools
smart-agent chat
```

In this mode, your `tools.yaml` contains URLs to remote tool services instead of localhost.

### Tool Management

Smart Agent provides a simple way to manage tools through YAML configuration:

```yaml
# Example tools.yaml configuration
mcp_think_tool:
  enabled: true
  url: "http://localhost:8000/sse"
  command: "uvx --from git+https://github.com/ddkang1/mcp-think-tool mcp-think-tool"

ddg_mcp:
  enabled: true
  url: "http://localhost:8001/sse"
  command: "uvx --from git+https://github.com/ddkang1/ddg-mcp ddg-mcp"

# Docker container-based tool example
python_repl:
  enabled: true
  url: "http://localhost:8002/sse"
  command: "docker run -i --rm --pull=always -v ./data:/mnt/data/ ghcr.io/ddkang1/mcp-py-repl:latest"

# Remote tool example
remote_tool:
  enabled: true
  url: "https://api.remote-tool.com/sse"
```

All tool management is done through the configuration files in the `config` directory:

1. **Enable/Disable Tools**: Set `enabled: true` or `enabled: false` in your `tools.yaml` file
2. **Configure URLs**: Set the appropriate URLs for each tool in `tools.yaml`
3. **Tool Commands**: Specify the exact installation command for each tool

No command-line flags are needed - simply edit your configuration files and run the commands.

## Configuration

Smart Agent uses YAML configuration files located in the `config` directory:

- `config.yaml` - Main configuration file
- `tools.yaml` - Tool configuration
- `litellm_config.yaml` - LLM provider configuration

The configuration system has been refactored to eliminate duplication between files. The main config now references the LiteLLM config file for model definitions, creating a single source of truth.

### Configuration Structure

The main configuration file (`config/config.yaml`) has the following structure:

```yaml
# API Configuration
api:
  provider: "proxy"  # Options: anthropic, bedrock, proxy
  base_url: "http://0.0.0.0:4000"

# Model Configuration
model:
  name: "claude-3-7-sonnet-20240229"
  temperature: 0.0

# Logging Configuration
logging:
  level: "INFO"
  file: null  # Set to a path to log to a file

# Monitoring Configuration
monitoring:
  langfuse:
    enabled: false
    host: "https://cloud.langfuse.com"

# Include tools configuration
tools_config: "config/tools.yaml"
```

### Tool Configuration

Tools are configured in `config/tools.yaml` with the following structure:

```yaml
# Example tools.yaml configuration
tools:
  mcp_think_tool:
    enabled: true
    url: "http://localhost:8000/sse"
    command: "uvx --from git+https://github.com/ddkang1/mcp-think-tool mcp-think-tool"

  ddg_mcp:
    enabled: true
    url: "http://localhost:8001/sse"
    command: "uvx --from git+https://github.com/example/tool example-tool"

  # Docker container-based tool example
  python_repl:
    enabled: true
    url: "http://localhost:8002/sse"
    command: "docker run -i --rm --pull=always -v ./data:/mnt/data/ ghcr.io/ddkang1/mcp-py-repl:latest"

  # Remote tool example
  remote_tool:
    enabled: true
    url: "https://api.remote-tool.com/sse"
```

#### Tool Configuration Schema

Each tool in the YAML configuration can have the following properties:

| Property | Description | Required |
|----------|-------------|----------|
| `enabled` | Whether the tool is enabled by default | Yes |
| `url` | URL for the tool's endpoint | Yes |
| `command` | Installation command for the tool | Yes |
| `name` | Human-readable name | No (defaults to tool ID) |
| `port` | Specific port to use | No (extracted from URL if not specified) |
| `env_prefix` | Environment variable prefix | No (defaults to SMART_AGENT_TOOL_{TOOL_ID_UPPERCASE}) |

#### Tool Types

Smart Agent supports two types of tools:
- **Remote SSE Tools**: Tools that are already running and accessible via a remote URL
- **Local stdio Tools**: Tools that need to be launched locally and converted to SSE

For local stdio tools, Smart Agent uses [supergateway](https://github.com/supercorp-ai/supergateway) to automatically convert them to SSE. This approach allows for seamless integration with various MCP tools without requiring them to natively support SSE.

The `command` field specifies the exact installation command for the tool. Smart Agent will automatically add port parameters to this command:
- For Docker commands: `docker run -i --rm --pull=always -v ./data:/mnt/data/ ghcr.io/ddkang1/mcp-py-repl:latest`
- For UVX commands: `uvx --from git+https://github.com/ddkang1/mcp-think-tool mcp-think-tool`
- For NPX commands: `npx my-tool`

All local tools are treated as stdio tools and converted to SSE using supergateway, regardless of their type setting in the configuration.

## Configuration Management

Smart Agent uses YAML configuration files to manage settings and tools. The configuration is split into two main files:

1. **config.yaml** - Contains API settings, model configurations, and logging options
2. **tools.yaml** - Contains tool-specific settings including URLs and storage paths

The Smart Agent CLI provides commands to help manage these configuration files:

```bash
# Run the setup wizard to create configuration files
smart-agent setup [--all|--quick|--config|--tools|--litellm]  # Setup (default is all options)
```

The setup wizard will guide you through creating configuration files based on examples.

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

# Run the setup wizard to create configuration files
smart-agent setup [--all|--quick|--config|--tools|--litellm]  # Setup (default is all options)
```

### Running Tests

```bash
pytest
```

## License

MIT

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
