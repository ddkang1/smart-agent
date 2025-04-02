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

### Getting Started

After installation, follow these steps to set up and use Smart Agent:

1. **Initial Setup**:
   ```bash
   # Create and configure the necessary YAML files (API keys, etc.)
   smart-agent setup
   ```
   This will:
   - Create configuration files (`config.yaml` and `tools.yaml`)
   - Prompt for your API key
   - Create necessary directories

2. **Launch Tool Services**:
   ```bash
   # Start the required tool services in the background
   smart-agent launch-tools
   ```
   Keep this terminal open. The tools will continue running and be available for the agent to use.

3. **Start Smart Agent**:
   ```bash
   # In a new terminal, start a chat session
   smart-agent chat
   ```
   Now you can chat with Smart Agent, which will use the tools you launched in step 2.

**Docker Alternative** (all-in-one solution):
```bash
# Clone the repository
git clone https://github.com/ddkang1/smart-agent.git
cd smart-agent

# Run the setup script and start all services
./run.sh
```

### Tool Management

Smart Agent provides a simple way to manage tools through YAML configuration:

```yaml
# Example tools.yaml configuration
tools:
  think_tool:
    name: "Think Tool"
    type: "sse"
    enabled: true  # Set to false to disable this tool
    url: "http://localhost:8001/sse"
    # ... other configuration options
```

All tool management is done through the configuration files in the `config` directory:

1. **Enable/Disable Tools**: Set `enabled: true` or `enabled: false` in your `tools.yaml` file
2. **Configure URLs**: Set the appropriate URLs for each tool in `tools.yaml`
3. **Storage Paths**: Configure where tool data is stored with the `storage_path` property

No command-line flags are needed - simply edit your configuration files and run the commands.

## Environment Configuration

Smart Agent uses a YAML-based configuration system. Configuration can be provided in the following ways:

1. **YAML Configuration Files**:
   - `config/config.yaml`: Main configuration file
   - `config/tools.yaml`: Tool-specific configuration (referenced from main config)

2. **Environment Variables**:
   - Environment variables can override YAML configuration
   - Can be set in a `.env` file or passed directly to the CLI

3. **Command Line Arguments**:
   - `--config`: Specify a custom configuration file path
   - `--disable-tools`: Disable all tools

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

### Environment Variables

Smart Agent primarily uses YAML-based configuration files, but the following environment variables can be used to override specific settings in Docker environments:

- `OPENAI_API_KEY`: Your OpenAI API key (required for API access)
- `OPENAI_API_BASE`: Base URL for the API (optional)

For most use cases, you should configure the agent through the YAML configuration files rather than environment variables.

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
    url: "http://localhost:8001/sse"
    description: "Enables the agent to pause, reflect, and ground its reasoning process"
    module: "mcp_think_tool"
    server_module: "mcp_think_tool.server"
  
  # Docker container-based tool example
  python_tool:
    name: "Python REPL Tool"
    type: "sse"
    enabled: true
    env_prefix: "SMART_AGENT_TOOL_PYTHON"
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

#### Environment Variable Override

While the YAML configuration is the preferred method, you can override tool configuration using environment variables in specific scenarios (like Docker environments):

- `ENABLE_TOOL_NAME`: Enable or disable a tool (e.g., `ENABLE_THINK_TOOL=false`)
- `SMART_AGENT_TOOL_NAME_URL`: Override the tool URL (e.g., `SMART_AGENT_TOOL_THINK_URL=http://localhost:9001/sse`)

The environment variables take precedence over the YAML configuration, but for most use cases, you should configure tools through the YAML files.

## Configuration Management

Smart Agent uses YAML configuration files to manage settings and tools. The configuration is split into two main files:

1. **config.yaml**: Contains general settings like API configuration, model settings, and logging options
2. **tools.yaml**: Contains tool-specific configurations

### Managing Configuration Files

For security and privacy, the actual configuration files are not included in the repository. Instead, example templates are provided:

- `config/config.yaml.example`
- `config/tools.yaml.example`

When you run the `setup-env.sh` script, it will:

1. Create `config.yaml` and `tools.yaml` from the example templates if they don't exist
2. Prompt for necessary API keys and update the configuration files
3. Create any required storage directories based on the tool configuration

The actual configuration files (`config.yaml` and `tools.yaml`) are excluded from Git via `.gitignore` to prevent accidentally committing sensitive information.

### Local Development

For local development:

1. Run `./setup-env.sh` to create your configuration files
2. Edit the generated files to match your environment
3. Your changes will remain local and won't be committed to the repository

### Deployment

For deployment environments:

1. Create the configuration files manually or use the setup script
2. Set environment variables to override specific settings as needed
3. Use Docker for easy deployment: `./run.sh`
4. Use secrets management appropriate for your deployment platform

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
