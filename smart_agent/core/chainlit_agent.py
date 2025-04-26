"""
Chainlit-specific SmartAgent implementation.

This module provides a Chainlit-specific implementation of the SmartAgent class
with features tailored for the Chainlit web interface.
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


class ChainlitAgent(BaseSmartAgent):
    """
    Chainlit-specific implementation of SmartAgent with features tailored for Chainlit interface.
    
    This class extends the BaseSmartAgent with functionality specific to Chainlit interface,
    including specialized event handling and UI integration.
    """

    async def connect_mcp_servers(self, mcp_servers_objects):
        """
        Connect to MCP servers with timeout and retry logic for Chainlit interface.
        
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
        Clean up MCP server connections for Chainlit interface.
        
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

    async def process_query(self, query: str, history: List[Dict[str, str]] = None, agent=None, assistant_msg=None, state=None) -> str:
        """
        Process a query using the OpenAI agent with MCP tools, optimized for Chainlit interface.
        
        This method is specifically designed for Chainlit interface, with
        specialized event handling and UI integration.
        
        Args:
            query: The user's query
            history: Optional conversation history
            agent: The Agent instance to use for processing the query
            assistant_msg: The Chainlit message object to stream tokens to
            state: State object containing UI elements and buffer
            
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
            
            # Process the stream events using handle_event
            async for event in result.stream_events():
                await self.handle_event(event, state, assistant_msg)
                
            return assistant_reply.strip()
        except Exception as e:
            # Log the error and return a user-friendly message
            logger.error(f"Error processing query: {e}")
            return f"I'm sorry, I encountered an error: {str(e)}. Please try again later."

    async def handle_event(self, event, state, assistant_msg):
        """
        Handle events from the agent for Chainlit UI.
        
        Args:
            event: The event to handle
            state: The state object containing UI elements
            assistant_msg: The Chainlit message object to stream tokens to
        """
        try:
            # ── token delta from the LLM ────────────────────────────────────────────

            if event.type != "run_item_stream_event":
                return

            item = event.item

            # ── model called a tool ───────────────────
            if item.type == "tool_call_item":
                try:
                    arg = json.loads(item.raw_item.arguments)
                    key, value = next(iter(arg.items()))
                    
                    if key == "thought":
                        state["is_thought"] = True
                        # Format thought like CLI does
                        thought_opening = "\n<thought>\n"
                        thought_closing = "\n</thought>"
                        
                        # Stream tokens character by character like CLI for thoughts only
                        for char in thought_opening:
                            await assistant_msg.stream_token(char)
                            state["buffer"].append((char, "thought"))
                            await asyncio.sleep(0.001)  # Small delay for visual effect
                            
                        for char in value:
                            await assistant_msg.stream_token(char)
                            state["buffer"].append((char, "thought"))
                            await asyncio.sleep(0.001)  # Small delay for visual effect
                            
                        for char in thought_closing:
                            await assistant_msg.stream_token(char)
                            state["buffer"].append((char, "thought"))
                            await asyncio.sleep(0.001)  # Small delay for visual effect
                    else:
                        # Format code without language specification
                        # Format regular tool call like CLI does
                        tool_opening = f"\n ``` \n"
                        tool_closing = "\n ``` \n"
                        
                        # Show all at once for non-thought items
                        # Ensure value is a string before concatenation
                        if isinstance(value, dict):
                            value = json.dumps(value)
                        elif not isinstance(value, str):
                            value = str(value)
                            
                        full_content = tool_opening + value + tool_closing
                        await assistant_msg.stream_token(full_content)
                        for char in full_content:
                            state["buffer"].append((char, "tool"))
                except Exception as e:
                    logger.error(f"Error processing tool call: {e}")
                    return

            # ── tool result ────────────────────────────────────────────────────────
            elif item.type == "tool_call_output_item":
                if state.get("is_thought"):
                    state["is_thought"] = False          # skip duplicate, reset
                    return
                try:
                    try:
                        # Try to parse as JSON for better handling
                        output_json = json.loads(item.output)
                        
                        # If it's a text response, format it appropriately
                        if isinstance(output_json, dict) and "text" in output_json:
                            # Format tool output like CLI does
                            output_opening = "\n ``` \n"
                            output_content = output_json['text']
                            output_closing = "\n ``` \n"
                        else:
                            # Format JSON output like CLI does
                            output_opening = "\n ``` \n"
                            output_content = json.dumps(output_json)
                            output_closing = "\n ``` \n"
                    except json.JSONDecodeError:
                        # For non-JSON outputs, show as plain text like CLI does
                        output_opening = "\n ``` \n"
                        output_content = item.output
                        output_closing = "\n ``` \n"
                    
                    # Show tool output all at once
                    full_output = output_opening + output_content + output_closing
                    await assistant_msg.stream_token(full_output)
                    for char in full_output:
                        state["buffer"].append((char, "tool_output"))
                except Exception as e:
                    logger.error(f"Error processing tool output: {e}")
                    return

            # ── final assistant chunk that is not streamed as delta ────────────────
            elif item.type == "message_output_item":
                txt = ItemHelpers.text_message_output(item)
                
                # Stream tokens character by character like CLI
                for char in txt:
                    await assistant_msg.stream_token(char)
                    state["buffer"].append((char, "assistant"))
                    await asyncio.sleep(0.001)  # Small delay for visual effect
                
        except Exception as e:
            # Catch any exceptions to prevent the event handling from crashing
            logger.exception(f"Error in handle_event: {e}")
            # Try to notify the user about the error
            try:
                await assistant_msg.stream_token(f"\n\n[Error processing response: {str(e)}]\n\n")
            except Exception:
                pass