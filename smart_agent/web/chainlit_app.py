"""Chainlit web interface for Smart Agent.

This module provides a web interface for Smart Agent using Chainlit.
It mirrors the functionality of the CLI chat client but in a web interface.
"""

# Standard library imports
import os
import sys
import json
import logging
import asyncio
import time
import warnings
import functools
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from agents import Runner, set_tracing_disabled, ItemHelpers
set_tracing_disabled(disabled=True)

warnings.filterwarnings("ignore", message="Attempted to exit cancel scope in a different task than it was entered in")
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["ABSL_LOGGING_LOG_TO_STDERR"] = "0"

# Add parent directory to path to import smart_agent modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Smart Agent imports
from smart_agent.tool_manager import ConfigManager
from smart_agent.agent import SmartAgent, PromptGenerator
from smart_agent.web.helpers import (
    safely_close_exit_stack,
    handle_event,
    create_translation_files
)
from smart_agent.web.helpers.agent import create_agent

# Import optional dependencies
try:
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None

try:
    from langfuse import Langfuse
except ImportError:
    Langfuse = None

try:
    from agents.mcp import MCPServerStdio
    from smart_agent.web.helpers.reconnecting_mcp import ReconnectingMCP
    from agents import Agent, OpenAIChatCompletionsModel
except ImportError:
    Agent = None
    OpenAIChatCompletionsModel = None
    ReconnectingMCP = None
    MCPServerStdio = None

# Chainlit import
import chainlit as cl

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Suppress verbose logging from external libraries
logging.getLogger('asyncio').setLevel(logging.ERROR)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('mcp.client.sse').setLevel(logging.WARNING)

# Import MCP helper functions
from smart_agent.web.helpers.mcp import initialize_mcp_servers, safely_close_exit_stack

# create_agent function is now imported from smart_agent.web.helpers.agent

@cl.on_settings_update
async def handle_settings_update(settings):
    """Handle settings updates from the UI."""
    # Make sure config_manager is initialized
    if not hasattr(cl.user_session, 'config_manager') or cl.user_session.config_manager is None:
        cl.user_session.config_manager = ConfigManager()

    # Update API key and other settings
    cl.user_session.config_manager.set_api_base_url(settings.get("api_base_url", ""))
    cl.user_session.config_manager.set_model_name(settings.get("model_name", ""))
    cl.user_session.config_manager.set_api_key(settings.get("api_key", ""))

    # Save settings to config file
    cl.user_session.config_manager.save_config()

    await cl.Message(
        content="Settings updated successfully!",
        author="System"
    ).send()

@cl.on_chat_start
async def on_chat_start():
    """Initialize the chat session.

    This function is called when a new chat session starts. It initializes
    the user session variables, creates the agent, and connects to MCP servers.
    """
    # Initialize user session variables
    cl.user_session.config_manager = None
    cl.user_session.mcp_servers_objects = []

    # Create translation files
    create_translation_files()

    # Initialize config manager
    cl.user_session.config_manager = ConfigManager()

    # Initialize conversation history
    cl.user_session.conversation_history = [{"role": "system", "content": PromptGenerator.create_system_prompt()}]

    try:
        # Initialize and connect to MCP servers using the helper function from mcp.py
        exit_stack, connected_servers = await initialize_mcp_servers(cl.user_session.config_manager)
        if exit_stack is None or not connected_servers:
            await cl.Message(
                content="Failed to connect to MCP servers. Please check your configuration.",
                author="System"
            ).send()
            return

        # Store the exit stack and connected servers in the user session
        cl.user_session.exit_stack = exit_stack
        cl.user_session.mcp_servers_objects = connected_servers

        # Create the agent
        agent = await create_agent(
            cl.user_session.conversation_history,
            cl.user_session.config_manager,
            cl.user_session.mcp_servers_objects
        )

        if agent is None:
            # Clean up resources if agent creation failed
            await safely_close_exit_stack(cl.user_session.exit_stack)
            try:
                cl.user_session.exit_stack = None
            except RuntimeError as e:
                # If there's an error related to async generators, log it and continue
                if "async generator" in str(e):
                    logger.debug(f"Caught async generator error when clearing exit_stack: {e}")
                else:
                    # For other runtime errors, log but don't re-raise during cleanup
                    logger.warning(f"RuntimeError when clearing exit_stack: {e}")
            return

        # Store the agent in the user session
        cl.user_session.agent = agent
        
        logger.info("Chat session initialized successfully")

    except Exception as e:
        # Handle any errors during initialization
        error_message = f"An error occurred during initialization: {str(e)}"
        logger.exception(error_message)
        await cl.Message(content=error_message, author="System").send()

        # Make sure to clean up resources
        if hasattr(cl.user_session, 'agent') and cl.user_session.agent:
            try:
                # Clear the agent reference to release any async generators
                cl.user_session.agent = None
            except Exception as cleanup_error:
                logger.warning(f"Error while clearing agent during exception handling: {cleanup_error}")

        if hasattr(cl.user_session, 'exit_stack') and cl.user_session.exit_stack:
            await safely_close_exit_stack(cl.user_session.exit_stack)
            try:
                cl.user_session.exit_stack = None
            except RuntimeError as e:
                # If there's an error related to async generators, log it and continue
                if "async generator" in str(e):
                    logger.debug(f"Caught async generator error when clearing exit_stack: {e}")
                else:
                    # For other runtime errors, log but don't re-raise during cleanup
                    logger.warning(f"RuntimeError when clearing exit_stack: {e}")
            
        # Force garbage collection to ensure resources are freed
        import gc
        gc.collect()

@cl.on_message
async def on_message(msg: cl.Message):
    """Handle user messages.
    
    This function is called when a user sends a message. It processes the message,
    runs the agent, and displays the response.
    
    Args:
        msg: The user message
    """
    user_input = msg.content
    conv = cl.user_session.conversation_history
    
    # Check for special commands
    if user_input.lower() == "clear":
        # Reset the conversation history
        conv.clear()
        conv.append({"role": "system", "content": PromptGenerator.create_system_prompt()})
        
        # Create a new agent
        agent = await create_agent(
            conv,
            cl.user_session.config_manager,
            cl.user_session.mcp_servers_objects
        )
        
        if agent:
            cl.user_session.agent = agent
            await cl.Message(content="Conversation history cleared", author="System").send()
        return
    
    # Add the user message to history
    conv.append({"role": "user", "content": user_input})

    # Create a placeholder message that will receive streamed tokens
    assistant_msg = cl.Message(content="", author="Smart Agent")
    await assistant_msg.send()

    # State container passed to the event handler
    state = {
        "assistant_msg": assistant_msg,
        "thought_step": None,
        "current_tool": None
    }

    # Run the agent with the conversation history
    runner = Runner.run_streamed(cl.user_session.agent, conv, max_turns=100)

    try:
        async for ev in runner.stream_events():
            await handle_event(ev, state)
    except Exception as e:
        logger.exception(f"Error processing stream events: {e}")
    finally:
        # Update the assistant message with final content
        await assistant_msg.update()
        if hasattr(runner, "aclose"):
            await runner.aclose()

    # Keep only assistant visible text in history
    conv.append({"role": "assistant", "content": assistant_msg.content})

@cl.on_chat_end
async def on_chat_end():
    """Clean up resources when the chat session ends.

    This function is called when a chat session ends. It cleans up all resources
    used by the agent, including MCP servers and the exit stack.
    """
    logger.info("Cleaning up resources...")

    try:
        # First, clear the agent reference to release any async generators
        if hasattr(cl.user_session, 'agent'):
            try:
                # Set to None to release references and allow garbage collection
                cl.user_session.agent = None
            except Exception as e:
                logger.warning(f"Error while clearing agent: {e}")

        # Use the exit stack to clean up all resources
        if hasattr(cl.user_session, 'exit_stack') and cl.user_session.exit_stack:
            try:
                # Use a timeout for cleanup to prevent hanging
                import asyncio
                await asyncio.wait_for(
                    safely_close_exit_stack(cl.user_session.exit_stack),
                    timeout=5.0  # 5 second timeout for cleanup
                )
            except asyncio.TimeoutError:
                logger.warning("Timeout while cleaning up resources")
            except Exception as e:
                logger.warning(f"Error during exit stack cleanup: {e}")
            
            try:
                cl.user_session.exit_stack = None
            except RuntimeError as e:
                # If there's an error related to async generators, log it and continue
                if "async generator" in str(e):
                    logger.debug(f"Caught async generator error when clearing exit_stack: {e}")
                else:
                    # For other runtime errors, log but don't re-raise during cleanup
                    logger.warning(f"RuntimeError when clearing exit_stack: {e}")

        # Clear the list of MCP servers
        if hasattr(cl.user_session, 'mcp_servers_objects'):
            # Explicitly clean up each server as a backup measure
            for server in cl.user_session.mcp_servers_objects:
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
            
            cl.user_session.mcp_servers_objects = []

        # Force garbage collection to ensure resources are freed
        import gc
        gc.collect()

        logger.info("Cleanup complete")
    except Exception as e:
        # Catch any exceptions during cleanup to prevent them from propagating
        logger.warning(f"Error during cleanup: {e}")
        # Still mark cleanup as complete
        logger.info("Cleanup completed with some errors")

if __name__ == "__main__":
    # This is used when running locally with `chainlit run`
    # The port can be overridden with the `--port` flag
    import argparse

    parser = argparse.ArgumentParser(description="Run the Chainlit web UI for Smart Agent")
    parser.add_argument("--port", type=int, default=8000, help="Port to run the server on")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to run the server on")
    parser.add_argument("--config", type=str, default=None, help="Path to configuration file")
    parser.add_argument("--tools", type=str, default=None, help="Path to tools configuration file")

    args = parser.parse_args()

    # Note: Chainlit handles the server startup when run with `chainlit run`
