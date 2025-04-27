"""
Base SmartAgent class for Smart Agent.

This module provides the base SmartAgent class that can be extended
for different interfaces (CLI, web, etc.).
"""

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
from agents.mcp import MCPServer, MCPServerSse
from agents import OpenAIChatCompletionsModel
set_tracing_disabled(disabled=True)

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
        
        # Initialize AsyncOpenAI client
        self.openai_client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
        )

    def setup_mcp_servers(self) -> List[MCPServer]:
        """
        Set up MCP servers based on the configuration.

        Returns:
            List of MCP server objects
        """
        mcp_servers = []
        
        # Get enabled tools
        for tool_id, tool_config in self.config_manager.get_tools_config().items():
            if not self.config_manager.is_tool_enabled(tool_id):
                continue
                
            transport_type = tool_config.get("transport", "stdio_to_sse").lower()
            
            # For SSE-based transports (stdio_to_sse, sse), use MCPServerSse
            if transport_type in ["stdio_to_sse", "sse"]:
                url = tool_config.get("url")
                if url:
                    # Get timeout configurations from config
                    http_timeout = self.config_manager.get_tool_timeout(tool_id, "timeout", 30)
                    sse_read_timeout = self.config_manager.get_tool_timeout(tool_id, "sse_read_timeout", 300)
                    client_session_timeout = self.config_manager.get_tool_timeout(tool_id, "client_session_timeout", 30)
                    
                    logger.info(f"Adding MCP server {tool_id} at {url} with timeouts: HTTP={http_timeout}s, SSE={sse_read_timeout}s, Session={client_session_timeout}s")
                    mcp_servers.append(MCPServerSse(
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
                    # Import MCPServerStdio here to avoid circular imports
                    from agents.mcp import MCPServerStdio
                    
                    # Get timeout configuration from config
                    client_session_timeout = self.config_manager.get_tool_timeout(tool_id, "client_session_timeout", 30)
                    
                    # For MCPServerStdio, we need to split the command into command and args
                    command_parts = command.split()
                    executable = command_parts[0]
                    args = command_parts[1:] if len(command_parts) > 1 else []
                    
                    logger.info(f"Adding MCP server {tool_id} with command '{command}' and session timeout: {client_session_timeout}s")
                    mcp_servers.append(MCPServerStdio(
                        name=tool_id,
                        params={
                            "command": executable,
                            "args": args
                        },
                        client_session_timeout_seconds=client_session_timeout
                    ))
            # For sse_to_stdio transport, always construct the command from the URL
            elif transport_type == "sse_to_stdio":
                # Get the URL from the configuration
                url = tool_config.get("url")
                if url:
                    # Import MCPServerStdio here to avoid circular imports
                    from agents.mcp import MCPServerStdio
                    
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
                    mcp_servers.append(MCPServerStdio(
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
        
        return mcp_servers

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