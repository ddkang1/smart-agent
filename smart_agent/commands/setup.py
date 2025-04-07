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
    Launch LiteLLM proxy using Docker.

    Args:
        config_manager: Configuration manager instance
        background: Whether to run in background

    Returns:
        Process ID if successful, None otherwise
    """
    console.print("[bold]Launching LiteLLM proxy using Docker...[/]")

    # Check if container already exists and is running
    container_name = "smart-agent-litellm-proxy"
    try:
        import subprocess
        result = subprocess.run(
            ["docker", "ps", "-q", "-f", f"name={container_name}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

        if result.stdout.strip():
            console.print(f"[green]LiteLLM proxy container '{container_name}' is already running.[/]")
            # Return a dummy PID to indicate success
            return 999999  # Using a large number that's unlikely to be a real PID
    except Exception as e:
        console.print(f"[yellow]Warning: Error checking for existing LiteLLM proxy container: {str(e)}[/]")

    # Get LiteLLM config path
    try:
        litellm_config_path = config_manager.get_litellm_config_path()
    except Exception as e:
        litellm_config_path = None
        console.print(f"[yellow]Warning: Could not get LiteLLM config path: {str(e)}[/]")

    # Get API settings
    api_base_url = config_manager.get_api_base_url() or "http://localhost:4000"
    api_port = 4000

    try:
        from urllib.parse import urlparse
        parsed_url = urlparse(api_base_url)
        if parsed_url.port:
            api_port = parsed_url.port
    except Exception:
        pass  # Use default port

    # Create command
    cmd = [
        "docker",
        "run",
        "-d",  # Run as daemon
        "-p",
        f"{api_port}:{api_port}",
        "--name",
        container_name,
    ]

    # Add volume if we have a config file
    if litellm_config_path and os.path.exists(litellm_config_path):
        # Mount the config file directly to /app/config.yaml as in docker-compose
        cmd.extend([
            "-v",
            f"{litellm_config_path}:/app/config.yaml",
        ])

        # Add image
        cmd.append("ghcr.io/berriai/litellm:litellm_stable_release_branch-stable")

        # Add command line arguments as in docker-compose
        cmd.extend([
            "--config", "/app/config.yaml",
            "--port", str(api_port),
            "--num_workers", "8"
        ])
    else:
        # Add image only if no config file
        cmd.append("ghcr.io/berriai/litellm:litellm_stable_release_branch-stable")
        # Add port argument
        cmd.extend(["--port", str(api_port)])

    # Print the command for debugging
    logger.debug(f"Launching LiteLLM proxy with command: {' '.join(cmd)}")
    console.print(f"[dim]Command: {' '.join(cmd)}[/]")

    # Run command
    try:
        if background:
            # Start the process in the background
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL
            )
        else:
            # Start in foreground for debugging
            process = subprocess.Popen(cmd)

        # Get the PID
        pid = process.pid

        # Save the PID
        if pid:
            pid_file = os.path.join(os.path.expanduser("~"), ".litellm_proxy_pid")
            with open(pid_file, "w") as f:
                f.write(str(pid))

        console.print(f"[green]Started LiteLLM proxy with PID {pid} on port {api_port}[/]")
        return pid
    except Exception as e:
        console.print(f"[red]Error launching LiteLLM proxy: {str(e)}[/]")
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
