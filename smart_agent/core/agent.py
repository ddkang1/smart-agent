"""
Base SmartAgent class for Smart Agent.

This module provides the base SmartAgent class that can be extended
for different interfaces (CLI, web, etc.).
"""

# Apply httpcore patches early to fix async generator issues
try:
    from smart_agent.web.httpcore_patch import patch_httpcore, suppress_async_warnings
except ImportError:
    # If patch module isn't available, continue without it
    pass

import asyncio
import json
import logging
import sys
from typing import List, Dict, Any, Optional
from contextlib import AsyncExitStack
from collections import deque
from abc import abstractmethod

# Set up logging
logger = logging.getLogger(__name__)

# Configure OpenAI client logger to suppress retry messages
openai_logger = logging.getLogger("openai")
openai_logger.setLevel(logging.WARNING)

# Configure MCP client logger to suppress verbose messages
mcp_client_logger = logging.getLogger("mcp.client")
mcp_client_logger.setLevel(logging.WARNING)

# Import OpenAI agents components
from agents import Agent, Runner, set_tracing_disabled, ItemHelpers
from agents.mcp import MCPServer
from agents import OpenAIChatCompletionsModel
set_tracing_disabled(disabled=True)

# Import our custom MCP server implementations
from .mcp_server import MCPServerSse, MCPServerStdio, MCPServerStreamableHttp

# Import OpenAI client
from openai import AsyncOpenAI

# Import Smart Agent components
from ..tool_manager import ConfigManager
from ..agent import PromptGenerator


class BaseSmartAgent:
    """
    Base OpenAI MCP Chat class that combines OpenAI agents with MCP connection management.
    
    This class provides the core functionality for interacting with OpenAI models and MCP servers.
    It is designed to be subclassed for specific interfaces (CLI, web, etc.).
    """
    
    # Track whether cleanup has been performed
    _cleanup_done = False

    def __init__(self, config_manager: ConfigManager):
        """
        Initialize the Base Smart Agent.

        Args:
            config_manager: Configuration manager instance
        """
        self.config_manager = config_manager
        self.api_key = config_manager.get_api_key()
        self.base_url = config_manager.get_api_base_url()
        self.model_name = config_manager.get_model_name()
        self.temperature = config_manager.get_model_temperature()
        self.mcp_servers = []
        self.conversation_history = []
        self.system_prompt = PromptGenerator.create_system_prompt()
        
        # Get Langfuse configuration
        self.langfuse_config = config_manager.get_langfuse_config()
        self.langfuse_enabled = self.langfuse_config.get("enabled", False)
        self.langfuse = None
        
        # Initialize Langfuse if enabled
        if self.langfuse_enabled:
            try:
                from langfuse import Langfuse
                
                self.langfuse = Langfuse(
                    public_key=self.langfuse_config.get("public_key", ""),
                    secret_key=self.langfuse_config.get("secret_key", ""),
                    host=self.langfuse_config.get("host", "https://cloud.langfuse.com"),
                )
                logger.info("Langfuse monitoring enabled")
            except ImportError:
                logger.warning("Langfuse package not installed. Run 'pip install langfuse' to enable monitoring.")
                self.langfuse_enabled = False
        
        # Initialize AsyncOpenAI client with proper connection management
        import httpx
        
        # Create a custom HTTP client that completely avoids streaming issues
        # by using a simpler configuration without connection pooling
        self._http_client = None  # Don't use custom HTTP client to avoid streaming issues
        
        self.openai_client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            max_retries=3,
            timeout=30.0,
            # Don't pass custom http_client - let OpenAI use its own default
        )
        
        # Initialize MCP servers list but don't connect yet
        self._setup_mcp_servers()
        
    async def connect(self, validate=False, force=False):
        """
        Asynchronously connect the agent, including connecting to MCP servers.
        This method should be called after creating the agent instance.
        If a connection error occurs, it will recreate the server with the same arguments
        and try to connect again.
        """
        
        if force:
            self.mcp_servers = []
            self._setup_mcp_servers()

        for i, server in enumerate(self.mcp_servers[:]):  # Create a copy of the list to iterate
            server_name = getattr(server, 'name', 'unknown')
            
            try:
                logger.debug(f"Connecting to MCP server: {server_name}")
                await server.connect()
                if validate:
                    await server.list_tools()
                logger.debug(f"Connected to MCP server: {server_name}")

            except Exception as e:
                logger.error(f"Error connecting to MCP server {server_name}: {e}")
                
                # Attempt to recreate the server with the same arguments
                try:
                    logger.info(f"Recreating MCP server {server_name} after connection error")
                    
                    # Create a new server of the same type with the same parameters
                    new_server = None
                    
                    # Determine server type and recreate accordingly
                    if isinstance(server, MCPServerSse):
                        new_server = MCPServerSse(
                            name=server.name,
                            params=server.params,
                            client_session_timeout_seconds=server.client_session_timeout_seconds
                        )
                    elif isinstance(server, MCPServerStdio):
                        new_server = MCPServerStdio(
                            name=server.name,
                            params=server.params,
                            client_session_timeout_seconds=server.client_session_timeout_seconds
                        )
                    elif isinstance(server, MCPServerStreamableHttp):
                        new_server = MCPServerStreamableHttp(
                            name=server.name,
                            params=server.params,
                            client_session_timeout_seconds=server.client_session_timeout_seconds
                        )
                    
                    if new_server:
                        # Replace the old server with the new one
                        self.mcp_servers[i] = new_server
                        
                        # Try to connect with the new server
                        logger.debug(f"Attempting to connect with recreated MCP server: {server_name}")
                        await new_server.connect()
                        logger.debug(f"Successfully connected to recreated MCP server: {server_name}")
                    else:
                        logger.error(f"Failed to recreate MCP server {server_name}: Unknown server type")
                        
                except Exception as e2:
                    logger.error(f"Error reconnecting to recreated MCP server {server_name}: {e2}")
                
    def _setup_mcp_servers(self):
        """Set up MCP server objects based on configuration."""
        # Get enabled tools
        for tool_id, tool_config in self.config_manager.get_tools_config().items():
            if not self.config_manager.is_tool_enabled(tool_id):
                continue
                
            transport_type = tool_config.get("transport", "stdio_to_sse").lower()
            
            # For Streamable HTTP transport, use MCPServerStreamableHttp
            if transport_type in ["streamable-http", "streamable_http"]:
                url = tool_config.get("url")
                if url:
                    # Get timeout configurations from config
                    http_timeout = self.config_manager.get_tool_timeout(tool_id, "timeout", 30)
                    sse_read_timeout = self.config_manager.get_tool_timeout(tool_id, "sse_read_timeout", 300)
                    client_session_timeout = self.config_manager.get_tool_timeout(tool_id, "client_session_timeout", 30)
                    
                    # Get headers if specified
                    headers = tool_config.get("headers", {})
                    
                    logger.info(f"Adding MCP server {tool_id} at {url} with Streamable HTTP transport and timeouts: HTTP={http_timeout}s, SSE={sse_read_timeout}s, Session={client_session_timeout}s")
                    self.mcp_servers.append(MCPServerStreamableHttp(
                        name=tool_id,
                        params={
                            "url": url,
                            "headers": headers,
                            "timeout": http_timeout,  # HTTP request timeout
                            "sse_read_timeout": sse_read_timeout  # SSE connection timeout for underlying streams
                        },
                        client_session_timeout_seconds=client_session_timeout
                    ))
            # For SSE-based transports (stdio_to_sse, sse), use MCPServerSse
            elif transport_type in ["stdio_to_sse", "sse"]:
                url = tool_config.get("url")
                if url:
                    # Get timeout configurations from config
                    http_timeout = self.config_manager.get_tool_timeout(tool_id, "timeout", 30)
                    sse_read_timeout = self.config_manager.get_tool_timeout(tool_id, "sse_read_timeout", 300)
                    client_session_timeout = self.config_manager.get_tool_timeout(tool_id, "client_session_timeout", 30)
                    
                    logger.info(f"Adding MCP server {tool_id} at {url} with timeouts: HTTP={http_timeout}s, SSE={sse_read_timeout}s, Session={client_session_timeout}s")
                    self.mcp_servers.append(MCPServerSse(
                        name=tool_id,
                        params={
                            "url": url,
                            "timeout": http_timeout,  # HTTP request timeout
                            "sse_read_timeout": sse_read_timeout  # SSE connection timeout
                        },
                        client_session_timeout_seconds=client_session_timeout
                    ))
            # For stdio transport, use MCPServerStdio with the command directly
            elif transport_type == "stdio":
                command = tool_config.get("command")
                if command:
                    # Get timeout configuration from config
                    client_session_timeout = self.config_manager.get_tool_timeout(tool_id, "client_session_timeout", 30)
                    
                    # For MCPServerStdio, we need to split the command into command and args
                    command_parts = command.split()
                    executable = command_parts[0]
                    args = command_parts[1:] if len(command_parts) > 1 else []
                    
                    # Get environment variables if specified
                    env = tool_config.get("env")
                    
                    # Prepare params dictionary
                    params = {
                        "command": executable,
                        "args": args
                    }
                    
                    # Add environment variables if specified
                    if env:
                        params["env"] = env
                        logger.info(f"Adding environment variables for MCP server {tool_id}")
                    
                    logger.info(f"Adding MCP server {tool_id} with command '{command}' and session timeout: {client_session_timeout}s")
                    self.mcp_servers.append(MCPServerStdio(
                        name=tool_id,
                        params=params,
                        client_session_timeout_seconds=client_session_timeout
                    ))
            # For sse_to_stdio transport, always construct the command from the URL
            elif transport_type == "sse_to_stdio":
                # Get the URL from the configuration
                url = tool_config.get("url")
                if url:
                    # Get timeout configuration from config
                    client_session_timeout = self.config_manager.get_tool_timeout(tool_id, "client_session_timeout", 30)
                    
                    # Construct the full supergateway command
                    command = f"npx -y supergateway --sse \"{url}\""
                    logger.debug(f"Constructed command for sse_to_stdio transport: '{command}'")
                    # For MCPServerStdio, we need to split the command into command and args
                    command_parts = command.split()
                    executable = command_parts[0]
                    args = command_parts[1:] if len(command_parts) > 1 else []
                    
                    logger.info(f"Adding MCP server {tool_id} with sse_to_stdio transport and session timeout: {client_session_timeout}s")
                    self.mcp_servers.append(MCPServerStdio(
                        name=tool_id,
                        params={
                            "command": executable,
                            "args": args
                        },
                        client_session_timeout_seconds=client_session_timeout
                    ))
                else:
                    logger.warning(f"Missing URL for sse_to_stdio transport type for tool {tool_id}")
            # For any other transport types, log a warning
            else:
                logger.warning(f"Unknown transport type '{transport_type}' for tool {tool_id}")

    @abstractmethod
    async def process_query(self, query: str, history: List[Dict[str, str]] = None, agent=None) -> str:
        """
        Process a query using the OpenAI agent with MCP tools.
        
        This is an abstract method that must be implemented by subclasses.
        Each implementation should handle the processing of queries in a way
        appropriate for its specific interface (CLI, web, etc.).

        Args:
            query: The user's query
            history: Optional conversation history
            agent: The Agent instance to use for processing the query

        Returns:
            The agent's response
        """
        pass
        
    async def aclose(self):
        """
        Asynchronously clean up resources, particularly MCP servers and OpenAI client.
        
        This method should be called when the agent is no longer needed to ensure
        proper cleanup of async resources.
        """
        if self._cleanup_done:
            return
            
        # Mark cleanup as done to prevent multiple cleanups
        self._cleanup_done = True
        
        # Clean up MCP servers
        for server in self.mcp_servers:
            try:
                await asyncio.wait_for(server.cleanup(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning(f"Timeout cleaning up MCP server {getattr(server, 'name', 'unknown')}")
            except Exception as e:
                logger.error(f"Error closing MCP server {getattr(server, 'name', 'unknown')}: {e}")
        
        # Clean up OpenAI client and underlying HTTP client
        try:
            # First close the OpenAI client
            if hasattr(self.openai_client, 'close'):
                await asyncio.wait_for(self.openai_client.close(), timeout=5.0)
            elif hasattr(self.openai_client, 'aclose'):
                await asyncio.wait_for(self.openai_client.aclose(), timeout=5.0)
                
        except asyncio.TimeoutError:
            logger.warning("Timeout closing OpenAI client")
        except Exception as e:
            logger.debug(f"Error closing OpenAI client: {e}")
        
        # Clean up any remaining HTTP connections
        try:
            # Force garbage collection to clean up any lingering connections
            import gc
            gc.collect()
            logger.debug("Forced garbage collection for HTTP cleanup")
        except Exception as e:
            logger.debug(f"Error during garbage collection: {e}")
    
    def close(self):
        """
        Synchronously clean up resources.
        
        This is a convenience method that handles cleanup gracefully,
        avoiding event loop issues during shutdown.
        """
        if self._cleanup_done:
            return
            
        try:
            # Try to get the current event loop
            try:
                loop = asyncio.get_running_loop()
                # If we're in a running loop, we can't use run_until_complete
                # Instead, schedule the cleanup and let it run when possible
                if loop.is_running():
                    # Create a task for the cleanup but don't wait for it
                    # This avoids blocking the current thread
                    task = loop.create_task(self.aclose())
                    # Add a callback to handle any exceptions
                    task.add_done_callback(self._cleanup_callback)
                    return
            except RuntimeError:
                # No running event loop, we can create one
                pass
            
            # Try to get or create an event loop for cleanup
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    raise RuntimeError("Event loop is closed")
            except RuntimeError:
                # Create a new event loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # Run the async cleanup with a timeout
            try:
                loop.run_until_complete(asyncio.wait_for(self.aclose(), timeout=5.0))
            except asyncio.TimeoutError:
                logger.warning("Cleanup timed out after 5 seconds")
            except Exception as e:
                logger.error(f"Error during async cleanup: {e}")
                
        except Exception as e:
            logger.error(f"Error during synchronous cleanup: {e}")
            # Mark cleanup as done even if it failed to prevent infinite loops
            self._cleanup_done = True
    
    def _cleanup_callback(self, task):
        """Callback to handle cleanup task completion."""
        try:
            task.result()  # This will raise any exception that occurred
        except Exception as e:
            logger.error(f"Error in async cleanup task: {e}")
    
    def __del__(self):
        """
        Destructor to ensure resources are cleaned up when the object is garbage collected.
        """
        if not self._cleanup_done:
            self.close()