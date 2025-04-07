"""
Start command implementation for the Smart Agent CLI.
"""

import os
import time
import logging
from typing import Dict, List, Optional, Any

import click
from rich.console import Console

from ..tool_manager import ConfigManager
from ..process_manager import ProcessManager

# Set up logging
logger = logging.getLogger(__name__)

# Initialize console for rich output
console = Console()


def start_tools(
    config_manager: ConfigManager,
    process_manager: ProcessManager,
    background: bool = True,
) -> Dict[str, Any]:
    """
    Start tool processes.

    Args:
        config_manager: Configuration manager instance
        process_manager: Process manager instance
        background: Whether to run in background

    Returns:
        Dictionary with tool status information
    """
    # Get tools configuration
    tools_config = config_manager.get_tools_config()

    # Track started tools
    started_tools = {}

    # Start each enabled tool
    for tool_id, tool_config in tools_config.items():
        if not tool_config.get("enabled", False):
            logger.debug(f"Tool {tool_id} is not enabled, skipping")
            continue

        # Check if the tool is already running
        if process_manager.is_tool_running(tool_id):
            port = process_manager.get_tool_port(tool_id)
            console.print(f"[yellow]Tool {tool_id} is already running on port {port}[/]")
            started_tools[tool_id] = {"status": "already_running", "port": port}
            continue

        # Get the tool command
        command = tool_config.get("command")
        if not command:
            console.print(f"[red]No command specified for tool {tool_id}, skipping[/]")
            continue

        # Get the tool port
        port = tool_config.get("port")

        try:
            # Start the tool process
            pid, actual_port = process_manager.start_tool_process(
                tool_id=tool_id,
                command=command,
                port=port,
                background=background,
            )

            # Update the tool URL in the configuration
            tool_url = tool_config.get("url", "")
            if tool_url and "{port}" in tool_url:
                tool_url = tool_url.replace("{port}", str(actual_port))
                tool_config["url"] = tool_url

            console.print(f"[green]Started tool {tool_id} with PID {pid} on port {actual_port}[/]")
            started_tools[tool_id] = {
                "status": "started",
                "pid": pid,
                "port": actual_port,
                "url": tool_url,
            }

            # Wait a moment to allow the tool to start
            time.sleep(1)
        except Exception as e:
            console.print(f"[red]Error starting tool {tool_id}: {e}[/]")
            started_tools[tool_id] = {"status": "error", "error": str(e)}

    return started_tools


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
    "--background/--no-background",
    default=True,
    help="Run in background",
)
def start(config, tools, background):
    """
    Start all tool services.

    Args:
        config: Path to configuration file
        tools: Path to tools configuration file
        background: Whether to run in background
    """
    # Create configuration manager
    config_manager = ConfigManager(config_path=config)

    # Create process manager
    process_manager = ProcessManager()

    # Check if we need to start the LiteLLM proxy
    api_base_url = config_manager.get_api_base_url()
    if api_base_url and ("localhost" in api_base_url or "127.0.0.1" in api_base_url):
        from ..commands.setup import launch_litellm_proxy
        launch_litellm_proxy(config_manager, background)

    # Start tools
    console.print("[bold]Starting tool services...[/]")
    started_tools = start_tools(config_manager, process_manager, background)

    # Print summary
    console.print("\n[bold]Tool services summary:[/]")
    for tool_id, info in started_tools.items():
        status = info.get("status")
        if status == "started":
            console.print(f"[green]{tool_id}: Started on port {info.get('port')}[/]")
        elif status == "already_running":
            console.print(f"[yellow]{tool_id}: Already running on port {info.get('port')}[/]")
        elif status == "error":
            console.print(f"[red]{tool_id}: Error - {info.get('error')}[/]")
        else:
            console.print(f"[yellow]{tool_id}: Unknown status[/]")
