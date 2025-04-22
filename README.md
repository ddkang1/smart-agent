# Smart Agent

A powerful AI agent chatbot that leverages external tools to augment its intelligence rather than being constrained by built-in capabilities, enabling more accurate, verifiable, and adaptable problem-solving capabilities for practical AI application development.

## Features

- **Unified API Access**: Uses AsyncOpenAI client making it API provider agnostic
- **Integrated Tools**: Python REPL, browser automation, and more
- **Configuration-Driven**: Simple YAML configuration for all settings
- **LiteLLM Support**: Easily connect to Claude, GPT, and other models
- **CLI Interface**: Intuitive commands for all operations
- **Web UI**: Chainlit-based web interface for easy interaction

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

Smart Agent follows a client-server architecture with a clear separation between server components (tools, LLM proxy) and client interfaces (chat, web UIs).

### Setup and Configuration

Before using Smart Agent, you need to set up your configuration:

```bash
# Run the interactive setup wizard
smart-agent setup --quick  # Setup (default is all options)
```

After setup, you'll need to edit these files manually to configure your environment:
1. **Edit `config/config.yaml`**: Main configuration including API settings
2. **Edit `config/tools.yaml`**: Tool configuration
3. **Edit `config/litellm_config.yaml`**: LLM provider configuration

### Server Components

The server components must be started before using any client interfaces:

```bash
# Start all required services (both tools and proxy)
smart-agent start

# Check status of running services
smart-agent status

# Stop all services
smart-agent stop
```

### Client Interfaces

Once the server components are running, you can use any of the client interfaces:

#### CLI Chat Interface

```bash
# Start the command-line chat interface
smart-agent chat
```

#### Chainlit Web Interface

```bash
# Install Chainlit
pip install chainlit

# Start the Chainlit web interface
smart-agent chainlit --port 8000 --host 127.0.0.1
```

### Usage Patterns

#### Quick Start (Single Session)

For development or quick testing:

```bash
# 1. Setup
smart-agent setup --quick

# 2. Start server components
smart-agent start

# 3. Start client interface
smart-agent chat  # or chainlit
```

#### Development Mode (Persistent Services)

For development when you need tools to stay running between chat sessions:

```bash
# Terminal 1: Start server components
smart-agent start [--all|--tools|--proxy]  # Use --tools or --proxy to start specific services

# Terminal 2: Use client interfaces as needed
smart-agent chat  # or chainlit
```

#### Production Mode (Remote Tool Services)

Connect to remote tool services running elsewhere:

```bash
# Edit config/tools.yaml to use remote URLs
# Example: url: "https://production-server.example.com/tool-name/sse"

# Start client interface - will automatically connect to remote tools
smart-agent chat  # or chainlit
```

### Smart Agent Architecture

Smart Agent follows a client-server architecture:

#### Server Part

The server components manage the tools, LLM proxy, and other background services:

```bash
# Start all services (tools and proxy)
smart-agent start

# Check status of running services
smart-agent status

# Stop all services
smart-agent stop
```

#### Client Part

The client components connect to the running services and provide different interfaces:

1. **CLI Chat Interface**:
   ```bash
   # Start the command-line chat interface
   smart-agent chat
   ```

2. **Chainlit Web Interface**:
   ```bash
   # Install Chainlit
   pip install chainlit
   
   # Start the Chainlit web interface
   smart-agent chainlit --port 8000 --host 127.0.0.1
   ```

Each client interface provides the same core functionality but with different user experiences. The Chainlit interface automatically initializes using the provided config and tools paths, providing a graphical alternative to the CLI chat client.

### Tool Management

Smart Agent provides a simple way to manage tools through YAML configuration:

```yaml
# Example tools.yaml configuration
tools:
  mcp_think_tool:
    enabled: true
    url: "http://localhost:8000/sse"
    command: "uvx mcp-think --sse --host 0.0.0.0"
    transport: stdio_to_sse

  ddg_mcp:
    enabled: true
    url: "http://localhost:8001/sse"
    command: "uvx --from git+https://github.com/ddkang1/ddg-mcp ddg-mcp"
    transport: stdio_to_sse

  # Docker container-based tool example
  python_repl:
    enabled: true
    url: "http://localhost:8002/sse"
    command: "docker run -i --rm --pull=always -v ./data:/mnt/data/ ghcr.io/ddkang1/mcp-py-repl:latest"
    transport: stdio_to_sse

  # Remote tool example
  remote_tool:
    enabled: true
    url: "https://api.remote-tool.com/sse"
    transport: sse
```

Each tool in the configuration can have the following properties:

| Property | Description | Required |
|----------|-------------|----------|
| `enabled` | Whether the tool is enabled | Yes |
| `transport` | Transport type: `stdio`, `sse`, `stdio_to_sse`, or `sse_to_stdio` | Yes |
| `url` | URL for the tool's endpoint | For `sse`, `stdio_to_sse`, and `sse_to_stdio` |
| `command` | Installation command for the tool | For `stdio` and `stdio_to_sse` |

All tool management is done through the configuration files in the `config` directory:

1. **Enable/Disable Tools**: Set `enabled: true` or `enabled: false` in your `tools.yaml` file
2. **Configure Transport**: Set the appropriate transport type for each tool
3. **Configure URLs**: Set the appropriate URLs for each tool in `tools.yaml`
4. **Tool Commands**: Specify the exact installation command for each tool

No command-line flags are needed - simply edit your configuration files and run the commands.

## Configuration

Smart Agent uses YAML configuration files located in the `config` directory:

- `config.yaml` - Main configuration file
- `tools.yaml` - Tool configuration
- `litellm_config.yaml` - LLM provider configuration

The configuration system has been refactored to eliminate duplication between files. The main config now references the LiteLLM config file for model definitions, creating a single source of truth.

### LiteLLM Proxy

Smart Agent can automatically launch a local LiteLLM proxy when needed. This happens when:

1. The `base_url` in your configuration contains `localhost`, `127.0.0.1`, or `0.0.0.0`
2. The LiteLLM configuration is explicitly enabled with `enabled: true`

The LiteLLM proxy is configured in `config/litellm_config.yaml` and allows you to:

- Use multiple LLM providers through a single API
- Route requests to different models based on your needs
- Add authentication, rate limiting, and other features

By default, the LiteLLM proxy binds to `0.0.0.0:4000`, allowing connections from any IP address.

### Configuration Structure

The main configuration file (`config/config.yaml`) has the following structure:

```yaml
# API Configuration
api:
  provider: "proxy"  # Options: anthropic, bedrock, proxy
  # Using localhost, 127.0.0.1, or 0.0.0.0 in base_url will automatically start a local LiteLLM proxy
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
    command: "uvx mcp-think --sse --host 0.0.0.0"
    transport: stdio_to_sse

  ddg_mcp:
    enabled: true
    url: "http://localhost:8001/sse"
    command: "uvx --from git+https://github.com/ddkang1/ddg-mcp ddg-mcp"
    transport: stdio_to_sse

  # Docker container-based tool example
  python_repl:
    enabled: true
    url: "http://localhost:8002/sse"
    command: "docker run -i --rm --pull=always -v ./data:/mnt/data/ ghcr.io/ddkang1/mcp-py-repl:latest"
    transport: stdio_to_sse

  # Remote tool example
  remote_tool:
    enabled: true
    url: "https://api.remote-tool.com/sse"
    transport: sse
```

#### Tool Configuration Schema

Each tool in the YAML configuration can have the following properties:

| Property | Description | Required |
|----------|-------------|----------|
| `enabled` | Whether the tool is enabled | Yes |
| `transport` | Transport type: `stdio`, `sse`, `stdio_to_sse`, or `sse_to_stdio` | Yes |
| `url` | URL for the tool's endpoint | For `sse`, `stdio_to_sse`, and `sse_to_stdio` |
| `command` | Installation command for the tool | For `stdio` and `stdio_to_sse` |

#### Tool Architecture: Server and Client Parts

Tools in Smart Agent follow a server-client architecture:

1. **Server Part**: The actual tool implementation that runs as a service
   - Requires a `command` to launch the tool server (for local tools)
   - Runs independently and exposes an API endpoint
   - Can be local or remote

2. **Client Part**: The Smart Agent's connection to the tool
   - Requires a `url` to connect to the tool server
   - Does not need a `command` when connecting to remote tools
   - Uses the specified `transport` type to communicate

#### Transport Types

Smart Agent supports four transport types:

- **stdio**: Direct stdio communication (no supergateway, no port/URL needed)
- **sse**: Remote SSE tools (no local launching needed, client-only)
- **stdio_to_sse**: Convert stdio to SSE using supergateway (server + client)
- **sse_to_stdio**: Convert SSE to stdio using supergateway (client-only)

For `stdio_to_sse` transport, Smart Agent uses [supergateway](https://github.com/supercorp-ai/supergateway) to automatically convert stdio tools to SSE. This approach allows for seamless integration with various MCP tools without requiring them to natively support SSE.

The `command` field is only required for server-side tools that need to be launched locally. Examples include:
- For Docker commands: `docker run -i --rm --pull=always -v ./data:/mnt/data/ ghcr.io/ddkang1/mcp-py-repl:latest`
- For UVX commands: `uvx mcp-think --sse --host 0.0.0.0`
- For NPX commands: `npx my-tool`

For client-only tools (like remote SSE tools with `transport: sse`), no `command` is needed as the tool server is already running elsewhere.

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
