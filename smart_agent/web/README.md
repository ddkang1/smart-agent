# Smart Agent Web Interface

This directory contains the web interface for Smart Agent.

## Usage

### Chainlit UI

You can start the Chainlit UI using the `smart-agent chainlit` command:

```bash
# Install Chainlit
pip install chainlit

# Start the Chainlit UI
smart-agent chainlit --port 8000 --host 127.0.0.1
```

The Chainlit UI provides a modern interface with better support for displaying code blocks and agent reasoning steps.

## Configuration

The web UI uses the same configuration files as the CLI:

- `config.yaml`: Contains API keys, model settings, etc.
- `tools.yaml`: Contains tool configurations

You can specify these files using the `--config` and `--tools` options, or place them in the default locations.

## Development

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

   Or use the Smart Agent CLI:
   ```bash
   smart-agent chainlit --debug
   ```

## Implementation

### Chainlit UI

The Chainlit UI provides a modern interface with better support for displaying code blocks and agent reasoning. Key features include:

- Settings panel for configuration (API keys, model selection, etc.)
- Expandable agent reasoning steps
- Better code block rendering
- Conversation history tracking
- Clean, modern UI design

The Chainlit UI uses the same underlying agent implementation as the CLI, but with a different presentation layer.
