# Smart Agent

A powerful AI agent chatbot that leverages external tools through the Model Context Protocol (MCP) to extend its capabilities beyond traditional language models.

## Quick Start

```bash
# Install Smart Agent
pip install smart-agent

# For web interface (Chainlit), install with web extras
pip install smart-agent[web]

# Initialize configuration
smart-agent init

# Start the CLI chat interface (connects to remote tools by default)
smart-agent chat

# OR start the web interface
smart-agent chainlit

# If you need to run your own tools locally:
smart-agent start  # Start the server components
```

## Understanding Smart Agent

Smart Agent operates in two primary modes:

### 1. Client Mode

Client mode provides chat interfaces that connect to MCP servers (either local or remote).

- **What it does**: Provides CLI or web interfaces to interact with the agent
- **When to use**: When you want to chat with the agent using available tools

```bash
# CLI interface
smart-agent chat

# Web interface (Chainlit)
smart-agent chainlit
```

### 2. Server Mode

Server mode manages MCP (Model Context Protocol) servers that provide tools and capabilities to the agent.

- **What it does**: Launches and manages tool servers that expose capabilities through standardized endpoints
- **When to use**: When you need to run tools locally or host tools for remote clients

```bash
# Start all server components (tools and LLM proxy)
smart-agent start

# Check status of running services
smart-agent status

# Stop all services
smart-agent stop
```

## Connection Types

Smart Agent supports two primary connection types between clients and servers:

### Local Connection (stdio)

- **How it works**: Direct communication through standard input/output
- **When to use**: For tools running locally on the same machine
- **Configuration**: Use `transport: stdio` in your config

### Remote Connection (SSE)

- **How it works**: Communication via Server-Sent Events over HTTP/HTTPS
- **When to use**: For connecting to tools running on remote machines
- **Configuration**: Use `transport: sse` in your config

### Transport Conversion

Smart Agent provides conversion mechanisms between transport types:

- **stdio_to_sse**: Converts local stdio tools to SSE endpoints
  - Useful for exposing local tools as network services
  - Example: `transport: stdio_to_sse` in config

- **sse_to_stdio**: Converts remote SSE endpoints to local stdio
  - Useful for using remote tools as if they were local
  - Example: `transport: sse_to_stdio` in config

## Configuration Example

```yaml
# config.yaml
llm:
  base_url: "http://localhost:4000"
  model: "claude-3-7-sonnet-20240229"
  api_key: "api_key"
  temperature: 0.0

tools:
  # Local tool with stdio_to_sse conversion
  mcp_think_tool:
    enabled: true
    url: "http://localhost:8000/sse"
    command: "uvx mcp-think --sse --host 0.0.0.0"
    transport: stdio_to_sse

  # Remote tool
  remote_tool:
    enabled: true
    url: "https://api.remote-tool.com/sse"
    transport: sse
```

## Common Usage Patterns

### Using Remote Tools (Simplest)

```bash
# Initialize configuration
smart-agent init

# Edit config.yaml to use remote URLs
# Example: url: "https://api.remote-tool.com/sse"

# Start client interface - will automatically connect to remote tools
smart-agent chat  # or chainlit
```

### Local Development (Running Your Own Tools)

```bash
# Initialize configuration
smart-agent init

# Start server components
smart-agent start

# Start client interface
smart-agent chat  # or chainlit
```

## Prerequisites

- Python 3.9+
- Node.js and npm (for running tools via supergateway)
- Docker (optional, for container-based tools)
- API keys for language models

## Installation

```bash
# Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install from PyPI
pip install smart-agent

# For web interface (Chainlit)
pip install smart-agent[web]

# For monitoring features
pip install smart-agent[monitoring]
```

For more detailed information, see the [documentation](https://github.com/ddkang1/smart-agent/wiki).
