"""
Stop command implementation for the Smart Agent CLI.
"""

import os
import logging
from typing import Dict, List, Optional, Any

import click
from rich.console import Console

from ..tool_manager import ConfigManager
from ..process_manager import ProcessManager
from ..proxy_manager import ProxyManager

# Set up logging
logger = logging.getLogger(__name__)

# Initialize console for rich output
console = Console()


def stop_tools(
    config_manager: ConfigManager,
    process_manager: ProcessManager,
) -> Dict[str, bool]:
    """
    Stop tool processes.

    Args:
        config_manager: Configuration manager instance
        process_manager: Process manager instance

    Returns:
        Dictionary mapping tool IDs to success status
    """
    # Get tools configuration
    tools_config = config_manager.get_tools_config()

    # Track stopped tools
    stopped_tools = {}

    # Stop each enabled tool
    for tool_id, tool_config in tools_config.items():
        if not tool_config.get("enabled", False):
            logger.debug(f"Tool {tool_id} is not enabled, skipping")
            continue

        # Check if the tool is running
        if not process_manager.is_tool_running(tool_id):
            console.print(f"[yellow]Tool {tool_id} is not running[/]")
            stopped_tools[tool_id] = False
            continue

        try:
            # Stop the tool process
            success = process_manager.stop_tool_process(tool_id)
            if success:
                console.print(f"[green]Stopped tool {tool_id}[/]")
            else:
                console.print(f"[yellow]Failed to stop tool {tool_id}[/]")
            stopped_tools[tool_id] = success
        except Exception as e:
            console.print(f"[red]Error stopping tool {tool_id}: {e}[/]")
            stopped_tools[tool_id] = False

    return stopped_tools


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
    "--all",
    is_flag=True,
    help="Stop all processes, including those not in the configuration",
)
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="Enable debug mode for verbose logging",
)
def stop(config, tools, all, debug):
    """
    Stop all tool services.

    Args:
        config: Path to configuration file
        tools: Path to tools configuration file
        all: Stop all processes, including those not in the configuration
    """
    # Create configuration manager
    config_manager = ConfigManager(config_path=config)

    # Create process manager and proxy manager with debug mode if requested
    process_manager = ProcessManager(debug=debug)
    proxy_manager = ProxyManager(debug=debug)

    if debug:
        # Set up logging for debugging
        logging.basicConfig(level=logging.DEBUG)
        logger = logging.getLogger("smart_agent")
        logger.setLevel(logging.DEBUG)
        console.print("[yellow]Debug mode enabled. Verbose logging will be shown.[/]")

    # Stop tools
    console.print("[bold]Stopping tool services...[/]")

    if all:
        # Stop all processes
        results = process_manager.stop_all_processes()

        # Print summary
        console.print("\n[bold]Tool services summary:[/]")
        for tool_id, success in results.items():
            if success:
                console.print(f"[green]{tool_id}: Stopped[/]")
            else:
                console.print(f"[yellow]{tool_id}: Failed to stop[/]")
    else:
        # Stop configured tools
        stopped_tools = stop_tools(config_manager, process_manager)

        # Print summary
        console.print("\n[bold]Tool services summary:[/]")
        for tool_id, success in stopped_tools.items():
            if success:
                console.print(f"[green]{tool_id}: Stopped[/]")
            else:
                console.print(f"[yellow]{tool_id}: Failed to stop[/]")

    # Stop LiteLLM proxy
    console.print("\n[bold]Stopping LiteLLM proxy...[/]")
    if proxy_manager.stop_litellm_proxy():
        console.print("[green]LiteLLM proxy stopped successfully[/]")
    else:
        console.print("[yellow]LiteLLM proxy was not running or failed to stop[/]")