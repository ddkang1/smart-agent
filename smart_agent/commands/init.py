"""
Init command implementation for the Smart Agent CLI.
"""

import os
import logging
from typing import Dict, Tuple

import click
from rich.console import Console

from ..tool_manager import ConfigManager

# Set up logging
logger = logging.getLogger(__name__)

# Initialize console for rich output
console = Console()


def initialize_config_files(
    config_manager: ConfigManager,
) -> Tuple[str, str]:
    """
    Initialize configuration files.

    Args:
        config_manager: Configuration manager instance

    Returns:
        Tuple of (config_file_path, tools_file_path)
    """
    # Initialize configuration files
    config_file = config_manager.init_config()
    tools_file = config_manager.init_tools()

    return config_file, tools_file


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
def init(config, tools):
    """
    Initialize configuration files.

    Args:
        config: Path to configuration file
        tools: Path to tools configuration file
    """
    # Create configuration manager
    config_manager = ConfigManager(config_path=config)

    # Initialize configuration files
    config_file, tools_file = initialize_config_files(config_manager)

    # Print success message
    console.print(f"[green]Initialized configuration file: {config_file}[/]")
    console.print(f"[green]Initialized tools configuration file: {tools_file}[/]")
    console.print("\n[bold]Edit these files to configure the agent and tools.[/]")

    # Print next steps
    console.print("\n[bold]Next steps:[/]")
    console.print("1. Edit the configuration files to set your API key and other settings")
    console.print("2. Run 'smart-agent start' to start the tool services")
    console.print("3. Run 'smart-agent chat' to start chatting with the agent")
