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

Smart Agent provides multiple ways to use the tool based on your needs:

### Quick Start (Single Session)

For development or quick testing, run Smart Agent with tools managed automatically:

```bash
# Install Smart Agent
pip install smart-agent

# Run the interactive setup wizard
smart-agent setup  # Walks you through configuration options

# Start chat (will automatically launch required tools)
smart-agent chat
```

The chat command will automatically launch required tools based on your configuration and clean them up when you exit.

### Development Mode (Persistent Services)

For development when you need tools to stay running between chat sessions:

```bash
# Terminal 1: First setup your configuration 
smart-agent setup               # Interactive wizard for configuration
smart-agent setup --quick       # Quick setup: copy example files without prompts
smart-agent setup --config      # Configure only config.yaml
smart-agent setup --tools       # Configure only tools.yaml
smart-agent setup --litellm     # Configure only litellm_config.yaml

# Then launch tools and proxy services that keep running
smart-agent start --all    # Use --tools or --proxy to start specific services

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
smart-agent setup  # Walks you through configuration options

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
tools:
  think_tool:
    name: "Think Tool"
    type: "sse"
    enabled: true  # Set to false to disable this tool
    url: "http://localhost:8000/sse"
    description: "Enables the agent to pause, reflect, and ground its reasoning process"
    module: "mcp_think_tool"
    server_module: "mcp_think_tool.server"
  
  search_tool:
    name: "Search Tool"
    type: "sse"
    enabled: true
    env_prefix: "SMART_AGENT_TOOL_SEARCH"
    repository: "git+https://github.com/ddkang1/ddg-mcp"
    url: "http://localhost:8001/sse"
    description: "Provides web search capabilities to find information online"
    module: "ddg_mcp"
    server_module: "ddg_mcp.server"
  
  # Docker container-based tool example
  python_tool:
    name: "Python REPL Tool"
    type: "sse"
    enabled: true
    env_prefix: "SMART_AGENT_TOOL_PYTHON"
    repository: "ghcr.io/ddkang1/mcp-py-repl:latest"
    url: "http://localhost:8002/sse"
    description: "Allows execution of Python code in a secure environment"
    container: true
```

All tool management is done through the configuration files in the `config` directory:

1. **Enable/Disable Tools**: Set `enabled: true` or `enabled: false` in your `tools.yaml` file
2. **Configure URLs**: Set the appropriate URLs for each tool in `tools.yaml`
3. **Storage Paths**: Configure where tool data is stored with the `storage_path` property

No command-line flags are needed - simply edit your configuration files and run the commands.

## Environment Configuration

Smart Agent uses a YAML-based configuration system. Configuration files are located in the `config` directory:

1. **Main Configuration Files**:
   - `config/config.yaml`: Main configuration file
   - `config/tools.yaml`: Tool-specific configuration
   - `config/litellm_config.yaml`: LiteLLM proxy configuration (when using proxy)

2. **Command Line Arguments**:
   - `--config`: Specify a custom configuration file path

The interactive setup wizard (`smart-agent setup`) will create these files for you with sensible defaults.

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
  think_tool:
    name: "Think Tool"
    type: "sse"
    enabled: true
    env_prefix: "SMART_AGENT_TOOL_THINK"
    repository: "git+https://github.com/ddkang1/mcp-think-tool"
    url: "http://localhost:8000/sse"
    description: "Enables the agent to pause, reflect, and ground its reasoning process"
    module: "mcp_think_tool"
    server_module: "mcp_think_tool.server"
  
  search_tool:
    name: "Search Tool"
    type: "sse"
    enabled: true
    env_prefix: "SMART_AGENT_TOOL_SEARCH"
    repository: "git+https://github.com/ddkang1/ddg-mcp"
    url: "http://localhost:8001/sse"
    description: "Provides web search capabilities to find information online"
    module: "ddg_mcp"
    server_module: "ddg_mcp.server"
  
  # Docker container-based tool example
  python_tool:
    name: "Python REPL Tool"
    type: "sse"
    enabled: true
    env_prefix: "SMART_AGENT_TOOL_PYTHON"
    repository: "ghcr.io/ddkang1/mcp-py-repl:latest"
    url: "http://localhost:8002/sse"
    description: "Allows execution of Python code in a secure environment"
    container: true
```

#### Tool Configuration Schema

Each tool in the YAML configuration can have the following properties:

| Property | Description | Required |
|----------|-------------|----------|
| `name` | Human-readable name | Yes |
| `type` | Tool type (e.g., "sse" or "stdio") | Yes |
| `enabled` | Whether the tool is enabled by default | Yes |
| `repository` | Git repository or Docker image for the tool | Yes |
| `url` | URL for the tool's endpoint | Yes |
| `description` | Brief description of what the tool does | No |
| `module` | Python module name (for pip install and import) | For Python tools |
| `server_module` | Module to run for the server | For Python tools |
| `container` | Set to true if the tool runs in a Docker container | For container tools |
| `env_prefix` | Environment variable prefix | No (defaults to SMART_AGENT_TOOL_{TOOL_ID_UPPERCASE}) |
| `launch_cmd` | Command to launch the tool | Yes (one of: "docker", "uvx", "npx") |
| `storage_path` | Path for tool data storage | No (used for Docker container tools) |

#### Tool Types and Launch Commands

Smart Agent supports two types of tools:
- **Remote SSE Tools**: Tools that are already running and accessible via a remote URL
- **Local stdio Tools**: Tools that need to be launched locally and converted to SSE

For local stdio tools, Smart Agent uses [supergateway](https://github.com/supercorp-ai/supergateway) to automatically convert them to SSE. This approach allows for seamless integration with various MCP tools without requiring them to natively support SSE.

The `launch_cmd` field specifies how the tool should be launched:
- **docker**: For container-based tools (e.g., Python REPL)
- **uvx**: For Python packages that use the uvx launcher
- **npx**: For Node.js-based tools

All local tools are treated as stdio tools and converted to SSE using supergateway, regardless of their type setting in the configuration.

## Configuration Management

Smart Agent uses YAML configuration files to manage settings and tools. The configuration is split into two main files:

1. **config.yaml** - Contains API settings, model configurations, and logging options
2. **tools.yaml** - Contains tool-specific settings including URLs and storage paths

The Smart Agent CLI provides commands to help manage these configuration files:

```bash
# Run the setup wizard to create configuration files
smart-agent setup
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
```

### Running Tests

```bash
pytest
```

## License

MIT

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
