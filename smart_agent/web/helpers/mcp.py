
"""Helper functions for MCP server management."""

import logging
import chainlit as cl
from contextlib import AsyncExitStack

logger = logging.getLogger(__name__)

async def initialize_mcp_servers(config_manager):
    """Initialize and connect to MCP servers.
    
    Args:
        config_manager: The configuration manager instance
        
    Returns:
        tuple: (exit_stack, connected_servers) or (None, None) if no servers could be connected
    """
    from agents.mcp import MCPServerStdio
    from smart_agent.web.helpers.reconnecting_mcp import ReconnectingMCP
    import asyncio
    import traceback
    
    # Create MCP server objects
    mcp_servers = []
    exit_stack = None
    
    try:
        # Get enabled tools
        for tool_id, tool_config in config_manager.get_tools_config().items():
            if not config_manager.is_tool_enabled(tool_id):
                continue
            
            transport_type = tool_config.get("transport", "stdio_to_sse").lower()
            url = tool_config.get("url")
            
            # Check if we have a URL (required for client-only mode)
            if not url:
                logger.warning(f"Tool {tool_id} has no URL and will be skipped.")
                continue
            
            # For SSE-based transports (stdio_to_sse, sse), use ReconnectingMCP
            if transport_type in ["stdio_to_sse", "sse"]:
                # Get reconnection configuration parameters if available
                max_reconnect_attempts = tool_config.get("max_reconnect_attempts", 10)
                reconnect_base_delay = tool_config.get("reconnect_base_delay", 1.0)
                reconnect_max_delay = tool_config.get("reconnect_max_delay", 60.0)
                ping_interval = tool_config.get("ping_interval", 5.0)
                
                logger.info(f"Adding {tool_id} at {url} to agent with reconnection capability "
                           f"(max_attempts={max_reconnect_attempts}, base_delay={reconnect_base_delay}s, "
                           f"max_delay={reconnect_max_delay}s, ping_interval={ping_interval}s)")
                
                mcp_servers.append(ReconnectingMCP(
                    name=tool_id,
                    params={"url": url},
                    max_reconnect_attempts=max_reconnect_attempts,
                    reconnect_base_delay=reconnect_base_delay,
                    reconnect_max_delay=reconnect_max_delay,
                    ping_interval=ping_interval
                ))
            # For stdio transport, use MCPServerStdio with the command directly
            elif transport_type == "stdio":
                command = tool_config.get("command")
                if command:
                    # For MCPServerStdio, we need to split the command into command and args
                    command_parts = command.split()
                    executable = command_parts[0]
                    args = command_parts[1:] if len(command_parts) > 1 else []
                    logger.info(f"Adding {tool_id} with command '{command}' to agent (stdio)")
                    mcp_servers.append(MCPServerStdio(name=tool_id, params={
                        "command": executable,
                        "args": args
                    }))
            # For sse_to_stdio transport, always construct the command from the URL
            elif transport_type == "sse_to_stdio":
                # Get the URL from the configuration
                if url:
                    # Construct the full supergateway command
                    command = f"npx -y supergateway --sse \"{url}\""
                    logger.debug(f"Constructed command for sse_to_stdio transport: '{command}'")
                    # For MCPServerStdio, we need to split the command into command and args
                    command_parts = command.split()
                    executable = command_parts[0]
                    args = command_parts[1:] if len(command_parts) > 1 else []
                    logger.info(f"Adding {tool_id} with supergateway to agent (sse_to_stdio)")
                    mcp_servers.append(MCPServerStdio(name=tool_id, params={
                        "command": executable,
                        "args": args
                    }))
                else:
                    logger.warning(f"Missing URL for sse_to_stdio transport type for tool {tool_id}")
        
        # Check if we have any MCP servers
        if not mcp_servers:
            await cl.Message(
                content="No tools are enabled or available. Please check your configuration.",
                author="System"
            ).send()
            return None, None
        
        # Create an AsyncExitStack to manage server connections
        exit_stack = AsyncExitStack()
        
        # Connect to MCP servers using the exit stack
        connected_servers = []
        connection_timeout = 10  # 10 seconds timeout for connections
        
        for server in mcp_servers:
            try:
                # Create a task for the connection attempt
                connection_task = asyncio.create_task(exit_stack.enter_async_context(server))
                
                # Wait for the connection with timeout
                try:
                    await asyncio.wait_for(connection_task, timeout=connection_timeout)
                    logger.info(f"Connected to MCP server: {server.name}")
                    connected_servers.append(server)
                except asyncio.TimeoutError:
                    # Cancel the connection task if it times out
                    connection_task.cancel()
                    try:
                        await connection_task
                    except asyncio.CancelledError:
                        pass
                    except Exception as cancel_error:
                        logger.debug(f"Error during connection task cancellation: {cancel_error}")
                    
                    logger.error(f"Timeout connecting to MCP server {server.name} after {connection_timeout} seconds")
                    await cl.Message(
                        content=f"Timeout connecting to tool {server.name} after {connection_timeout} seconds",
                        author="System"
                    ).send()
            except asyncio.CancelledError:
                logger.error(f"Connection to MCP server {server.name} was cancelled")
                # Don't send a message for cancellation as it might be part of cleanup
            except Exception as e:
                logger.error(f"Error connecting to MCP server {server.name}: {e}")
                # Extract more detailed error information if possible
                error_details = str(e)
                if "TaskGroup" in error_details:
                    try:
                        # Try to get the first sub-exception if it's a TaskGroup error
                        tb = traceback.format_exc()
                        logger.debug(f"Full traceback for {server.name}: {tb}")
                        error_details = f"{error_details} - See logs for details"
                    except Exception:
                        pass
                
                await cl.Message(
                    content=f"Error connecting to tool {server.name}: {error_details}",
                    author="System"
                ).send()
                # Don't return here, continue with other servers
        
        # Check if we have any connected servers
        if not connected_servers:
            await cl.Message(
                content="Could not connect to any tools. Please check your configuration.",
                author="System"
            ).send()
            # Close the exit stack to clean up any resources
            if exit_stack:
                try:
                    await exit_stack.aclose()
                except Exception as e:
                    # Ignore the error and just log it at debug level
                    logger.debug(f"Ignoring error during cleanup: {e}")
            return None, None
        
        return exit_stack, connected_servers
        
    except Exception as e:
        # logger.exception(f"Error initializing MCP servers: {e}")
        # await cl.Message(
        #     content=f"Error initializing tools: {str(e)}",
        #     author="System"
        # ).send()
        # Clean up resources if an error occurs
        if exit_stack:
            try:
                await exit_stack.aclose()
            except Exception as cleanup_e:
                logger.debug(f"Error during cleanup after initialization error: {cleanup_e}")
        return None, []
    
    # Check if we have any connected servers
    if not connected_servers:
        await cl.Message(
            content="Could not connect to any tools. Please check your configuration.",
            author="System"
        ).send()
        # Close the exit stack to clean up any resources
        try:
            await exit_stack.aclose()
        except Exception as e:
            # Ignore the error and just log it at debug level
            logger.debug(f"Ignoring error during cleanup: {e}")
        return None, None
    
    return exit_stack, connected_servers


async def safely_close_exit_stack(exit_stack):
    """Safely close an AsyncExitStack, ignoring specific errors.
    
    Args:
        exit_stack: The AsyncExitStack to close
    """
    if exit_stack is None:
        return
        
    logger.info("Closing exit stack...")
    try:
        await exit_stack.aclose()
        logger.info("Exit stack closed successfully")
    except RuntimeError as e:
        # For RuntimeError related to cancel scopes, just log at debug level
        if "cancel scope" in str(e):
            logger.debug(f"Ignoring cancel scope error during cleanup: {e}")
        else:
            # For other RuntimeErrors, log at warning level
            logger.warning(f"RuntimeError during cleanup: {e}")
    except Exception as e:
        # Ignore other errors and just log them at debug level
        logger.debug(f"Ignoring error during cleanup: {e}")
