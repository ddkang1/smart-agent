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
                    logger.info(f"Adding MCP server {tool_id} at {url}")
                    mcp_servers.append(MCPServerSse(
                        name=tool_id,
                        params={
                            "url": url,
                            "timeout": 30,  # HTTP request timeout
                            "sse_read_timeout": 300  # SSE connection timeout (5 minutes)
                        },
                        client_session_timeout_seconds=30  # Increase timeout to 30 seconds
                    ))
            # For stdio transport, use MCPServerStdio with the command directly
            elif transport_type == "stdio":
                command = tool_config.get("command")
                if command:
                    # Import MCPServerStdio here to avoid circular imports
                    from agents.mcp import MCPServerStdio
                    
                    # For MCPServerStdio, we need to split the command into command and args
                    command_parts = command.split()
                    executable = command_parts[0]
                    args = command_parts[1:] if len(command_parts) > 1 else []
                    mcp_servers.append(MCPServerStdio(
                        name=tool_id,
                        params={
                            "command": executable,
                            "args": args
                        },
                        client_session_timeout_seconds=30  # Increase timeout to 30 seconds
                    ))
            # For sse_to_stdio transport, always construct the command from the URL
            elif transport_type == "sse_to_stdio":
                # Get the URL from the configuration
                url = tool_config.get("url")
                if url:
                    # Import MCPServerStdio here to avoid circular imports
                    from agents.mcp import MCPServerStdio
                    
                    # Construct the full supergateway command
                    command = f"npx -y supergateway --sse \"{url}\""
                    logger.debug(f"Constructed command for sse_to_stdio transport: '{command}'")
                    # For MCPServerStdio, we need to split the command into command and args
                    command_parts = command.split()
                    executable = command_parts[0]
                    args = command_parts[1:] if len(command_parts) > 1 else []
                    mcp_servers.append(MCPServerStdio(
                        name=tool_id,
                        params={
                            "command": executable,
                            "args": args
                        },
                        client_session_timeout_seconds=30  # Increase timeout to 30 seconds
                    ))
                else:
                    logger.warning(f"Missing URL for sse_to_stdio transport type for tool {tool_id}")
            # For any other transport types, log a warning
            else:
                logger.warning(f"Unknown transport type '{transport_type}' for tool {tool_id}")
        
        return mcp_servers

    async def process_query(self, query: str, history: List[Dict[str, str]] = None, custom_event_handler=None, agent=None) -> str:
        """
        Process a query using the OpenAI agent with MCP tools.

        Args:
            query: The user's query
            history: Optional conversation history
            custom_event_handler: Optional custom event handler function for streaming events
            agent: The Agent instance to use for processing the query

        Returns:
            The agent's response
        """
        # Create message history with system prompt and user query if not provided
        if history is None:
            history = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": query}
            ]
        
        # Ensure we have an agent
        if agent is None:
            raise ValueError("Agent must be provided to process_query")
        
        # Track the assistant's response
        assistant_reply = ""
        
        try:
            # Run the agent with streaming
            result = Runner.run_streamed(agent, history, max_turns=100)
            
            # Process the stream events
            async for event in result.stream_events():
                # If a custom event handler is provided, use it exclusively
                if custom_event_handler:
                    try:
                        await custom_event_handler(event)
                        
                        # Still update assistant_reply for the return value
                        # This ensures we return a complete response even when using custom handler
                        if event.type == "run_item_stream_event":
                            if event.item.type == "tool_call_item":
                                try:
                                    arguments_dict = json.loads(event.item.raw_item.arguments)
                                    key, value = next(iter(arguments_dict.items()))
                                    if key == "thought":
                                        assistant_reply += f"\n<thought>{value}</thought>"
                                    else:
                                        if key == "code":
                                            code_str = str(value)
                                            assistant_reply += f"\n<tool name=\"{key}\">\n```\n{code_str}\n```</tool>"
                                        else:
                                            assistant_reply += f"\n<tool name=\"{key}\">{value}</tool>"
                                except (json.JSONDecodeError, StopIteration):
                                    pass
                            elif event.item.type == "tool_call_output_item":
                                try:
                                    output_text = json.loads(event.item.output).get("text", "")
                                    assistant_reply += f"\n<tool_output>{output_text}</tool_output>"
                                except json.JSONDecodeError:
                                    assistant_reply += f"\n<tool_output>{event.item.output}</tool_output>"
                            elif event.item.type == "message_output_item":
                                role = event.item.raw_item.role
                                text_message = ItemHelpers.text_message_output(event.item)
                                if role == "assistant":
                                    assistant_reply += text_message
                                else:
                                    assistant_reply += f"\n<{role}>{text_message}</{role}>"
                    except Exception as e:
                        logger.error(f"Error in custom event handler: {e}")
                    # Skip normal processing when using custom handler
                    continue
                
                # Normal processing (only used when no custom handler is provided)
                if event.type == "raw_response_event":
                    continue
                elif event.type == "agent_updated_stream_event":
                    continue
                elif event.type == "run_item_stream_event":
                    if event.item.type == "message_output_item":
                        role = event.item.raw_item.role
                        text_message = ItemHelpers.text_message_output(event.item)
                        if role == "assistant":
                            assistant_reply += text_message
                        else:
                            assistant_reply += f"\n<{role}>{text_message}</{role}>"
                    elif event.item.type == "tool_call_item":
                        try:
                            arguments_dict = json.loads(event.item.raw_item.arguments)
                            key, value = next(iter(arguments_dict.items()))
                            if key == "thought":
                                assistant_reply += f"\n<thought>{value}</thought>"
                            else:
                                if key == "code":
                                    code_str = str(value)
                                    assistant_reply += f"\n<tool name=\"{key}\">\n```\n{code_str}\n```</tool>"
                                else:
                                    assistant_reply += f"\n<tool name=\"{key}\">{value}</tool>"
                        except (json.JSONDecodeError, StopIteration) as e:
                            error_text = f"Error parsing tool call: {e}"
                            assistant_reply += f"\n<error>{error_text}</error>"
                    elif event.item.type == "tool_call_output_item":
                        try:
                            output_text = json.loads(event.item.output).get("text", "")
                            assistant_reply += f"\n<tool_output>{output_text}</tool_output>"
                        except json.JSONDecodeError:
                            assistant_reply += f"\n<tool_output>{event.item.output}</tool_output>"
            
            return assistant_reply.strip()
        except Exception as e:
            # Log the error and return a user-friendly message
            logger.error(f"Error processing query: {e}")
            return f"I'm sorry, I encountered an error: {str(e)}. Please try again later."