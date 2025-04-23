#!/usr/bin/env python
"""
CLI interface for Smart Agent.

This module provides command-line interface functionality for the Smart Agent,
including chat, tool management, and configuration handling.
"""

# Standard library imports
import sys
import logging

# Third-party imports
import click
from rich.console import Console

# Local imports
from . import __version__
from .commands.chat import chat
from .commands.start import start
from .commands.stop import stop
from .commands.status import status
from .commands.init import init
from .commands.setup import setup, launch_litellm_proxy

# Try to import streamlit commands if dependencies are available
try:
    import streamlit
    from .commands.streamlit import streamlit as streamlit_cmd
    has_streamlit = True
except ImportError:
    has_streamlit = False

try:
    import chainlit
    from .commands.chainlit import run_chainlit_ui, setup_parser
    has_chainlit = True
except ImportError:
    has_chainlit = False

# Import ConfigManager for type hints
from .tool_manager import ConfigManager

# Default logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

def configure_logging(config_manager=None, debug=False):
    """Configure logging based on settings from config_manager.
    
    Args:
        config_manager: Optional ConfigManager instance. If not provided,
                       default logging settings will be used.
        debug: If True, set log level to DEBUG regardless of config settings.
    """
    if config_manager:
        log_level_str = config_manager.get_log_level()
        log_file = config_manager.get_log_file()
        
        # If debug flag is set, override log level to DEBUG
        if debug:
            log_level_str = "DEBUG"
        
        # Convert string log level to logging constant
        log_level = getattr(logging, log_level_str.upper(), logging.INFO)
        
        # Configure logging
        handlers = [logging.StreamHandler()]
        if log_file:
            handlers.append(logging.FileHandler(log_file))
        
        # Reset root logger handlers
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)
            
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=handlers,
        )
        
        # Configure specific loggers
        litellm_logger = logging.getLogger('litellm')
        litellm_logger.setLevel(log_level)
        
        # Always keep backoff logger at WARNING or higher to suppress retry messages
        backoff_logger = logging.getLogger('backoff')
        backoff_logger.setLevel(logging.WARNING)
        
        # Log the current logging level
        logger.debug(f"Logging level set to {log_level_str}")

# Configure logging for various libraries to suppress specific error messages
openai_agents_logger = logging.getLogger('openai.agents')
asyncio_logger = logging.getLogger('asyncio')
httpx_logger = logging.getLogger('httpx')
httpcore_logger = logging.getLogger('httpcore')
mcp_client_sse_logger = logging.getLogger('mcp.client.sse')
backoff_logger = logging.getLogger('backoff')

# Set backoff logger to WARNING to suppress retry messages
backoff_logger.setLevel(logging.WARNING)

# Set log levels to reduce verbosity
httpx_logger.setLevel(logging.WARNING)
mcp_client_sse_logger.setLevel(logging.WARNING)
# Set openai.agents logger to CRITICAL to suppress ERROR messages
openai_agents_logger.setLevel(logging.CRITICAL)

# Create a filter to suppress specific error messages
# class SuppressSpecificErrorFilter(logging.Filter):
#     """Filter to suppress specific error messages in logs.

#     This filter checks log messages against a list of patterns and
#     filters out any messages that match, preventing them from being
#     displayed to the user.
#     """
#     def filter(self, record) -> bool:
#         # Get the message from the record
#         message = record.getMessage()

#         # List of error patterns to suppress
#         suppress_patterns = [
#             'Error cleaning up server: Attempted to exit a cancel scope',
#             'Event loop is closed',
#             'Task exception was never retrieved',
#             'AsyncClient.aclose',
#         ]

#         # Check if any of the patterns are in the message
#         for pattern in suppress_patterns:
#             if pattern in message:
#                 return False  # Filter out this message

#         return True  # Keep this message

# # Add the filter to various loggers
# openai_agents_logger.addFilter(SuppressSpecificErrorFilter())
# asyncio_logger.addFilter(SuppressSpecificErrorFilter())
# httpx_logger.addFilter(SuppressSpecificErrorFilter())
# httpcore_logger.addFilter(SuppressSpecificErrorFilter())

# Initialize console for rich output
console = Console()

# Optional imports with fallbacks
try:
    from agents import set_tracing_disabled
    set_tracing_disabled(disabled=True)
except ImportError:
    logger.debug("Agents package not installed. Tracing will not be disabled.")


@click.group()
@click.version_option(version=__version__)
def cli():
    """Smart Agent CLI."""
    pass


# Add commands to the CLI
cli.add_command(chat)
cli.add_command(start)
cli.add_command(stop)
cli.add_command(status)
cli.add_command(init)
cli.add_command(setup)

# Add streamlit command if streamlit is available
if has_streamlit:
    cli.add_command(streamlit_cmd, name="streamlit")
else:
    # Create a placeholder command that shows installation instructions
    @click.command(name="streamlit")
    def streamlit_placeholder():
        """Start Streamlit web interface (requires web dependencies)."""
        console.print("[bold yellow]Streamlit web dependencies not installed.[/]")
        console.print("To use this command, install web dependencies:")
        console.print("[bold]pip install 'smart-agent[web]'[/]")

    # Add placeholder command
    cli.add_command(streamlit_placeholder, name="streamlit")

# Add chainlit command if chainlit is available
if has_chainlit:
    @click.command(name="chainlit")
    @click.option("--port", default=8000, help="Port to run the server on")
    @click.option("--host", default="127.0.0.1", help="Host to run the server on")
    @click.option("--debug", is_flag=True, help="Run in debug mode")
    def chainlit_ui(port, host, debug):
        """Start Chainlit web interface."""
        from .commands.chainlit import run_chainlit_ui
        class Args:
            def __init__(self, port, host, debug):
                self.port = port
                self.host = host
                self.debug = debug
        run_chainlit_ui(Args(port, host, debug))

    # Add chainlit command
    cli.add_command(chainlit_ui, name="chainlit")
else:
    # Create a placeholder command that shows installation instructions
    @click.command(name="chainlit")
    def chainlit_ui_placeholder():
        """Start Chainlit web interface (requires chainlit)."""
        console.print("[bold yellow]Chainlit not installed.[/]")
        console.print("To use this command, install Chainlit:")
        console.print("[bold]pip install chainlit[/]")

    # Add placeholder command
    cli.add_command(chainlit_ui_placeholder, name="chainlit")


def main():
    """Main entry point for the CLI."""
    try:
        cli()
    except Exception as e:
        console.print(f"[bold red]Error:[/] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
