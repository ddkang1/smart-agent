"""
Chainlit-specific SmartAgent implementation.

This module provides a Chainlit-specific implementation of the SmartAgent class
with features tailored for the Chainlit web interface.
"""

import asyncio
import json
import logging
from typing import List, Dict, Any, Optional
from contextlib import AsyncExitStack
from openai.types.responses import ResponseTextDeltaEvent

# Import chainlit
import chainlit as cl
from chainlit.message import Message

# Set up logging
logger = logging.getLogger(__name__)

# Import base SmartAgent
from .agent import BaseSmartAgent

# Import helpers
from agents import ItemHelpers


class ChainlitSmartAgent(BaseSmartAgent):
    """
    Chainlit-specific implementation of SmartAgent with features tailored for Chainlit interface.
    
    This class extends the BaseSmartAgent with functionality specific to Chainlit interface,
    including specialized event handling, UI integration, and MCP session management.
    """
    
    def __init__(self, *args, **kwargs):
        """Initialize the ChainlitSmartAgent."""
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
        
        # If no servers to connect to, return empty list
        if not mcp_servers_objects:
            logger.info("No MCP servers to connect to")
            return mcp_servers
            
        logger.info(f"Connecting to {len(mcp_servers_objects)} MCP servers...")
            
        for server in mcp_servers_objects:
            server_name = getattr(server, 'name', 'unknown')
            
            try:
                # For each server, decide which exit stack to use
                exit_stack = shared_exit_stack if shared_exit_stack else server.exit_stack
                
                logger.debug(f"Connecting to MCP server: {server_name}")
                connected_server = await exit_stack.enter_async_context(server)
                mcp_servers.append(connected_server)
                logger.debug(f"Connected to MCP server: {server_name}")
                self.mcp_sessions[server_name] = (connected_server, exit_stack)

            except Exception as e:
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
    
    async def process_query(self, query: str, history: List[Dict[str, str]] = None, agent=None, assistant_msg=None, state=None) -> str:
        """
        Process a query using the OpenAI agent with MCP tools, optimized for Chainlit interface.
        
        Args:
            query: The user's query
            history: Optional conversation history
            agent: The Agent instance to use for processing the query
            assistant_msg: The Chainlit message object to stream tokens to
            state: State dictionary for tracking conversation state
            
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
            
        # Initialize state if needed
        if state is not None:
            state["assistant_reply"] = ""
            state["tool_count"] = 0
            
        # The agent_step is now created in chainlit_app.py
        await state["agent_step"].send()

        try:
            # Run the agent with streaming
            from agents import Runner
            result = Runner.run_streamed(agent, history, max_turns=100)
            
            # Process the stream events using handle_event
            async for event in result.stream_events():
                await self.handle_event(event, state, assistant_msg)
            
            # Update the final step name to show a more descriptive summary
            if state is not None and "agent_step" in state and state.get("tool_count", 0) > 0:
                agent_step = state["agent_step"]
                
                # Track different types of operations performed
                thinking_steps = state.get("thinking_count", 0)
                tool_steps = state.get("tool_count", 0) - thinking_steps
                
                # Create a more descriptive summary that works with the "Used" prefix
                if tool_steps > 0 and thinking_steps > 0:
                    agent_step.name = f"{tool_steps} tools and {thinking_steps} thinking steps to complete the task"
                elif tool_steps > 0:
                    agent_step.name = f"{tool_steps} tools to complete the task"
                elif thinking_steps > 0:
                    agent_step.name = f"{thinking_steps} thinking steps to complete the task"
                else:
                    agent_step.name = f"{state['tool_count']} operations to complete the task"
                
                await agent_step.update()
            
            # Get the accumulated assistant reply from state if available
            if state is not None and "assistant_reply" in state:
                return state["assistant_reply"].strip()
            return ""
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
            # Handle raw response events (immediate token streaming)
            if event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):
                await assistant_msg.stream_token(event.data.delta)
                return
                
            if event.type != "run_item_stream_event":
                return

            item = event.item

            # Handle tool call
            if item.type == "tool_call_item":
                try:
                    # Parse arguments as JSON
                    arguments_dict = json.loads(item.raw_item.arguments)
                    
                    # Check if this is a thought tool call
                    if "thought" in arguments_dict:
                        state["is_thought"] = True
                        value = arguments_dict["thought"]
                        
                        # Increment tool count and thinking count
                        if state:
                            state["tool_count"] = state.get("tool_count", 0) + 1
                            state["thinking_count"] = state.get("thinking_count", 0) + 1
                            
                        # Update the agent step with the thought
                        if state and "agent_step" in state:
                            agent_step = state["agent_step"]
                            current_count = state.get("tool_count", 0)
                            
                            # Update the step content
                            if agent_step.output:
                                agent_step.output += f"\n\n**Step {current_count}: Thinking**\n{value}"
                            else:
                                agent_step.output = f"**Step {current_count}: Thinking**\n{value}"
                                
                            # Update the step name to flow naturally after "Using"/"Used" prefix
                            agent_step.name = f"thinking to analyze the request"
                            await agent_step.update()
                    else:
                        # Get the tool name
                        tool_name = item.raw_item.name if hasattr(item.raw_item, 'name') else "tool"
                        
                        # Format the arguments
                        formatted_input = {}
                        for arg_key, arg_value in arguments_dict.items():
                            formatted_input[arg_key] = arg_value
                            
                        # Format the input as a string
                        input_str = json.dumps(formatted_input, indent=2)
                        
                        # Increment tool count
                        if state:
                            state["tool_count"] = state.get("tool_count", 0) + 1
                            state["current_tool"] = tool_name
                            state["current_tool_count"] = state.get("tool_count", 0)
                            
                        # Update the agent step with the tool call
                        if state and "agent_step" in state:
                            agent_step = state["agent_step"]
                            current_count = state.get("tool_count", 0)
                            
                            # Update the step content
                            if agent_step.output:
                                agent_step.output += f"\n\n**Step {current_count}: {tool_name}**\n```json\n{input_str}\n```"
                            else:
                                agent_step.output = f"**Step {current_count}: {tool_name}**\n```json\n{input_str}\n```"
                                
                            # Update the step name to flow naturally after "Using"/"Used" prefix
                            agent_step.name = f"{tool_name} to process the request"
                            await agent_step.update()
                except Exception as e:
                    error_text = f"Error parsing tool call: {e}"
                    await assistant_msg.stream_token(f"\n<error>{error_text}</error>")
                    logger.error(f"Error processing tool call: {e}")

            # Handle tool output
            elif item.type == "tool_call_output_item":
                if state and state.get("is_thought"):
                    state["is_thought"] = False  # Reset thought flag
                    return  # Skip processing thought outputs
                    
                try:
                    # Try to parse output as JSON
                    try:
                        output_json = json.loads(item.output)
                        output_content = output_json.get('text', json.dumps(output_json, indent=2))
                    except json.JSONDecodeError:
                        output_content = item.output
                    
                    # Update the agent step with the tool output
                    if state and "agent_step" in state and state.get("current_tool_count"):
                        agent_step = state["agent_step"]
                        
                        # Add the tool output to the existing output with more context
                        agent_step.output += f"\n\n**Output from {state.get('current_tool', 'tool')}:**\n```\n{str(output_content)}\n```"
                        
                        # Update the step name to flow naturally after "Using"/"Used" prefix
                        agent_step.name = f"{state.get('current_tool', 'tool')} to process the result"
                        
                        # Update the step
                        await agent_step.update()
                        
                        # Clear the current tool count from state
                        state["current_tool_count"] = None
                    else:
                        # If we don't have a step, fall back to the old behavior
                        full_output = f"\n<tool_output>\n{str(output_content)}\n</tool_output>\n"
                        
                        # For tool outputs, update the message directly
                        if hasattr(assistant_msg, 'original_message'):
                            assistant_msg.original_message.content += full_output
                            await assistant_msg.original_message.update()
                        else:
                            assistant_msg.content += full_output
                            await assistant_msg.update()
                except Exception as e:
                    logger.error(f"Error processing tool output: {e}")
                    await assistant_msg.stream_token(f"\n<error>Error processing tool output: {e}</error>")
                    
            # Handle final assistant message
            elif item.type == "message_output_item":
                if item.raw_item.role == "assistant" and state and "assistant_reply" in state:
                    state["assistant_reply"] += ItemHelpers.text_message_output(item)
                
        except Exception as e:
            logger.exception(f"Error in handle_event: {e}")
            try:
                await assistant_msg.stream_token(f"\n\n[Error processing response: {str(e)}]\n\n")
            except Exception:
                pass