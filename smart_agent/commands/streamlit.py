"""
Streamlit command implementation for the Smart Agent CLI.
"""

import os
import sys
import subprocess
import click
import logging

# Set up logging
logger = logging.getLogger(__name__)

@click.command()
@click.option(
    "--config",
    default=None,
    help="Path to configuration file",
)
@click.option(
    "--tools",
    default=None,
    help="Path to tools configuration file",
)
@click.option(
    "--port",
    default=8501,
    help="Port to run the Streamlit server on",
)
def streamlit(config, tools, port):
    """
    Start a Streamlit web interface for the agent.

    Args:
        config: Path to configuration file
        tools: Path to tools configuration file
        port: Port to run the Streamlit server on
    """
    try:
        # Check if streamlit is installed
        try:
            import streamlit as st
        except ImportError:
            print("Streamlit is not installed. Please install it with 'pip install smart-agent[web]'")
            return
        
        # Get the path to the streamlit_app.py file
        web_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        streamlit_app_path = os.path.join(web_dir, "web", "streamlit_app.py")
        
        # Check if the file exists
        if not os.path.exists(streamlit_app_path):
            print(f"Error: Streamlit app file not found at {streamlit_app_path}")
            return
        
        # Set environment variables for configuration
        if config:
            os.environ["SMART_AGENT_CONFIG"] = config
        if tools:
            os.environ["SMART_AGENT_TOOLS"] = tools
        
        # Build the command to run streamlit
        cmd = [
            "streamlit", "run", 
            streamlit_app_path,
            "--server.port", str(port),
            "--server.headless", "true",
            "--browser.serverAddress", "localhost",
            "--theme.base", "light"
        ]
        
        print(f"Starting Streamlit server on port {port}...")
        print(f"URL: http://localhost:{port}")
        print("Press Ctrl+C to stop the server")
        
        # Run the streamlit command
        subprocess.run(cmd)
        
    except KeyboardInterrupt:
        print("\nStopping Streamlit server...")
    except Exception as e:
        print(f"Error starting Streamlit interface: {e}")
        import traceback
        traceback.print_exc()