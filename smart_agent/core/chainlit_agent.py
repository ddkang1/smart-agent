"""
Chainlit-specific SmartAgent implementation.

This module provides a Chainlit-specific implementation of the SmartAgent class
with features tailored for the Chainlit web interface.
"""

import asyncio
import json
import logging
import time
from typing import List, Dict, Any, Optional, Tuple, Dict
from collections import deque
from contextlib import AsyncExitStack
from openai.types.responses import ResponseTextDeltaEvent

# Import for type hints
from chainlit.message import Message

# Set up logging
logger = logging.getLogger(__name__)

# Import base SmartAgent
from .agent import BaseSmartAgent

# Import helpers
from agents import ItemHelpers, Runner


class ChainlitSmartAgent(BaseSmartAgent):
    """
    Chainlit-specific implementation of SmartAgent with features tailored for Chainlit interface.
    
    This class extends the BaseSmartAgent with functionality specific to Chainlit interface,
    including specialized event handling, UI integration, and robust MCP session management.
    
    Features:
    - Improved MCP server connection management with proper resource cleanup
    - Support for both shared and dedicated AsyncExitStack for connection lifecycle management
    - Robust error handling and connection state tracking
    - Helper methods for MCP session access and management
    - Specialized event handling for Chainlit UI integration
    
    The MCP session management follows the pattern used in chainlit/backend/chainlit/server.py
    with connect_mcp and disconnect_mcp functions, but adapted for the SmartAgent context.
    """
    
    def __init__(self, *args, **kwargs):
        """Initialize the ChainlitSmartAgent with MCP session tracking."""
        super().__init__(*args, **kwargs)
        # Dictionary to store MCP sessions: {server_name: (client_session, exit_stack)}
        self.mcp_sessions = {}

    async def connect_mcp_servers(self, mcp_servers_objects, shared_exit_stack=None):
        """
        Connect to MCP servers with improved session management for Chainlit interface.
        
        Args:
            mcp_servers_objects: List of MCP server objects to connect to
            shared_exit_stack: Optional AsyncExitStack to use for connection management
                
        Returns:
            List of successfully connected MCP server objects
        """
        mcp_servers = []
        connection_errors = []
        
        # Track if we're using a shared exit stack provided by the caller
        using_shared_stack = shared_exit_stack is not None
        
        # If no servers to connect to, return empty list
        if not mcp_servers_objects:
            logger.info("No MCP servers to connect to")
            return mcp_servers
            
        logger.info(f"Connecting to {len(mcp_servers_objects)} MCP servers...")
            
        for server in mcp_servers_objects:
            server_name = getattr(server, 'name', 'unknown')
            
            try:
                # For each server, decide which exit stack to use
                if using_shared_stack:
                    # Use the provided shared exit stack
                    exit_stack = shared_exit_stack
                else:
                    # Use the server's own exit_stack instead of creating a new one
                    exit_stack = server.exit_stack
                
                logger.debug(f"Connecting to MCP server: {server_name}")
                connected_server = await exit_stack.enter_async_context(server)
                mcp_servers.append(connected_server)
                logger.debug(f"Connected to MCP server: {server_name}")
                self.mcp_sessions[server_name] = (connected_server, exit_stack)

            except Exception as e:
                # We don't need to close the exit_stack here since we're using the server's own exit_stack
                # which will be closed when the server is cleaned up
                pass
                error_msg = f"Error connecting to MCP server {server_name}: {e}"
                logger.error(error_msg)
                connection_errors.append(error_msg)
        
        # Log summary of connections
        if mcp_servers:
            logger.info(f"Successfully connected to {len(mcp_servers)} MCP servers")
        else:
            logger.warning("Failed to connect to any MCP servers")
            
        if connection_errors:
            logger.warning(f"Connection errors occurred: {'; '.join(connection_errors)}")
                
        return mcp_servers
            
    async def disconnect_mcp_servers(self, server_names=None):
        """
        Disconnect from MCP servers and clean up resources.
        
        Args:
            server_names: Optional list of server names to disconnect from.
                          If None, disconnect from all servers.
                          
        Returns:
            List of names of successfully disconnected servers
        """
        if server_names is None:
            # Disconnect from all servers if no specific names provided
            server_names = list(self.mcp_sessions.keys())
        
        # If no servers to disconnect, return empty list
        if not server_names:
            logger.debug("No MCP servers to disconnect")
            return []
            
        logger.info(f"Disconnecting from {len(server_names)} MCP servers...")
        
        disconnected_servers = []
        disconnect_errors = []
            
        for name in server_names:
            if name in self.mcp_sessions:
                client_session, exit_stack = self.mcp_sessions[name]
                logger.debug(f"Disconnecting from MCP server: {name}")
                
                try:
                    # If the client session has a shutdown method, call it
                    if hasattr(client_session, 'shutdown') and callable(getattr(client_session, 'shutdown')):
                        try:
                            await asyncio.wait_for(client_session.shutdown(), timeout=5)
                            logger.debug(f"Shutdown called for MCP server: {name}")
                        except (asyncio.TimeoutError, Exception) as e:
                            logger.warning(f"Error during shutdown of MCP server {name}: {e}")
                    
                    # Close the exit stack which will clean up all resources
                    await exit_stack.aclose()
                    logger.info(f"Successfully disconnected from MCP server: {name}")
                    disconnected_servers.append(name)
                except Exception as e:
                    error_msg = f"Error disconnecting from MCP server {name}: {e}"
                    logger.error(error_msg)
                    disconnect_errors.append(error_msg)
                finally:
                    # Always remove the session from our tracking dict
                    del self.mcp_sessions[name]
        
        # Log summary of disconnections
        if disconnected_servers:
            logger.info(f"Successfully disconnected from {len(disconnected_servers)} MCP servers")
        
        if disconnect_errors:
            logger.warning(f"Disconnection errors occurred: {'; '.join(disconnect_errors)}")
            
        return disconnected_servers
    
    async def cleanup(self):
        """
        Clean up all resources when shutting down the agent.
        This ensures all MCP sessions are properly closed.
        
        Returns:
            bool: True if cleanup was successful, False otherwise
        """
        logger.info("Cleaning up ChainlitSmartAgent resources")
        success = True
        
        try:
            # Get the number of active sessions before cleanup
            active_sessions = len(self.mcp_sessions)
            if active_sessions > 0:
                logger.info(f"Disconnecting from {active_sessions} active MCP sessions")
                
                # Disconnect from all MCP servers
                disconnected_servers = await self.disconnect_mcp_servers()
                
                # Check if all servers were disconnected
                if len(disconnected_servers) < active_sessions:
                    logger.warning(f"Only disconnected {len(disconnected_servers)} out of {active_sessions} MCP servers")
                    success = False
                else:
                    logger.info("All MCP servers successfully disconnected")
            else:
                logger.info("No active MCP sessions to clean up")
        except Exception as e:
            logger.error(f"Error during ChainlitSmartAgent cleanup: {e}")
            success = False
            
        # Final check to ensure all sessions are removed
        if self.mcp_sessions:
            logger.warning(f"Some MCP sessions ({len(self.mcp_sessions)}) were not properly cleaned up")
            # Force clear the sessions dictionary as a last resort
            self.mcp_sessions.clear()
            success = False
            
        return success
    
    def get_mcp_session(self, server_name):
        """
        Get an MCP session by server name.
        
        Args:
            server_name: The name of the MCP server
            
        Returns:
            The client session object if found, None otherwise
        """
        if server_name in self.mcp_sessions:
            client_session, _ = self.mcp_sessions[server_name]
            return client_session
        return None
    
    def get_connected_servers(self):
        """
        Get a list of all connected MCP server names.
        
        Returns:
            List of server names that are currently connected
        """
        return list(self.mcp_sessions.keys())

    class SmoothStreamWrapper:
        """
        A wrapper for Chainlit message objects that provides consistent output rates
        for token streaming, similar to the CLI agent's stream_output function.
        """
        
        def __init__(self, original_message: Message):
            """
            Initialize the wrapper with the original message.
            
            Args:
                original_message: The Chainlit message object to wrap
            """
            self.original_message = original_message
            
            # Buffer for tokens
            self.buffer = deque()
            self.stream_ended = asyncio.Event()
            
            # Define constants for consistent output
            self.output_interval = 0.025  # 50ms between outputs
            self.output_size = 24  # Output 24 characters at a time
            
            # Start the streaming task
            self.streaming_task = asyncio.create_task(
                self._stream_output(self.buffer, self.output_interval, self.output_size, self.stream_ended)
            )
        
        async def _stream_output(self, buffer, interval, size, end_event):
            """
            Stream output from the buffer at a consistent rate.
            
            Args:
                buffer: The buffer to stream from
                interval: The interval between outputs
                size: The number of characters to output at once
                end_event: Event to signal the end of streaming
            """
            try:
                while not end_event.is_set() or buffer:  # Continue until signaled and buffer is empty
                    if buffer:
                        # Get a batch of tokens from the buffer
                        batch = []
                        
                        for _ in range(min(size, len(buffer))):
                            if not buffer:
                                break
                                
                            batch.append(buffer.popleft())
                        
                        # Send the batch
                        if batch:
                            await self.original_message.stream_token(''.join(batch))
                    
                    await asyncio.sleep(interval)
            except asyncio.CancelledError:
                # Task cancellation is expected on completion
                pass
            except Exception as e:
                logging.error(f"Error in stream_output: {e}")
        
        async def stream_token(self, token: str, *args, **kwargs):
            """
            Override of the original stream_token method with consistent output rates.
            
            Args:
                token: The token to stream
                *args, **kwargs: Additional arguments passed to the original method
            """
            if not token:
                return
                
            # Add the token to the buffer
            for char in token:
                self.buffer.append(char)
        
        async def cleanup(self):
            """Clean up resources when done streaming."""
            self.stream_ended.set()
            try:
                await self.streaming_task
            except Exception as e:
                logging.error(f"Error cleaning up streaming task: {e}")
    
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
        
        # Add assistant_reply to state for accumulating tokens
        if state is not None:
            state["assistant_reply"] = assistant_reply
            
        # Create smooth stream wrapper if assistant_msg is provided
        smooth_stream = None
        if assistant_msg is not None:
            smooth_stream = self.SmoothStreamWrapper(assistant_msg)
        
        try:
            # Run the agent with streaming
            result = Runner.run_streamed(agent, history, max_turns=100)
            
            # Process the stream events using handle_event
            async for event in result.stream_events():
                await self.handle_event(event, state, smooth_stream or assistant_msg)
            
            # Clean up smooth stream wrapper if used
            if smooth_stream:
                await smooth_stream.cleanup()
            
            # Get the accumulated assistant reply from state if available
            if state is not None and "assistant_reply" in state:
                return state["assistant_reply"].strip()
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
            assistant_msg: The Chainlit message object or SmoothStreamWrapper to stream tokens to
        """
        try:
            # ── token delta from the LLM ────────────────────────────────────────────
            
            # Handle raw response events (immediate token streaming)
            if event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):
                await assistant_msg.stream_token(event.data.delta)
                return
                
            if event.type != "run_item_stream_event":
                return

            item = event.item

            # ── model called a tool ───────────────────
            if item.type == "tool_call_item":
                try:
                    # Parse arguments as JSON
                    arguments_dict = json.loads(item.raw_item.arguments)
                    
                    # Check if this is a thought tool call
                    if "thought" in arguments_dict:
                        state["is_thought"] = True
                        value = arguments_dict["thought"]
                        await assistant_msg.stream_token("\n<thought>\n")
                        await assistant_msg.stream_token(value)
                        await assistant_msg.stream_token("\n</thought>")
                    else:
                        # Regular tool call
                        tool_opening = "\n<tool>\n"
                        tool_content = ""
                        
                        # Add all key-value pairs from arguments_dict
                        for arg_key, arg_value in arguments_dict.items():
                            tool_content += f"{arg_key}={str(arg_value)}\n"
                            
                        tool_closing = "</tool>"
                        full_content = tool_opening + tool_content + tool_closing
                        await assistant_msg.stream_token(full_content)
                except (json.JSONDecodeError, Exception) as e:
                    error_text = f"Error parsing tool call: {e}"
                    error_content = f"\n<error>{error_text}</error>"
                    await assistant_msg.stream_token(error_content)
                    logger.error(f"Error processing tool call: {e}")

            # ── tool result ────────────────────────────────────────────────────────
            elif item.type == "tool_call_output_item":
                if state.get("is_thought"):
                    state["is_thought"] = False          # skip duplicate, reset
                    return
                try:
                    try:
                        output_json = json.loads(item.output)
                        
                        if isinstance(output_json, dict) and "text" in output_json:
                            output_content = output_json['text']
                        else:
                            output_content = json.dumps(output_json, indent=2)
                    except json.JSONDecodeError:
                        output_content = item.output
                    
                    output_opening = "\n<tool_output>\n"
                    output_closing = "\n</tool_output>"
                    
                    full_output = output_opening + str(output_content) + output_closing
                    
                    # For tool outputs, we need to update the message directly
                    # This bypasses the smooth streaming for tool outputs
                    if hasattr(assistant_msg, 'original_message'):
                        assistant_msg.original_message.content += full_output
                        await assistant_msg.original_message.update()
                    else:
                        assistant_msg.content += full_output
                        await assistant_msg.update()
                except Exception as e:
                    logger.error(f"Error processing tool output: {e}")
                    error_content = f"\n<error>Error processing tool output: {e}</error>"
                    await assistant_msg.stream_token(error_content)
                    return

            # ── final assistant chunk that is not streamed as delta ────────────────
            elif item.type == "message_output_item":
                role = item.raw_item.role
                text_message = ItemHelpers.text_message_output(item)
                if role == "assistant":
                    if state is not None and "assistant_reply" in state:
                        state["assistant_reply"] += text_message
                
        except Exception as e:
            logger.exception(f"Error in handle_event: {e}")
            try:
                await assistant_msg.stream_token(f"\n\n[Error processing response: {str(e)}]\n\n")
            except Exception:
                pass