#!/usr/bin/env python
"""
CLI interface for Smart Agent.

This module provides command-line interface functionality for the Smart Agent,
including chat, tool management, and configuration handling.
"""

# Standard library imports
import sys
import logging
import os

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


def check_config_exists(ctx, cmd_name):
    """
    Check if config.yaml exists in the current directory or if --config option is provided.
    
    Args:
        ctx: Click context
        cmd_name: Command name being executed
    
    Returns:
        True if config exists or init command is being run, False otherwise
    """
    # Skip check for init command
    if cmd_name == "init":
        return True
        
    # Check if --config option is provided
    params = ctx.params
    if params.get("config") and os.path.exists(params["config"]):
        return True
        
    # Check if config.yaml exists in current directory
    if os.path.exists(os.path.join(os.getcwd(), "config.yaml")):
        return True
        
    # Config not found, show message
    console.print("[bold yellow]Configuration file not found![/]")
    console.print("Please run [bold]smart-agent init[/] to create a configuration file")
    console.print("or specify a config file with [bold]--config[/] option.")
    return False


def main():
    """Main entry point for the CLI."""
    try:
        # Get the original command
        cmd_name = sys.argv[1] if len(sys.argv) > 1 else None
        
        # Create a new Click context
        ctx = click.Context(cli)
        
        # Parse parameters to get --config option if provided
        try:
            cli.parse_args(ctx, sys.argv[1:])
        except:
            # Ignore parsing errors, we just need to extract --config if present
            pass
            
        # Check if config exists for commands that need it
        if cmd_name in ["start", "stop", "status", "chat", "chainlit"]:
            if not check_config_exists(ctx, cmd_name):
                sys.exit(1)
                
        # Run the CLI command
        cli()
    except Exception as e:
        console.print(f"[bold red]Error:[/] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
