"""
Setup command implementation for the Smart Agent CLI.
"""

import os
import logging
from typing import Dict, Any, Optional

import click
from rich.console import Console

from ..tool_manager import ConfigManager

# Set up logging
logger = logging.getLogger(__name__)

# Initialize console for rich output
console = Console()


def launch_litellm_proxy(
    config_manager: ConfigManager,
    background: bool = True,
) -> Optional[int]:
    """
    Launch the LiteLLM proxy.

    Args:
        config_manager: Configuration manager instance
        background: Whether to run in background

    Returns:
        Process ID if successful, None otherwise
    """
    # Get LiteLLM configuration
    litellm_config = config_manager.get_litellm_config()

    # Check if LiteLLM is enabled
    if not litellm_config.get("enabled", False):
        logger.debug("LiteLLM proxy is not enabled, skipping")
        return None

    # Get the command
    command = litellm_config.get("command")
    if not command:
        console.print("[red]No command specified for LiteLLM proxy, skipping[/]")
        return None

    # Get the port
    port = litellm_config.get("port", 4000)

    try:
        # Start the process
        import subprocess

        # Replace {port} in the command
        command = command.replace("{port}", str(port))

        # Start the process
        if background:
            # Use platform-specific approach for background processes
            import platform
            if platform.system() == "Windows":
                # Windows approach
                process = subprocess.Popen(
                    command,
                    shell=True,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                )
            else:
                # Unix approach - ensure process is fully detached
                # Use nohup and disown to ensure the process continues running even if the terminal is closed
                detached_command = f"nohup {command} > /dev/null 2>&1 & disown"
                process = subprocess.Popen(
                    detached_command,
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL  # Close stdin to prevent any interaction
                )
        else:
            # Foreground process
            process = subprocess.Popen(command, shell=True)

        # Get the PID
        pid = process.pid

        console.print(f"[green]Started LiteLLM proxy with PID {pid} on port {port}[/]")
        return pid
    except Exception as e:
        console.print(f"[red]Error starting LiteLLM proxy: {e}[/]")
        return None


@click.command()
@click.option(
    "--config",
    default=None,
    help="Path to configuration file",
)
@click.option(
    "--background/--no-background",
    default=True,
    help="Run in background",
)
def setup(config, background):
    """
    Set up the Smart Agent environment.

    Args:
        config: Path to configuration file
        background: Whether to run in background
    """
    # Create configuration manager
    config_manager = ConfigManager(config_path=config)

    # Launch LiteLLM proxy
    console.print("[bold]Setting up Smart Agent environment...[/]")
    pid = launch_litellm_proxy(config_manager, background)

    if pid:
        console.print(f"[green]LiteLLM proxy started with PID {pid}[/]")
    else:
        console.print("[yellow]LiteLLM proxy not started[/]")

    # Print next steps
    console.print("\n[bold]Next steps:[/]")
    console.print("1. Run 'smart-agent start' to start the tool services")
    console.print("2. Run 'smart-agent chat' to start chatting with the agent")
