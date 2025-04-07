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

# Set up logging
logger = logging.getLogger(__name__)

# Initialize console for rich output
console = Console()


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
        
        # Basic status
        status = {
            "enabled": enabled,
            "name": tool_config.get("name", tool_id),
            "description": tool_config.get("description", ""),
        }
        
        # Skip detailed status for disabled tools
        if not enabled:
            status["running"] = False
            tools_status[tool_id] = status
            continue
            
        # Check if the tool is running
        running = process_manager.is_tool_running(tool_id)
        status["running"] = running
        
        if running:
            # Get additional information for running tools
            port = process_manager.get_tool_port(tool_id)
            status["port"] = port
            
            # Get the tool URL
            url = tool_config.get("url", "")
            if url and "{port}" in url and port:
                url = url.replace("{port}", str(port))
            status["url"] = url
            
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
def status(config, tools, json):
    """
    Show the status of all services.

    Args:
        config: Path to configuration file
        tools: Path to tools configuration file
        json: Output in JSON format
    """
    # Create configuration manager
    config_manager = ConfigManager(config_path=config, tools_path=tools)
    
    # Create process manager
    process_manager = ProcessManager()
    
    # Get tools status
    tools_status = get_tools_status(config_manager, process_manager)
    
    # Output in JSON format if requested
    if json:
        import json as json_lib
        console.print(json_lib.dumps(tools_status, indent=2))
        return
    
    # Create a table for the output
    table = Table(title="Tool Services Status")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="magenta")
    table.add_column("Enabled", style="green")
    table.add_column("Running", style="green")
    table.add_column("Port", style="blue")
    table.add_column("URL", style="yellow")
    
    # Add rows to the table
    for tool_id, status in tools_status.items():
        enabled = "✓" if status.get("enabled", False) else "✗"
        running = "✓" if status.get("running", False) else "✗"
        port = str(status.get("port", "")) if status.get("running", False) else ""
        url = status.get("url", "") if status.get("running", False) else ""
        
        table.add_row(
            tool_id,
            status.get("name", tool_id),
            enabled,
            running,
            port,
            url,
        )
    
    # Print the table
    console.print(table)
