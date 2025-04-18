"""
Start command implementation for the Smart Agent CLI.
"""

import os
import time
import logging
import urllib.parse
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

        # Get the transport type first
        transport_type = tool_config.get("transport", "stdio_to_sse").lower()

        # For sse transport type, check if a command is provided
        if transport_type == "sse":
            command = config_manager.get_tool_command(tool_id)
        # For sse_to_stdio transport type, we construct the command from the URL
        elif transport_type == "sse_to_stdio":
            tool_url = tool_config.get("url")
            if tool_url:
                command = f"npx -y supergateway --sse \"{tool_url}\""
                if process_manager.debug:
                    logger.debug(f"Constructed command for sse_to_stdio transport: '{command}'")
            else:
                console.print(f"[red]No URL specified for sse_to_stdio tool {tool_id}, skipping[/]")
                console.print(f"[yellow]Please add a 'url' field to the {tool_id} configuration in your tools.yaml file[/]")
                continue
        # For all other transport types, get the command from the configuration
        else:
            command = config_manager.get_tool_command(tool_id)
            if not command:
                console.print(f"[red]No command specified for tool {tool_id}, skipping[/]")
                console.print(f"[yellow]Please add a 'command' field to the {tool_id} configuration in your tools.yaml file[/]")
                continue

        # Get the tool URL
        tool_url = tool_config.get("url", "")
        url_port = None
        url_has_port_placeholder = False
        command_port = None

        # For 'sse' transport type, try to extract port from command if it exists
        if transport_type == "sse" and command:
            # Try to extract port from command (e.g., --port 8003 or -p 8003)
            if "--port" in command:
                try:
                    port_str = command.split("--port")[1].strip().split()[0]
                    command_port = int(port_str)
                    logger.debug(f"Extracted port {command_port} from command {command}")
                except (IndexError, ValueError):
                    logger.debug(f"Could not extract port from command {command}")
            elif " -p " in command:
                try:
                    port_str = command.split(" -p ")[1].strip().split()[0]
                    command_port = int(port_str)
                    logger.debug(f"Extracted port {command_port} from command {command}")
                except (IndexError, ValueError):
                    logger.debug(f"Could not extract port from command {command}")

        # Check if URL has a port placeholder
        if "{port}" in tool_url:
            url_has_port_placeholder = True
        # Try to extract port from URL using urllib.parse for any hostname
        elif tool_url:
            try:
                # Parse the URL properly
                parsed_url = urllib.parse.urlparse(tool_url)
                # Extract port from parsed URL
                if parsed_url.port:
                    url_port = parsed_url.port
                    logger.debug(f"Extracted port {url_port} from URL {tool_url}")
                # If no explicit port in URL but hostname is present, try to extract from hostname:port format
                elif ":" in parsed_url.netloc:
                    try:
                        hostname, port_str = parsed_url.netloc.split(":", 1)
                        url_port = int(port_str)
                        logger.debug(f"Extracted port {url_port} from URL netloc {parsed_url.netloc}")
                    except (ValueError, IndexError):
                        logger.debug(f"Could not extract port from URL netloc {parsed_url.netloc}")
            except Exception as e:
                logger.debug(f"Could not extract port from URL {tool_url}: {e}")

        # Get explicitly configured port (lowest priority)
        config_port = tool_config.get("port")

        # Determine which port to use (priority: URL port > command port > config port > next available port)
        # This ensures we honor the URL port if provided
        if url_port is not None:
            port = url_port
        elif command_port is not None:
            port = command_port
        elif config_port is not None:
            port = config_port
        else:
            port = next_port
            next_port += 1
            
        # Special handling for pubmed tool which has no port argument in command
        if tool_id == "pubmed" and transport_type == "sse":
            # For pubmed, always use the port from URL if available
            if url_port is not None:
                port = url_port

        # For 'sse' transport type with a command-specified port, don't allow automatic port reassignment
        if transport_type == "sse" and command_port is not None:
            # Check if the port is already in use by another tool we started
            if any(info.get("port") == port for info in started_tools.values()):
                error_msg = f"Port {port} specified in command for {tool_id} is already in use by another tool"
                logger.error(error_msg)
                console.print(f"[red]Error: {error_msg}[/]")
                console.print(f"[yellow]Please modify the command to use a different port or stop the other tool first[/]")
                started_tools[tool_id] = {"status": "error", "error": error_msg}
                continue
        # For other transport types, check if port is already in use
        elif any(info.get("port") == port for info in started_tools.values()):
            # If URL port is specified, we should honor it and report an error if it's in use
            if url_port is not None:
                error_msg = f"Port {port} specified in URL for {tool_id} is already in use by another tool"
                logger.error(error_msg)
                console.print(f"[red]Error: {error_msg}[/]")
                console.print(f"[yellow]Please modify the URL to use a different port or stop the other tool first[/]")
                started_tools[tool_id] = {"status": "error", "error": error_msg}
                continue
            else:
                # Only use next available port if URL port wasn't specified
                logger.debug(f"Port {port} is already in use, finding next available port")
                port = next_port
                next_port += 1

        # If URL has a port placeholder, we'll update it later with the actual port
        # If URL has a hardcoded port that's different from our assigned port, log a warning
        if url_port is not None and url_port != port and not url_has_port_placeholder:
            logger.warning(f"Tool {tool_id} URL specifies port {url_port} but will run on port {port}")
            console.print(f"[yellow]Warning: Tool {tool_id} URL specifies port {url_port} but will run on port {port}[/]")

        # Get the transport type from the configuration
        transport_type = tool_config.get("transport", "stdio_to_sse").lower()

        if process_manager.debug:
            logger.debug(f"Transport type for {tool_id}: '{transport_type}'")
            logger.debug(f"Original command for {tool_id}: '{command}'")

        # Skip tool launching for 'sse' transport type only if no command is provided
        if transport_type == "sse" and not command:
            logger.info(f"Skipping launch for {tool_id} as it uses 'sse' transport type with no command (remote tool)")
            console.print(f"[yellow]Skipping tool {tool_id} (remote tool)[/]")
            continue

        # For 'stdio' transport type, we use the command directly without any modifications
        if transport_type == "stdio":
            # Use the command as is, without any modifications
            original_command = command  # Store the original command for reference
            if process_manager.debug:
                logger.debug(f"Using stdio transport with command: '{command}'")
        else:
            # For supergateway-based transport types
            # Determine if we need to add port parameters based on the command
            hostname = "localhost"
            try:
                parsed_url = urllib.parse.urlparse(tool_url)
                hostname = parsed_url.hostname or "localhost"
                if process_manager.debug:
                    logger.debug(f"Extracted hostname '{hostname}' from URL '{tool_url}'")
            except Exception as e:
                if process_manager.debug:
                    logger.debug(f"Error extracting hostname from URL '{tool_url}': {e}")

            # Handle different transport types
            if transport_type == "stdio_to_sse":
                command = f"npx -y supergateway --stdio \"{command}\" --header \"X-Accel-Buffering: no\" --port {{port}} --baseUrl http://{hostname}:{{port}} --cors"
                if process_manager.debug:
                    logger.debug(f"Using stdio_to_sse transport with command: '{command}'")
            # For 'sse' transport type, add port parameter if not present
            elif transport_type == "sse":
                # Check if command already has a port parameter
                if "--port" not in command and " -p " not in command:
                    # Add port parameter to the command
                    command = f"{command} --port {port}"
                    if process_manager.debug:
                        logger.debug(f"Added port parameter to sse command: '{command}'")
                else:
                    # Use the command as is
                    if process_manager.debug:
                        logger.debug(f"Using sse transport with command: '{command}'")
            # stdio_to_ws transport type is no longer supported
            # elif transport_type == "stdio_to_ws":
            #     command = f"npx -y supergateway --stdio \"{command}\" --outputTransport ws --port {{port}} --cors"
            #     if process_manager.debug:
            #         logger.debug(f"Using stdio_to_ws transport with command: '{command}'")
            # sse_to_stdio is handled in the command construction section above
            else:
                logger.warning(f"Unknown transport type '{transport_type}' for {tool_id}, defaulting to stdio_to_sse")
                command = f"npx -y supergateway --stdio \"{command}\" --header \"X-Accel-Buffering: no\" --port {{port}} --baseUrl http://{hostname}:{{port}} --cors"
                if process_manager.debug:
                    logger.debug(f"Using default stdio_to_sse transport with command: '{command}'")

        try:
            # For 'sse' transport type, we need to handle the process differently
            if transport_type == "sse":
                # Start the tool process with special handling for 'sse' transport type
                pid, actual_port = process_manager.start_tool_process(
                    tool_id=tool_id,
                    command=command,
                    port=port,
                    background=background,
                    redirect_io=False  # Don't redirect stdin/stdout/stderr for 'sse' transport type
                )
            else:
                # Start the tool process normally for other transport types
                pid, actual_port = process_manager.start_tool_process(
                    tool_id=tool_id,
                    command=command,
                    port=port,
                    background=background,
                )

            # Update the tool URL in the configuration only if it has a port placeholder
            if url_has_port_placeholder:
                # Replace {port} placeholder with actual port
                updated_url = tool_url.replace("{port}", str(actual_port))
                tool_config["url"] = updated_url
                logger.debug(f"Updated URL from {tool_url} to {updated_url}")
            # Don't update URLs with hardcoded ports to maintain consistency between server and client configs

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
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="Enable debug mode for verbose logging",
)
def start(config, background, debug):
    """
    Start all tool services.

    Args:
        config: Path to configuration file
        tools: Path to tools configuration file
        background: Whether to run in background
    """
    # Create configuration manager
    config_manager = ConfigManager(config_path=config)

    # Create process manager and proxy manager with debug mode if requested
    process_manager = ProcessManager(debug=debug)
    proxy_manager = ProxyManager(debug=debug)

    # Configure logging using the config_manager
    from ..cli import configure_logging
    configure_logging(config_manager)
    
    if debug:
        # Override logging level to DEBUG for all loggers
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger("smart_agent").setLevel(logging.DEBUG)
        logging.getLogger("litellm").setLevel(logging.DEBUG)
        logging.getLogger("openai").setLevel(logging.DEBUG)
        
        # Keep backoff logger at WARNING level even in debug mode
        logging.getLogger("backoff").setLevel(logging.WARNING)
        
        console.print("[yellow]Debug mode enabled. Verbose logging will be shown.[/]")

    # Check if we need to start the LiteLLM proxy
    api_base_url = config_manager.get_api_base_url()

    # Check if we should start the LiteLLM proxy
    should_start_litellm = False

    # Check if API base URL is a local address (localhost, 127.0.0.1, or 0.0.0.0)
    if api_base_url and ("localhost" in api_base_url or "127.0.0.1" in api_base_url or "0.0.0.0" in api_base_url):
        should_start_litellm = True

    # Check if LiteLLM is explicitly enabled in config
    litellm_config = config_manager.get_litellm_config()
    if litellm_config and isinstance(litellm_config, dict) and litellm_config.get("enabled", False):
        should_start_litellm = True

    if should_start_litellm:
        console.print("[bold]Starting LiteLLM proxy...[/]")

        # Check if the proxy is already running
        proxy_status = proxy_manager.get_litellm_proxy_status()

        if proxy_status["running"]:
            console.print(f"[green]LiteLLM proxy is already running on port {proxy_status['port']}[/]")
            pid = 999999  # Dummy PID
        else:
            # If the container exists but is not running, restart it
            if proxy_status["container_id"]:
                console.print(f"[yellow]LiteLLM proxy container exists but is not running. Restarting...[/]")
                pid = proxy_manager.restart_litellm_proxy(config_manager, background)
            else:
                # Otherwise, launch a new container
                pid = proxy_manager.launch_litellm_proxy(config_manager, background)

        if pid:
            console.print(f"[green]LiteLLM proxy started successfully[/]")
        else:
            console.print(f"[yellow]Warning: LiteLLM proxy may not have started properly[/]")

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
