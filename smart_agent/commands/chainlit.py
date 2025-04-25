"""
Command to run the Chainlit web interface for Smart Agent.
"""

import os
import sys
import socket
import time
import subprocess
import argparse
from pathlib import Path

def find_available_port(start_port=8000, max_attempts=100):
    """Find an available port starting from start_port."""
    # Try a wider range of ports
    for port in range(start_port, start_port + max_attempts):
        try:
            # Create a socket with a timeout
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)  # 1 second timeout
            
            # Set SO_REUSEADDR option to allow reusing the address immediately
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # Try to bind to the port
            s.bind(("0.0.0.0", port))
            
            # If we get here, the port is available
            s.close()
            
            # Wait a moment to ensure the port is fully released
            time.sleep(0.1)
            
            return port
        except (OSError, socket.error):
            # Port is already in use, try the next one
            try:
                s.close()
            except:
                pass
            continue
    
    # If we get here, no ports were available in the range
    # Try a completely different port range
    for port in range(9000, 9000 + max_attempts):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", port))
            s.close()
            time.sleep(0.1)
            return port
        except (OSError, socket.error):
            try:
                s.close()
            except:
                pass
            continue
    
    # If all else fails, return a high port number
    return 10000  # Just return a high port and let Chainlit handle any errors

def run_chainlit_ui(args):
    """Run the Chainlit web UI."""
    # Get the path to the Chainlit app
    script_dir = Path(__file__).parent
    chainlit_app_path = script_dir.parent / "web" / "chainlit_app.py"
    
    # Check if the Chainlit app exists
    if not chainlit_app_path.exists():
        print(f"Error: Chainlit app not found at {chainlit_app_path}")
        return 1
    
    # Check if the specified port is available, if not find an available one
    port = find_available_port(args.port)
    if port != args.port:
        print(f"Port {args.port} is already in use. Using port {port} instead.")
        args.port = port
    
    # Build the command to run Chainlit
    cmd = [
        "chainlit", "run", 
        str(chainlit_app_path),
        "--port", str(args.port),
        "--host", args.host
    ]
    
    if args.debug:
        cmd.append("--debug")
    
    # Run Chainlit
    try:
        print(f"Starting Chainlit web UI on http://{args.host}:{args.port}")
        process = subprocess.Popen(cmd)
        process.wait()
        return process.returncode
    except KeyboardInterrupt:
        print("\nStopping Chainlit web UI...")
        return 0
    except Exception as e:
        print(f"Error running Chainlit: {e}")
        print("Make sure Chainlit is installed: pip install chainlit")
        return 1

def setup_parser(parser):
    """Set up the argument parser for the chainlit command."""
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to run the Chainlit server on"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host to run the Chainlit server on"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Run in debug mode"
    )
    return parser

def main():
    """Main entry point for the chainlit command."""
    parser = argparse.ArgumentParser(description="Run the Chainlit web UI for Smart Agent")
    parser = setup_parser(parser)
    args = parser.parse_args()
    return run_chainlit_ui(args)

if __name__ == "__main__":
    sys.exit(main())
