"""
Command to run the Chainlit web UI for Smart Agent.
"""

import os
import sys
import subprocess
import argparse
from pathlib import Path

def run_chainlit_ui(args):
    """Run the Chainlit web UI."""
    # Get the path to the Chainlit app
    script_dir = Path(__file__).parent
    chainlit_app_path = script_dir.parent / "web" / "chainlit_app.py"

    # Check if the Chainlit app exists
    if not chainlit_app_path.exists():
        print(f"Error: Chainlit app not found at {chainlit_app_path}")
        return 1

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
    """Set up the argument parser for the chainlit-ui command."""
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to run the Chainlit server on"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host to run the Chainlit server on"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Run in debug mode"
    )
    return parser

def main():
    """Main entry point for the chainlit-ui command."""
    parser = argparse.ArgumentParser(description="Run the Chainlit web UI for Smart Agent")
    parser = setup_parser(parser)
    args = parser.parse_args()
    return run_chainlit_ui(args)

if __name__ == "__main__":
    sys.exit(main())
