"""
Chat command implementation for the Smart Agent CLI.
"""

import asyncio
import logging
import click

# Set up logging
logger = logging.getLogger(__name__)

# Import Smart Agent components
from ..tool_manager import ConfigManager
from ..core.cli_agent import CLISmartAgent

# Re-export the CLISmartAgent as SmartAgent for backward compatibility
SmartAgent = CLISmartAgent


@click.command()
@click.option(
    "--config",
    default=None,
    help="Path to configuration file",
)
@click.option(
    "--debug",
    is_flag=True,
    help="Enable debug logging",
)
def chat(config, debug):
    """
    Start a chat session with the agent.

    Args:
        config: Path to configuration file
        debug: Enable debug logging
    """
    # Create configuration manager
    config_manager = ConfigManager(config_path=config)
    
    # Configure logging
    from ..cli import configure_logging
    configure_logging(config_manager, debug)
    
    # Create and run the chat using the CLI-specific agent
    chat_agent = CLISmartAgent(config_manager)
    asyncio.run(chat_agent.run_chat_loop())


if __name__ == "__main__":
    chat()