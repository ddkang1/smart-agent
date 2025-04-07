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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# Configure logging for various libraries to suppress specific error messages
openai_agents_logger = logging.getLogger('openai.agents')
asyncio_logger = logging.getLogger('asyncio')
httpx_logger = logging.getLogger('httpx')
httpcore_logger = logging.getLogger('httpcore')
mcp_client_sse_logger = logging.getLogger('mcp.client.sse')

# Set log levels to reduce verbosity
httpx_logger.setLevel(logging.WARNING)
mcp_client_sse_logger.setLevel(logging.WARNING)

# Create a filter to suppress specific error messages
class SuppressSpecificErrorFilter(logging.Filter):
    """Filter to suppress specific error messages in logs.

    This filter checks log messages against a list of patterns and
    filters out any messages that match, preventing them from being
    displayed to the user.
    """
    def filter(self, record) -> bool:
        # Get the message from the record
        message = record.getMessage()

        # List of error patterns to suppress
        suppress_patterns = [
            'Error cleaning up server: Attempted to exit a cancel scope',
            'Event loop is closed',
            'Task exception was never retrieved',
            'AsyncClient.aclose',
        ]

        # Check if any of the patterns are in the message
        for pattern in suppress_patterns:
            if pattern in message:
                return False  # Filter out this message

        return True  # Keep this message

# Add the filter to various loggers
openai_agents_logger.addFilter(SuppressSpecificErrorFilter())
asyncio_logger.addFilter(SuppressSpecificErrorFilter())
httpx_logger.addFilter(SuppressSpecificErrorFilter())
httpcore_logger.addFilter(SuppressSpecificErrorFilter())

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


def main():
    """Main entry point for the CLI."""
    try:
        cli()
    except Exception as e:
        console.print(f"[bold red]Error:[/] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
