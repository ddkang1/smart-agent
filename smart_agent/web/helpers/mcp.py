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
    from agents.mcp import MCPServerSse
    
    # Create MCP server objects
    mcp_servers = []
    
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
        
        # For SSE-based transports (stdio_to_sse, sse), use MCPServerSse
        if transport_type in ["stdio_to_sse", "sse"]:
            logger.info(f"Adding {tool_id} at {url} to agent")
            mcp_servers.append(MCPServerSse(name=tool_id, params={"url": url}))
    
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
    for server in mcp_servers:
        try:
            # Use the exit stack to ensure proper cleanup
            await exit_stack.enter_async_context(server)
            logger.info(f"Connected to MCP server: {server.name}")
            connected_servers.append(server)
        except Exception as e:
            logger.error(f"Error connecting to MCP server: {e}")
            await cl.Message(
                content=f"Error connecting to tool {server.name}: {e}",
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
