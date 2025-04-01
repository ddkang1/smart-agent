#!/bin/bash

# Launch MCP Tool Services
# This script starts the various MCP tool services required for the smart-agent to function properly

# Default settings
PYTHON_REPL_DATA_DIR="python_repl_storage"
PYTHON_REPL_PORT=8000
LAUNCH_PYTHON_REPL=true

THINK_TOOL_REPO="git+https://github.com/ddkang1/mcp-think-tool"
THINK_TOOL_PORT=8001
LAUNCH_THINK_TOOL=true

SEARCH_TOOL_REPO="git+https://github.com/ddkang1/ddg-mcp"
SEARCH_TOOL_PORT=8002
LAUNCH_SEARCH_TOOL=true

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --no-python-repl)
      LAUNCH_PYTHON_REPL=false
      shift
      ;;
    --python-repl-data=*)
      PYTHON_REPL_DATA_DIR="${1#*=}"
      shift
      ;;
    --python-repl-port=*)
      PYTHON_REPL_PORT="${1#*=}"
      shift
      ;;
    --no-think-tool)
      LAUNCH_THINK_TOOL=false
      shift
      ;;
    --think-tool-port=*)
      THINK_TOOL_PORT="${1#*=}"
      shift
      ;;
    --think-tool-repo=*)
      THINK_TOOL_REPO="${1#*=}"
      shift
      ;;
    --no-search-tool)
      LAUNCH_SEARCH_TOOL=false
      shift
      ;;
    --search-tool-port=*)
      SEARCH_TOOL_PORT="${1#*=}"
      shift
      ;;
    --search-tool-repo=*)
      SEARCH_TOOL_REPO="${1#*=}"
      shift
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [--no-python-repl] [--python-repl-data=DIR] [--python-repl-port=PORT]"
      echo "          [--no-think-tool] [--think-tool-port=PORT] [--think-tool-repo=REPO]"
      echo "          [--no-search-tool] [--search-tool-port=PORT] [--search-tool-repo=REPO]"
      exit 1
      ;;
  esac
done

# Function to check if a service is running
is_service_running() {
    local service_pattern=$1
    pgrep -f "$service_pattern" > /dev/null
}

# Function to launch Python REPL tool
launch_python_repl() {
    # Create data directory if it doesn't exist
    mkdir -p "$PYTHON_REPL_DATA_DIR"
    echo "Created directory for Python REPL tool: $PYTHON_REPL_DATA_DIR"

    # Check if the service is already running
    if is_service_running "supergateway.*mcp-py-repl.*$PYTHON_REPL_PORT"; then
        echo "MCP Python REPL service is already running on port $PYTHON_REPL_PORT."
        return 0
    fi

    echo "Launching MCP Python REPL service on port $PYTHON_REPL_PORT..."
    echo "Data will be stored in: $PYTHON_REPL_DATA_DIR"
    
    # Run the MCP Python REPL service
    npx -y supergateway \
        --stdio "docker run -i --rm --pull=always -v ./$PYTHON_REPL_DATA_DIR:/mnt/data/ ghcr.io/ddkang1/mcp-py-repl:latest" \
        --port "$PYTHON_REPL_PORT" --baseUrl "http://localhost:$PYTHON_REPL_PORT" \
        --ssePath /sse --messagePath /message &
    
    # Store the PID
    PYTHON_REPL_PID=$!
    echo "Python REPL service started with PID: $PYTHON_REPL_PID"
    
    # Add to PIDs array
    TOOL_PIDS+=($PYTHON_REPL_PID)
}

# Function to launch Think Tool
launch_think_tool() {
    # Check if the service is already running
    if is_service_running "supergateway.*mcp-think-tool.*$THINK_TOOL_PORT"; then
        echo "MCP Think Tool service is already running on port $THINK_TOOL_PORT."
        return 0
    fi

    echo "Launching MCP Think Tool service on port $THINK_TOOL_PORT..."
    
    # Run the MCP Think Tool service
    npx -y supergateway \
        --stdio "uvx --from $THINK_TOOL_REPO mcp-think-tool" \
        --port "$THINK_TOOL_PORT" --baseUrl "http://localhost:$THINK_TOOL_PORT" \
        --ssePath /sse --messagePath /message &
    
    # Store the PID
    THINK_TOOL_PID=$!
    echo "Think Tool service started with PID: $THINK_TOOL_PID"
    
    # Add to PIDs array
    TOOL_PIDS+=($THINK_TOOL_PID)
}

# Function to launch Search Tool
launch_search_tool() {
    # Check if the service is already running
    if is_service_running "supergateway.*ddg-mcp.*$SEARCH_TOOL_PORT"; then
        echo "MCP Search Tool service is already running on port $SEARCH_TOOL_PORT."
        return 0
    fi

    echo "Launching MCP Search Tool service on port $SEARCH_TOOL_PORT..."
    
    # Run the MCP Search Tool service
    npx -y supergateway \
        --stdio "uvx --from $SEARCH_TOOL_REPO ddg-mcp" \
        --port "$SEARCH_TOOL_PORT" --baseUrl "http://localhost:$SEARCH_TOOL_PORT" \
        --ssePath /sse --messagePath /message &
    
    # Store the PID
    SEARCH_TOOL_PID=$!
    echo "Search Tool service started with PID: $SEARCH_TOOL_PID"
    
    # Add to PIDs array
    TOOL_PIDS+=($SEARCH_TOOL_PID)
}

# Main execution
echo "Launching MCP Tool Services..."
echo "These services need to be running for smart-agent to function properly."
echo "Press Ctrl+C to stop all services when you're done."
echo ""

# Initialize array to store PIDs
TOOL_PIDS=()

# Launch requested services
if [ "$LAUNCH_PYTHON_REPL" = true ]; then
    launch_python_repl
fi

if [ "$LAUNCH_THINK_TOOL" = true ]; then
    launch_think_tool
fi

if [ "$LAUNCH_SEARCH_TOOL" = true ]; then
    launch_search_tool
fi

# Add more tool launching functions here as needed
# For example: launch_web_browser_tool, launch_file_system_tool, etc.

echo ""
echo "All requested MCP tool services are now running."
echo "You can now run smart-agent in a separate terminal."
echo "Leave this terminal open to keep the services running."

# Function to kill all tool processes
cleanup() {
    echo "Stopping all services..."
    for pid in "${TOOL_PIDS[@]}"; do
        kill $pid 2>/dev/null
    done
    exit 0
}

# Set up trap for Ctrl+C
trap cleanup INT

# Wait for all background processes
wait
