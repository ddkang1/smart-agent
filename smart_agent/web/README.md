# Smart Agent Web UI

This directory contains the web interface for Smart Agent, implemented using Streamlit. The web UI is designed to be an exact reflection of the CLI chat client, with the same functionality and behavior but in a web interface.

## Usage

You can start the web UI using the `smart-agent web` command:

```bash
# Install with web dependencies
pip install "smart-agent[web]"

# Start the web UI
smart-agent web --config path/to/config.yaml --tools path/to/tools.yaml --port 8501
```

## Configuration

The web UI uses the same configuration files as the CLI:

- `config.yaml`: Contains API keys, model settings, etc.
- `tools.yaml`: Contains tool configurations

You can specify these files using the `--config` and `--tools` options, or place them in the default locations.

## Development

To develop the web UI:

1. Install the development dependencies:
   ```bash
   pip install -e ".[web,dev]"
   ```

2. Run the Streamlit app directly:
   ```bash
   streamlit run smart_agent/web/streamlit_app.py
   ```

## Implementation

The web UI is a direct port of the CLI chat client to Streamlit. It maintains the same behavior and functionality, including:

- Automatic initialization using the provided config and tools paths
- Conversation history management
- Tool execution and visualization
- Error handling and cleanup

The web UI takes configuration directly from the command line arguments, so there's no need to enter config paths in the UI. It provides the exact same experience as the CLI chat client, but in a web interface.
