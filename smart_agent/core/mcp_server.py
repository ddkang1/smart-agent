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
            read_timeout_seconds=datetime.timedelta(seconds=client_session_timeout_seconds) if client_session_timeout_seconds else None,
        )
        self._cleanup_lock = asyncio.Lock()
        self._connected = False
        self.exit_stack = AsyncExitStack()

    async def __aenter__(self):
        """Async context manager entry point."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit point."""
        await self.cleanup()

    async def connect(self):
        """Connect to the server using fastmcp Client."""
        try:
            # Use the exit_stack to manage the client's lifecycle
            self.client = await self.exit_stack.enter_async_context(self.client)
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
            self._tools_list = await self.client.list_tools()
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
            result = await self.client.call_tool_mcp(tool_name, arguments or {})
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
            read_timeout_seconds=datetime.timedelta(seconds=client_session_timeout_seconds) if client_session_timeout_seconds else None,
        )
        self._cleanup_lock = asyncio.Lock()
        self._connected = False
        self.exit_stack = AsyncExitStack()

    async def __aenter__(self):
        """Async context manager entry point."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit point."""
        await self.cleanup()

    async def connect(self):
        """Connect to the server using fastmcp Client."""
        try:
            # Use the exit_stack to manage the client's lifecycle
            self.client = await self.exit_stack.enter_async_context(self.client)
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
            self._tools_list = await self.client.list_tools()
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
            result = await self.client.call_tool_mcp(tool_name, arguments or {})
            return result
        except Exception as e:
            logger.error(f"Error calling tool {tool_name} on server {self._name}: {e}")
            raise