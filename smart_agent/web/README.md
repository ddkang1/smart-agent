# Smart Agent Web Interfaces

This directory contains web interfaces for Smart Agent. There are two implementations available:

1. **Streamlit UI**: The original web interface, designed to be an exact reflection of the CLI chat client
2. **Chainlit UI**: A newer interface with better support for displaying code blocks and agent reasoning

## Usage

### Streamlit UI

You can start the Streamlit UI using the `smart-agent web` command:

```bash
# Install with web dependencies
pip install "smart-agent[web]"

# Start the Streamlit UI
smart-agent web --config path/to/config.yaml --tools path/to/tools.yaml --port 8501
```

### Chainlit UI

You can start the Chainlit UI using the `smart-agent chainlit-ui` command:

```bash
# Install Chainlit
pip install chainlit

# Start the Chainlit UI
smart-agent chainlit-ui --port 8000 --host 127.0.0.1
```

The Chainlit UI provides a more modern interface with better support for displaying code blocks and agent reasoning steps.

## Configuration

The web UI uses the same configuration files as the CLI:

- `config.yaml`: Contains API keys, model settings, etc.
- `tools.yaml`: Contains tool configurations

You can specify these files using the `--config` and `--tools` options, or place them in the default locations.

## Development

### Streamlit UI Development

To develop the Streamlit UI:

1. Install the development dependencies:
   ```bash
   pip install -e ".[web,dev]"
   ```

2. Run the Streamlit app directly:
   ```bash
   streamlit run smart_agent/web/streamlit_app.py
   ```

### Chainlit UI Development

To develop the Chainlit UI:

1. Install Chainlit:
   ```bash
   pip install chainlit
   ```

2. Run the Chainlit app directly:
   ```bash
   chainlit run smart_agent/web/chainlit_app.py
   ```

## Implementation

### Streamlit UI

The Streamlit UI is a direct port of the CLI chat client. It maintains the same behavior and functionality, including:

- Automatic initialization using the provided config and tools paths
- Conversation history management
- Tool execution and visualization
- Error handling and cleanup

The Streamlit UI takes configuration directly from the command line arguments, so there's no need to enter config paths in the UI. It provides the exact same experience as the CLI chat client, but in a web interface.

### Chainlit UI

The Chainlit UI is a newer implementation that provides a more modern interface with better support for displaying code blocks and agent reasoning. Key features include:

- Settings panel for configuration (API keys, model selection, etc.)
- Expandable agent reasoning steps
- Better code block rendering
- Conversation history tracking
- Clean, modern UI design

The Chainlit UI uses the same underlying agent implementation as the CLI and Streamlit UI, but with a different presentation layer.
