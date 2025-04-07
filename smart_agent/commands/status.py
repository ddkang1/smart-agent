"""
Status command implementation for the Smart Agent CLI.
"""

import logging
from typing import Dict, Any

import click
from rich.console import Console
from rich.table import Table

from ..tool_manager import ConfigManager
from ..process_manager import ProcessManager
from ..proxy_manager import ProxyManager

# Set up logging
logger = logging.getLogger(__name__)

# Initialize console for rich output
console = Console()


def get_litellm_proxy_status(proxy_manager: ProxyManager) -> Dict[str, Any]:
    """
    Get the status of the LiteLLM proxy.

    Args:
        proxy_manager: Proxy manager instance

    Returns:
        Dictionary with LiteLLM proxy status information
    """
    return proxy_manager.get_litellm_proxy_status()


def get_tools_status(
    config_manager: ConfigManager,
    process_manager: ProcessManager,
) -> Dict[str, Any]:
    """
    Get the status of all tool services.

    Args:
        config_manager: Configuration manager instance
        process_manager: Process manager instance

    Returns:
        Dictionary with tool status information
    """
    # Get tools configuration
    tools_config = config_manager.get_tools_config()

    # Track tool status
    tools_status = {}

    # Check status of each tool
    for tool_id, tool_config in tools_config.items():
        enabled = tool_config.get("enabled", False)

        # Get the transport type
        transport_type = tool_config.get("transport", "stdio_to_sse").lower()

        # Basic status
        status = {
            "enabled": enabled,
            "name": tool_config.get("name", tool_id),
            "description": tool_config.get("description", ""),
            "transport": transport_type,
        }

        # Skip detailed status for disabled tools
        if not enabled:
            status["running"] = False
            tools_status[tool_id] = status
            continue

        # Handle different transport types
        if transport_type == "sse":
            # For 'sse' transport type, we don't need to check if it's running
            status["running"] = True  # Assume it's always running
            status["url"] = tool_config.get("url", "")
        else:
            # Check if the tool is running
            running = process_manager.is_tool_running(tool_id)
            status["running"] = running

            if running:
                # For 'stdio' and 'sse_to_stdio' transport types, we don't need port information
                if transport_type not in ["stdio", "sse_to_stdio"]:
                    # Get additional information for running tools
                    port = process_manager.get_tool_port(tool_id)
                    status["port"] = port

                    # Get the tool URL
                    url = tool_config.get("url", "")
                    if url and "{port}" in url and port:
                        url = url.replace("{port}", str(port))
                    status["url"] = url
                else:
                    # For stdio transport, URL is irrelevant
                    status["url"] = ""  # No URL for stdio transport

                    # For sse_to_stdio, we might want to show the remote URL
                    if transport_type == "sse_to_stdio":
                        status["remote_url"] = tool_config.get("url", "")

        tools_status[tool_id] = status

    return tools_status


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
    "--json",
    is_flag=True,
    help="Output in JSON format",
)
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="Enable debug mode for verbose logging",
)
def status(config, tools, json, debug):
    """
    Show the status of all services.

    Args:
        config: Path to configuration file
        tools: Path to tools configuration file
        json: Output in JSON format
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

    # Get tools status
    tools_status = get_tools_status(config_manager, process_manager)

    # Get LiteLLM proxy status
    litellm_status = get_litellm_proxy_status(proxy_manager)

    # Combine status information
    all_status = {
        "tools": tools_status,
        "litellm": litellm_status
    }

    # Output in JSON format if requested
    if json:
        import json as json_lib
        console.print(json_lib.dumps(all_status, indent=2))
        return

    # Show LiteLLM proxy status
    if litellm_status["running"]:
        console.print(f"[bold green]LiteLLM Proxy:[/] Running on port {litellm_status['port']}")
    else:
        console.print("[bold yellow]LiteLLM Proxy:[/] Not running")
    console.print()

    # Create a table for the tools output
    table = Table(title="Tool Services Status")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="magenta")
    table.add_column("Enabled", style="green")
    table.add_column("Running", style="green")
    table.add_column("Transport", style="blue")
    table.add_column("Port", style="blue")
    table.add_column("URL/Remote URL", style="yellow")

    # Add rows to the table
    for tool_id, status in tools_status.items():
        enabled = "✓" if status.get("enabled", False) else "✗"
        running = "✓" if status.get("running", False) else "✗"
        transport = status.get("transport", "stdio_to_sse")
        port = str(status.get("port", "")) if status.get("running", False) else ""
        # Get URL or remote URL
        url = ""
        if status.get("running", False):
            if status.get("transport") == "sse_to_stdio":
                url = status.get("remote_url", "")
            else:
                url = status.get("url", "")

        table.add_row(
            tool_id,
            status.get("name", tool_id),
            enabled,
            running,
            transport,
            port,
            url,
        )

    # Print the table
    console.print(table)
