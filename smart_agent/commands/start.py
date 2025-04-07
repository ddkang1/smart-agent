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
    start_port: int = 8000,
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

    # Track the next available port
    next_port = start_port

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
        command = config_manager.get_tool_command(tool_id)
        if not command:
            console.print(f"[red]No command specified for tool {tool_id}, skipping[/]")
            console.print(f"[yellow]Please add a 'command' field to the {tool_id} configuration in your tools.yaml file[/]")
            continue

        # Get the tool URL
        tool_url = tool_config.get("url", "")
        url_port = None
        url_has_port_placeholder = False

        # Check if URL has a port placeholder
        if "{port}" in tool_url:
            url_has_port_placeholder = True
        # Try to extract port from URL if it's a localhost URL
        elif tool_url and ("localhost:" in tool_url or "127.0.0.1:" in tool_url):
            try:
                # Extract port from URL (e.g., http://localhost:8000/sse)
                if "localhost:" in tool_url:
                    port_str = tool_url.split("localhost:")[1].split("/")[0]
                else:  # 127.0.0.1:
                    port_str = tool_url.split("127.0.0.1:")[1].split("/")[0]
                url_port = int(port_str)
                logger.debug(f"Extracted port {url_port} from URL {tool_url}")
            except (IndexError, ValueError):
                logger.debug(f"Could not extract port from URL {tool_url}")

        # Get explicitly configured port (lowest priority)
        config_port = tool_config.get("port")

        # Determine which port to use (priority: URL port > config port > next available port)
        if url_port is not None:
            port = url_port
        elif config_port is not None:
            port = config_port
        else:
            port = next_port
            next_port += 1

        # If the port is already in use by another tool we started, use the next available port
        if any(info.get("port") == port for info in started_tools.values()):
            logger.debug(f"Port {port} is already in use, finding next available port")
            port = next_port
            next_port += 1

        # If URL has a port placeholder, we'll update it later with the actual port
        # If URL has a hardcoded port that's different from our assigned port, log a warning
        if url_port is not None and url_port != port and not url_has_port_placeholder:
            logger.warning(f"Tool {tool_id} URL specifies port {url_port} but will run on port {port}")
            console.print(f"[yellow]Warning: Tool {tool_id} URL specifies port {url_port} but will run on port {port}[/]")

        # Determine if we need to add port parameters based on the command

        # Modify command to include port parameter if needed
        if "docker" in command.lower():
            # For Docker commands, add port mapping
            if "-p" not in command:
                command = command.replace("docker run", f"docker run -p {{port}}:{{port}}")
        elif "--port" not in command and "-p" not in command:
            # For other commands, add --port parameter if not present
            command = f"{command} --port {{port}}"

        try:
            # Start the tool process
            pid, actual_port = process_manager.start_tool_process(
                tool_id=tool_id,
                command=command,
                port=port,
                background=background,
            )

            # Update the tool URL in the configuration
            if url_has_port_placeholder:
                # Replace {port} placeholder with actual port
                updated_url = tool_url.replace("{port}", str(actual_port))
                tool_config["url"] = updated_url
                logger.debug(f"Updated URL from {tool_url} to {updated_url}")
            elif url_port is not None and url_port != actual_port:
                # If URL had a hardcoded port that's different from the actual port, update it
                if "localhost:" in tool_url:
                    updated_url = tool_url.replace(f"localhost:{url_port}", f"localhost:{actual_port}")
                else:  # 127.0.0.1:
                    updated_url = tool_url.replace(f"127.0.0.1:{url_port}", f"127.0.0.1:{actual_port}")
                tool_config["url"] = updated_url
                logger.debug(f"Updated URL from {tool_url} to {updated_url}")

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
    "--background/--no-background",
    default=True,
    help="Run in background",
)
def start(config, background):
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
    started_tools = start_tools(config_manager, process_manager, background, start_port=8000)

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
