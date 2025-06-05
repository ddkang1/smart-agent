"""
MCP Server implementations for Smart Agent.

This module provides MCP server implementations that can be used by the Smart Agent.
It includes new implementations of MCPServerSse and MCPServerStdio that use the fastmcp Client module.
"""

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional
from contextlib import AsyncExitStack
from pathlib import Path

from agents.mcp import MCPServer
from mcp.types import CallToolResult, Tool as MCPTool
from agents.exceptions import UserError

# Import fastmcp Client
from fastmcp.client import Client
import datetime

# Set up logging
logger = logging.getLogger(__name__)

class MCPServerSse(MCPServer):
    """
    MCP server implementation that uses the HTTP with SSE transport via fastmcp Client.
    
    This implementation uses the fastmcp Client module to connect to an MCP server over SSE.
    It replaces the original MCPServerSse implementation from openai-agents-python.
    """

    def __init__(
        self,
        params: Dict[str, Any],
        cache_tools_list: bool = False,
        name: str = None,
        client_session_timeout_seconds: float = 5,
    ):
        """
        Create a new MCP server based on the HTTP with SSE transport using fastmcp Client.

        Args:
            params: The params that configure the server. This includes the URL of the server,
                the headers to send to the server, the timeout for the HTTP request, and the
                timeout for the SSE connection.

            cache_tools_list: Whether to cache the tools list. If `True`, the tools list will be
                cached and only fetched from the server once. If `False`, the tools list will be
                fetched from the server on each call to `list_tools()`.

            name: A readable name for the server. If not provided, we'll create one from the
                URL.

            client_session_timeout_seconds: the read timeout passed to the MCP ClientSession.
        """
        self.params = params
        self._name = name or f"sse: {self.params['url']}"
        self._cache_tools_list = cache_tools_list
        self._cache_dirty = True
        self._tools_list = None
        self.client_session_timeout_seconds = client_session_timeout_seconds
        
        # Create a fastmcp Client with SSE transport
        self.client = Client(
            transport=self.params["url"],
            timeout=client_session_timeout_seconds,
        )
        self._cleanup_lock = asyncio.Lock()
        self._connected = False
        self.exit_stack = AsyncExitStack()

    async def __aenter__(self):
        """Async context manager entry point."""
        # Connect the client directly without using exit_stack to avoid task context issues
        await self.client.__aenter__()
        self.connected_client = self.client
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit point."""
        try:
            # Properly close the client in the same task context
            if hasattr(self.client, '__aexit__'):
                await self.client.__aexit__(exc_type, exc_val, exc_tb)
        except Exception as e:
            logger.debug(f"Error during client exit: {e}")
        await self.cleanup()

    async def connect(self):
        """Connect to the server using fastmcp Client."""
        try:
            # The client will be managed by the AsyncExitStack when used as context manager
            self._connected = True
            logger.info(f"Connected to MCP server: {self._name}")
        except Exception as e:
            logger.error(f"Error connecting to MCP server {self._name}: {e}")
            await self.cleanup()
            raise

    async def cleanup(self):
        """Cleanup the server connection."""
        async with self._cleanup_lock:
            try:
                # The client should already be closed by __aexit__, but ensure it's disconnected
                if hasattr(self.client, '_disconnect') and callable(getattr(self.client, '_disconnect')):
                    try:
                        await asyncio.wait_for(self.client._disconnect(), timeout=3.0)
                    except (asyncio.TimeoutError, Exception) as e:
                        logger.debug(f"Error during client disconnect for {self._name}: {e}")
                
                # Close the exit stack for any other resources (but not the client)
                try:
                    await asyncio.wait_for(self.exit_stack.aclose(), timeout=3.0)
                except (asyncio.TimeoutError, Exception) as e:
                    logger.debug(f"Error closing exit stack for {self._name}: {e}")
                
                logger.info(f"Disconnected from MCP server: {self._name}")
            except Exception as e:
                logger.error(f"Error cleaning up server {self._name}: {e}")
            finally:
                self._connected = False

    def invalidate_tools_cache(self):
        """Invalidate the tools cache."""
        self._cache_dirty = True

    @property
    def name(self) -> str:
        """A readable name for the server."""
        return self._name

    async def list_tools(self) -> List[MCPTool]:
        """List the tools available on the server."""
        if not self._connected:
            raise UserError(f"Server {self._name} not initialized. Make sure you call `connect()` first.")

        # Return from cache if caching is enabled, we have tools, and the cache is not dirty
        if self._cache_tools_list and not self._cache_dirty and self._tools_list:
            return self._tools_list

        # Reset the cache dirty to False
        self._cache_dirty = False

        # Fetch the tools from the server using fastmcp Client
        try:
            # Use the connected client if available, otherwise use the original client
            client_to_use = getattr(self, 'connected_client', self.client)
            self._tools_list = await client_to_use.list_tools()
            return self._tools_list
        except Exception as e:
            logger.error(f"Error listing tools from server {self._name}: {e}")
            raise

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any] = None) -> CallToolResult:
        """Invoke a tool on the server."""
        if not self._connected:
            raise UserError(f"Server {self._name} not initialized. Make sure you call `connect()` first.")

        # Call the tool using fastmcp Client
        try:
            # Use the connected client if available, otherwise use the original client
            client_to_use = getattr(self, 'connected_client', self.client)
            result = await client_to_use.call_tool_mcp(tool_name, arguments or {})
            return result
        except Exception as e:
            logger.error(f"Error calling tool {tool_name} on server {self._name}: {e}")
            raise


class MCPServerStdio(MCPServer):
    """
    MCP server implementation that uses the stdio transport via fastmcp Client.
    
    This implementation uses the fastmcp Client module to connect to an MCP server over stdio.
    It allows running MCP servers as subprocesses and communicating with them via stdin/stdout.
    """

    def __init__(
        self,
        params: Dict[str, Any],
        cache_tools_list: bool = False,
        name: str = None,
        client_session_timeout_seconds: float = 5,
    ):
        """
        Create a new MCP server based on the stdio transport using fastmcp Client.

        Args:
            params: The params that configure the server. This includes:
                - command: The command to run (e.g., "python", "node")
                - args: The arguments to pass to the command (e.g., ["script.py"])
                - env: Optional environment variables to set for the subprocess
                - cwd: Optional working directory for the subprocess

            cache_tools_list: Whether to cache the tools list. If `True`, the tools list will be
                cached and only fetched from the server once. If `False`, the tools list will be
                fetched from the server on each call to `list_tools()`.

            name: A readable name for the server. If not provided, we'll create one from the
                command and args.

            client_session_timeout_seconds: the read timeout passed to the MCP ClientSession.
        """
        self.params = params
        command = self.params.get("command", "")
        args = self.params.get("args", [])
        
        # Create a default name if none provided
        if name:
            self._name = name
        else:
            script_name = ""
            if args and len(args) > 0:
                script_path = args[0]
                script_name = os.path.basename(script_path)
            self._name = f"stdio: {command} {script_name}".strip()
        
        self._cache_tools_list = cache_tools_list
        self._cache_dirty = True
        self._tools_list = None
        self.client_session_timeout_seconds = client_session_timeout_seconds
        
        # Create a fastmcp Client with stdio transport
        # Structure the transport dictionary according to fastmcp's requirements
        transport_dict = {
            "mcpServers": {
                self._name: {  # Use the server name as the key
                    "command": self.params.get("command"),
                    "args": self.params.get("args", []),
                    "env": self.params.get("env"),
                    "cwd": self.params.get("cwd")
                }
            }
        }
        
        self.client = Client(
            transport=transport_dict,
            timeout=client_session_timeout_seconds,
        )
        self._cleanup_lock = asyncio.Lock()
        self._connected = False
        self.exit_stack = AsyncExitStack()

    async def __aenter__(self):
        """Async context manager entry point."""
        # Connect the client directly without using exit_stack to avoid task context issues
        await self.client.__aenter__()
        self.connected_client = self.client
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit point."""
        try:
            # Properly close the client in the same task context
            if hasattr(self.client, '__aexit__'):
                await self.client.__aexit__(exc_type, exc_val, exc_tb)
        except Exception as e:
            logger.debug(f"Error during client exit: {e}")
        await self.cleanup()

    async def connect(self):
        """Connect to the server using fastmcp Client."""
        try:
            # The client will be managed by the AsyncExitStack when used as context manager
            self._connected = True
            logger.info(f"Connected to MCP server: {self._name}")
        except Exception as e:
            logger.error(f"Error connecting to MCP server {self._name}: {e}")
            await self.cleanup()
            raise

    async def cleanup(self):
        """Cleanup the server connection."""
        async with self._cleanup_lock:
            try:
                # The client should already be closed by __aexit__, but ensure it's disconnected
                if hasattr(self.client, '_disconnect') and callable(getattr(self.client, '_disconnect')):
                    try:
                        await asyncio.wait_for(self.client._disconnect(), timeout=3.0)
                    except (asyncio.TimeoutError, Exception) as e:
                        logger.debug(f"Error during client disconnect for {self._name}: {e}")
                
                # Close the exit stack for any other resources (but not the client)
                await self.exit_stack.aclose()
                logger.info(f"Disconnected from MCP server: {self._name}")
            except Exception as e:
                logger.error(f"Error cleaning up server {self._name}: {e}")
            finally:
                self._connected = False

    def invalidate_tools_cache(self):
        """Invalidate the tools cache."""
        self._cache_dirty = True

    @property
    def name(self) -> str:
        """A readable name for the server."""
        return self._name

    async def list_tools(self) -> List[MCPTool]:
        """List the tools available on the server."""
        if not self._connected:
            raise UserError(f"Server {self._name} not initialized. Make sure you call `connect()` first.")

        # Return from cache if caching is enabled, we have tools, and the cache is not dirty
        if self._cache_tools_list and not self._cache_dirty and self._tools_list:
            return self._tools_list

        # Reset the cache dirty to False
        self._cache_dirty = False

        # Fetch the tools from the server using fastmcp Client
        try:
            # Use the connected client if available, otherwise use the original client
            client_to_use = getattr(self, 'connected_client', self.client)
            self._tools_list = await client_to_use.list_tools()
            return self._tools_list
        except Exception as e:
            logger.error(f"Error listing tools from server {self._name}: {e}")
            raise

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any] = None) -> CallToolResult:
        """Invoke a tool on the server."""
        if not self._connected:
            raise UserError(f"Server {self._name} not initialized. Make sure you call `connect()` first.")

        # Call the tool using fastmcp Client
        try:
            # Use the connected client if available, otherwise use the original client
            client_to_use = getattr(self, 'connected_client', self.client)
            result = await client_to_use.call_tool_mcp(tool_name, arguments or {})
            return result
        except Exception as e:
            logger.error(f"Error calling tool {tool_name} on server {self._name}: {e}")
            raise


class MCPServerStreamableHttp(MCPServer):
    """
    MCP server implementation that uses the Streamable HTTP transport via fastmcp Client.
    
    This implementation uses the fastmcp Client module to connect to an MCP server over Streamable HTTP.
    Streamable HTTP is a more efficient transport than SSE for MCP servers as it allows for bidirectional
    streaming and better connection management.
    """

    def __init__(
        self,
        params: Dict[str, Any],
        cache_tools_list: bool = False,
        name: str = None,
        client_session_timeout_seconds: float = 5,
    ):
        """
        Create a new MCP server based on the Streamable HTTP transport using fastmcp Client.

        Args:
            params: The params that configure the server. This includes the URL of the server,
                the headers to send to the server, the timeout for the HTTP request, and the
                timeout for the Streamable HTTP connection.

            cache_tools_list: Whether to cache the tools list. If `True`, the tools list will be
                cached and only fetched from the server once. If `False`, the tools list will be
                fetched from the server on each call to `list_tools()`.

            name: A readable name for the server. If not provided, we'll create one from the
                URL.

            client_session_timeout_seconds: the read timeout passed to the MCP ClientSession.
        """
        self.params = params
        self._name = name or f"streamable_http: {self.params['url']}"
        self._cache_tools_list = cache_tools_list
        self._cache_dirty = True
        self._tools_list = None
        self.client_session_timeout_seconds = client_session_timeout_seconds
        
        # Create a fastmcp Client with StreamableHttp transport
        from fastmcp.client.transports import StreamableHttpTransport
        
        # Extract configuration parameters
        url = self.params["url"]
        headers = self.params.get("headers", {})
        timeout = self.params.get("timeout", 30)
        sse_read_timeout = self.params.get("sse_read_timeout", 300)
        
        # Create the transport
        transport = StreamableHttpTransport(
            url=url,
            headers=headers,
            sse_read_timeout=sse_read_timeout,
        )
        
        self.client = Client(
            transport=transport,
            timeout=client_session_timeout_seconds,
        )
        self._cleanup_lock = asyncio.Lock()
        self._connected = False
        self.exit_stack = AsyncExitStack()

    async def __aenter__(self):
        """Async context manager entry point."""
        # Connect the client directly without using exit_stack to avoid task context issues
        await self.client.__aenter__()
        self.connected_client = self.client
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit point."""
        try:
            # Properly close the client in the same task context
            if hasattr(self.client, '__aexit__'):
                await self.client.__aexit__(exc_type, exc_val, exc_tb)
        except Exception as e:
            logger.debug(f"Error during client exit: {e}")
        await self.cleanup()

    async def connect(self):
        """Connect to the server using fastmcp Client."""
        try:
            # The client will be managed by the AsyncExitStack when used as context manager
            self._connected = True
            logger.info(f"Connected to MCP server: {self._name}")
        except Exception as e:
            logger.error(f"Error connecting to MCP server {self._name}: {e}")
            await self.cleanup()
            raise

    async def cleanup(self):
        """Cleanup the server connection."""
        async with self._cleanup_lock:
            try:
                # First try to gracefully close the client if it has a close method
                if hasattr(self.client, '_disconnect') and callable(getattr(self.client, '_disconnect')):
                    try:
                        await asyncio.wait_for(self.client._disconnect(), timeout=3.0)
                    except (asyncio.TimeoutError, Exception) as e:
                        logger.debug(f"Error during client disconnect for {self._name}: {e}")
                
                # Then close the exit stack
                await self.exit_stack.aclose()
                logger.info(f"Disconnected from MCP server: {self._name}")
            except Exception as e:
                logger.error(f"Error cleaning up server {self._name}: {e}")
            finally:
                self._connected = False

    def invalidate_tools_cache(self):
        """Invalidate the tools cache."""
        self._cache_dirty = True

    @property
    def name(self) -> str:
        """A readable name for the server."""
        return self._name

    async def list_tools(self) -> List[MCPTool]:
        """List the tools available on the server."""
        if not self._connected:
            raise UserError(f"Server {self._name} not initialized. Make sure you call `connect()` first.")

        # Return from cache if caching is enabled, we have tools, and the cache is not dirty
        if self._cache_tools_list and not self._cache_dirty and self._tools_list:
            return self._tools_list

        # Reset the cache dirty to False
        self._cache_dirty = False

        # Fetch the tools from the server using fastmcp Client
        try:
            # Use the connected client if available, otherwise use the original client
            client_to_use = getattr(self, 'connected_client', self.client)
            self._tools_list = await client_to_use.list_tools()
            return self._tools_list
        except Exception as e:
            logger.error(f"Error listing tools from server {self._name}: {e}")
            raise

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any] = None) -> CallToolResult:
        """Invoke a tool on the server."""
        if not self._connected:
            raise UserError(f"Server {self._name} not initialized. Make sure you call `connect()` first.")

        # Call the tool using fastmcp Client
        try:
            # Use the connected client if available, otherwise use the original client
            client_to_use = getattr(self, 'connected_client', self.client)
            result = await client_to_use.call_tool_mcp(tool_name, arguments or {})
            return result
        except Exception as e:
            logger.error(f"Error calling tool {tool_name} on server {self._name}: {e}")
            raise