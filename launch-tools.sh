#!/bin/bash

# Launch MCP Tool Services
# This script starts the various MCP tool services required for the smart-agent to function properly

# Default settings
PYTHON_REPL_DATA_DIR="python_repl_storage"
PYTHON_REPL_PORT=8000
LAUNCH_PYTHON_REPL=true

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
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [--no-python-repl] [--python-repl-data=DIR] [--python-repl-port=PORT]"
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
    if is_service_running "supergateway.*mcp-py-repl"; then
        echo "MCP Python REPL service is already running."
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
}

# Main execution
echo "Launching MCP Tool Services..."
echo "These services need to be running for smart-agent to function properly."
echo "Press Ctrl+C to stop all services when you're done."
echo ""

# Launch requested services
if [ "$LAUNCH_PYTHON_REPL" = true ]; then
    launch_python_repl
fi

# Add more tool launching functions here as needed
# For example: launch_web_browser_tool, launch_file_system_tool, etc.

echo ""
echo "All requested MCP tool services are now running."
echo "You can now run smart-agent in a separate terminal."
echo "Leave this terminal open to keep the services running."

# Wait for user to press Ctrl+C
trap "echo 'Stopping all services...'; kill $PYTHON_REPL_PID 2>/dev/null; exit 0" INT
wait
