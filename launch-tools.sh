#!/bin/bash
# Launch MCP Tool Services
# This script starts the various MCP tool services required for the smart-agent to function properly

set -e

# Default values
CONFIG_FILE="config/tools.yaml"
PYTHON_REPL_DATA="python_repl_storage"
PYTHON_REPL_PORT=8000
THINK_TOOL_PORT=8001
SEARCH_TOOL_PORT=8002
ENABLE_PYTHON_REPL=true
ENABLE_THINK_TOOL=true
ENABLE_SEARCH_TOOL=true

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --config=*)
      CONFIG_FILE="${1#*=}"
      shift
      ;;
    --python-repl-data=*)
      PYTHON_REPL_DATA="${1#*=}"
      shift
      ;;
    --python-repl-port=*)
      PYTHON_REPL_PORT="${1#*=}"
      shift
      ;;
    --think-tool-port=*)
      THINK_TOOL_PORT="${1#*=}"
      shift
      ;;
    --search-tool-port=*)
      SEARCH_TOOL_PORT="${1#*=}"
      shift
      ;;
    --no-python-repl)
      ENABLE_PYTHON_REPL=false
      shift
      ;;
    --no-think-tool)
      ENABLE_THINK_TOOL=false
      shift
      ;;
    --no-search-tool)
      ENABLE_SEARCH_TOOL=false
      shift
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

# Function to parse YAML using Python
parse_yaml() {
  local file=$1
  local tool=$2
  local property=$3
  python3 -c "
import yaml
try:
    with open('$file', 'r') as f:
        config = yaml.safe_load(f)
    print(config.get('tools', {}).get('$tool', {}).get('$property', ''))
except Exception as e:
    print('')
"
}

# Check if config file exists and load values from it
if [ -f "$CONFIG_FILE" ]; then
  echo "Loading tool configuration from $CONFIG_FILE"
  
  # Only override if not explicitly set via command line
  if [ "$ENABLE_PYTHON_REPL" = true ]; then
    PYTHON_TOOL_REPO=$(parse_yaml "$CONFIG_FILE" "python_tool" "repository")
    PYTHON_TOOL_ENABLED=$(parse_yaml "$CONFIG_FILE" "python_tool" "enabled")
    if [ -n "$PYTHON_TOOL_ENABLED" ] && [ "$PYTHON_TOOL_ENABLED" = "false" ]; then
      ENABLE_PYTHON_REPL=false
    fi
  fi
  
  if [ "$ENABLE_THINK_TOOL" = true ]; then
    THINK_TOOL_REPO=$(parse_yaml "$CONFIG_FILE" "think_tool" "repository")
    THINK_TOOL_ENABLED=$(parse_yaml "$CONFIG_FILE" "think_tool" "enabled")
    if [ -n "$THINK_TOOL_ENABLED" ] && [ "$THINK_TOOL_ENABLED" = "false" ]; then
      ENABLE_THINK_TOOL=false
    fi
  fi
  
  if [ "$ENABLE_SEARCH_TOOL" = true ]; then
    SEARCH_TOOL_REPO=$(parse_yaml "$CONFIG_FILE" "search_tool" "repository")
    SEARCH_TOOL_ENABLED=$(parse_yaml "$CONFIG_FILE" "search_tool" "enabled")
    if [ -n "$SEARCH_TOOL_ENABLED" ] && [ "$SEARCH_TOOL_ENABLED" = "false" ]; then
      ENABLE_SEARCH_TOOL=false
    fi
  fi
fi

# Environment variables take precedence over config file
PYTHON_TOOL_REPO=${MCP_PYTHON_TOOL_REPO:-${PYTHON_TOOL_REPO:-"ghcr.io/ddkang1/mcp-py-repl:latest"}}
THINK_TOOL_REPO=${MCP_THINK_TOOL_REPO:-${THINK_TOOL_REPO:-"git+https://github.com/ddkang1/mcp-think-tool"}}
SEARCH_TOOL_REPO=${MCP_SEARCH_TOOL_REPO:-${SEARCH_TOOL_REPO:-"git+https://github.com/ddkang1/ddg-mcp"}}

# Override enable flags from environment variables if set
if [ -n "$ENABLE_PYTHON_TOOL" ]; then
  if [ "$ENABLE_PYTHON_TOOL" = "false" ]; then
    ENABLE_PYTHON_REPL=false
  fi
fi

if [ -n "$ENABLE_THINK_TOOL" ]; then
  if [ "$ENABLE_THINK_TOOL" = "false" ]; then
    ENABLE_THINK_TOOL=false
  fi
fi

if [ -n "$ENABLE_SEARCH_TOOL" ]; then
  if [ "$ENABLE_SEARCH_TOOL" = "false" ]; then
    ENABLE_SEARCH_TOOL=false
  fi
fi

# Create data directory if it doesn't exist
mkdir -p "$PYTHON_REPL_DATA"

# Start Python REPL tool
if [ "$ENABLE_PYTHON_REPL" = true ]; then
  echo "Starting Python REPL tool on port $PYTHON_REPL_PORT"
  docker run -d --rm --name mcp-python-repl \
    -p "$PYTHON_REPL_PORT:8000" \
    -v "$(pwd)/$PYTHON_REPL_DATA:/app/data" \
    "$PYTHON_TOOL_REPO"
  
  # Set environment variable for the URL
  export MCP_PYTHON_TOOL_URL="http://localhost:$PYTHON_REPL_PORT/sse"
  echo "Python REPL tool available at $MCP_PYTHON_TOOL_URL"
else
  echo "Python REPL tool disabled"
fi

# Start Think tool
if [ "$ENABLE_THINK_TOOL" = true ]; then
  echo "Starting Think tool on port $THINK_TOOL_PORT"
  
  # Install the Think tool if not already installed
  if ! pip show mcp-think-tool &> /dev/null; then
    echo "Installing Think tool from $THINK_TOOL_REPO"
    pip install "$THINK_TOOL_REPO"
  fi
  
  # Start the Think tool server
  python -m mcp_think_tool.server --port "$THINK_TOOL_PORT" &
  THINK_TOOL_PID=$!
  
  # Set environment variable for the URL
  export MCP_THINK_TOOL_URL="http://localhost:$THINK_TOOL_PORT/sse"
  echo "Think tool available at $MCP_THINK_TOOL_URL"
else
  echo "Think tool disabled"
fi

# Start Search tool
if [ "$ENABLE_SEARCH_TOOL" = true ]; then
  echo "Starting Search tool on port $SEARCH_TOOL_PORT"
  
  # Install the Search tool if not already installed
  if ! pip show ddg-mcp &> /dev/null; then
    echo "Installing Search tool from $SEARCH_TOOL_REPO"
    pip install "$SEARCH_TOOL_REPO"
  fi
  
  # Start the Search tool server
  python -m ddg_mcp.server --port "$SEARCH_TOOL_PORT" &
  SEARCH_TOOL_PID=$!
  
  # Set environment variable for the URL
  export MCP_SEARCH_TOOL_URL="http://localhost:$SEARCH_TOOL_PORT/sse"
  echo "Search tool available at $MCP_SEARCH_TOOL_URL"
else
  echo "Search tool disabled"
fi

echo "All enabled tools are now running. Press Ctrl+C to stop."

# Handle cleanup on exit
cleanup() {
  echo "Stopping all tools..."
  
  if [ "$ENABLE_PYTHON_REPL" = true ]; then
    docker stop mcp-python-repl &> /dev/null || true
  fi
  
  if [ "$ENABLE_THINK_TOOL" = true ]; then
    kill $THINK_TOOL_PID &> /dev/null || true
  fi
  
  if [ "$ENABLE_SEARCH_TOOL" = true ]; then
    kill $SEARCH_TOOL_PID &> /dev/null || true
  fi
  
  echo "All tools stopped."
  exit 0
}

trap cleanup INT TERM

# Keep the script running
while true; do
  sleep 1
done
