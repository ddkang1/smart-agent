"""
Web-specific SmartAgent implementation.

This module provides a web-specific implementation of the SmartAgent class
with features tailored for web interfaces like Chainlit.
"""

import asyncio
import json
import logging
from typing import List, Dict, Any, Optional
from collections import deque

# Set up logging
logger = logging.getLogger(__name__)

# Import base SmartAgent
from .agent import BaseSmartAgent

# Import helpers
from agents import ItemHelpers, Runner


class WebSmartAgent(BaseSmartAgent):
    """
    Web-specific implementation of SmartAgent with features tailored for web interfaces.
    
    This class extends the BaseSmartAgent with functionality specific to web interfaces,
    such as Chainlit, including specialized event handling and UI integration.
    """

    async def connect_mcp_servers(self, mcp_servers_objects):
        """
        Connect to MCP servers with timeout and retry logic for web interfaces.
        
        Args:
            mcp_servers_objects: List of MCP server objects to connect to
            
        Returns:
            List of successfully connected MCP server objects
        """
        # Connect to all MCP servers with timeout and retry
        connected_servers = []
        for server in mcp_servers_objects:
            try:
                # Use a timeout for connection
                connection_task = asyncio.create_task(server.connect())
                await asyncio.wait_for(connection_task, timeout=10)  # 10 seconds timeout
                
                # For ReconnectingMCP, verify connection is established
                if hasattr(server, '_connected'):
                    # Wait for ping to verify connection
                    await asyncio.sleep(1)
                    if not server._connected:
                        logger.warning(f"Connection to {server.name} not fully established. Skipping.")
                        continue
                
                connected_servers.append(server)
                logger.info(f"Connected to {server.name}")
            except asyncio.TimeoutError:
                logger.warning(f"Timeout connecting to MCP server {server.name}")
                # Cancel the connection task
                connection_task.cancel()
                try:
                    await connection_task
                except (asyncio.CancelledError, Exception):
                    pass
            except Exception as e:
                logger.error(f"Error connecting to MCP server {server.name}: {e}")

        return connected_servers

    async def cleanup_mcp_servers(self, mcp_servers_objects):
        """
        Clean up MCP server connections for web interfaces.
        
        Args:
            mcp_servers_objects: List of MCP server objects to clean up
        """
        for server in mcp_servers_objects:
            try:
                if hasattr(server, 'cleanup') and callable(server.cleanup):
                    if asyncio.iscoroutinefunction(server.cleanup):
                        try:
                            await asyncio.wait_for(server.cleanup(), timeout=2.0)
                        except asyncio.TimeoutError:
                            logger.warning(f"Timeout cleaning up server {getattr(server, 'name', 'unknown')}")
                    else:
                        server.cleanup()
            except Exception as e:
                logger.debug(f"Error cleaning up server {getattr(server, 'name', 'unknown')}: {e}")
        
        # Force garbage collection to ensure resources are freed
        import gc
        gc.collect()

    async def process_query(self, query: str, history: List[Dict[str, str]] = None, agent=None) -> str:
        """
        Process a query using the OpenAI agent with MCP tools, optimized for web interfaces.
        
        This method is specifically designed for web interfaces like Chainlit, with
        specialized event handling and UI integration.
        
        Args:
            query: The user's query
            history: Optional conversation history
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
                # Process events without an event handler in this base implementation
                # Web UI specific event handling should be implemented in the web application
                
                # Still update assistant_reply for the return value
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
            
            return assistant_reply.strip()
        except Exception as e:
            # Log the error and return a user-friendly message
            logger.error(f"Error processing query: {e}")
            return f"I'm sorry, I encountered an error: {str(e)}. Please try again later."