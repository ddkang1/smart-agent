"""Chainlit web interface for Smart Agent.

This module provides a web interface for Smart Agent using Chainlit.
It directly translates the CLI chat client functionality to a web interface.
"""

# Standard library imports
import os
import sys
import json
import logging
import asyncio
import time
import warnings
from datetime import datetime
from collections import deque
from typing import List, Dict, Any, Optional
from contextlib import AsyncExitStack

# Configure agents tracing
from agents import Runner, set_tracing_disabled, ItemHelpers
set_tracing_disabled(disabled=True)

# Suppress specific warnings
warnings.filterwarnings("ignore", message="Attempted to exit cancel scope in a different task than it was entered in")
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["ABSL_LOGGING_LOG_TO_STDERR"] = "0"

# Explicitly unset environment variables that would trigger Chainlit's data persistence layer
if "LITERAL_API_KEY" in os.environ:
    del os.environ["LITERAL_API_KEY"]
if "DATABASE_URL" in os.environ:
    del os.environ["DATABASE_URL"]

# Add parent directory to path to import smart_agent modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Smart Agent imports
from smart_agent.tool_manager import ConfigManager
from smart_agent.agent import PromptGenerator
from smart_agent.core.chainlit_agent import ChainlitSmartAgent
from smart_agent.web.helpers.setup import create_translation_files

try:
    from agents import Agent, OpenAIChatCompletionsModel
except ImportError:
    Agent = None
    OpenAIChatCompletionsModel = None
    MCPServerSse = None
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
    # Create translation files
    create_translation_files()

    # Initialize config manager
    cl.user_session.config_manager = ConfigManager()

    # Get API configuration
    api_key = cl.user_session.config_manager.get_api_key()
    base_url = cl.user_session.config_manager.get_api_base_url()

    # Check if API key is set
    if not api_key:
        await cl.Message(
            content="Error: API key is not set in config.yaml or environment variable.",
            author="System"
        ).send()
        return

    try:
        # Create the ChainlitSmartAgent
        smart_agent = ChainlitSmartAgent(config_manager=cl.user_session.config_manager)
        
        # Initialize conversation history with system prompt
        system_prompt = PromptGenerator.create_system_prompt()
        cl.user_session.conversation_history = [{"role": "system", "content": system_prompt}]
        
        # Get model configuration
        model_name = cl.user_session.config_manager.get_model_name()
        temperature = cl.user_session.config_manager.get_model_temperature()

        # Set up MCP server objects
        smart_agent.mcp_servers = smart_agent.setup_mcp_servers()
        
        # Create an exit stack for the session
        cl.user_session.exit_stack = AsyncExitStack()
        
        # Store the agent and other session variables
        cl.user_session.smart_agent = smart_agent
        cl.user_session.model_name = model_name
        cl.user_session.temperature = temperature
        cl.user_session.langfuse_enabled = smart_agent.langfuse_enabled
        cl.user_session.langfuse = smart_agent.langfuse
        
        # Connect to all MCP servers at chat start
        try:
            logger.info("Connecting to MCP servers...")
            mcp_servers = await smart_agent.connect_mcp_servers(
                smart_agent.mcp_servers,
                shared_exit_stack=cl.user_session.exit_stack
            )
            cl.user_session.mcp_servers = mcp_servers
            logger.info(f"Successfully connected to {len(mcp_servers)} MCP servers")
        except Exception as e:
            logger.error(f"Error connecting to MCP servers: {e}")
            await cl.Message(
                content=f"Warning: Failed to connect to some MCP servers: {str(e)}",
                author="System"
            ).send()

    except ImportError:
        await cl.Message(
            content="Required packages not installed. Run 'pip install openai agent' to use the agent.",
            author="System"
        ).send()
        return
    except Exception as e:
        # Handle any errors during initialization
        error_message = f"An error occurred during initialization: {str(e)}"
        logger.exception(error_message)
        await cl.Message(content=error_message, author="System").send()
        await cl.user_session.exit_stack.aclose()

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
    
    # Add the user message to history
    conv.append({"role": "user", "content": user_input})

    # Create a placeholder message that will receive streamed tokens
    assistant_msg = cl.Message(content="", author="Smart Agent")
    await assistant_msg.send()

    state = {
        "assistant_msg": assistant_msg,
        "current_type": "assistant",  # Default type is assistant message
        "is_thought": False           # Track pending <thought> output
    }

    try:
        # Use the already connected MCP servers
        mcp_servers = cl.user_session.mcp_servers if hasattr(cl.user_session, 'mcp_servers') else []
        logger.debug(f"Using {len(mcp_servers)} connected MCP servers for this message")
        
        # Create a fresh agent for this query with the connected servers
        agent = Agent(
            name="Assistant",
            instructions=cl.user_session.smart_agent.system_prompt,
            model=OpenAIChatCompletionsModel(
                model=cl.user_session.model_name,
                openai_client=cl.user_session.smart_agent.openai_client,
            ),
            mcp_servers=mcp_servers,
        )
        
        # Process the query with the Chainlit-specific method
        assistant_reply = await cl.user_session.smart_agent.process_query(
            user_input,
            conv,
            agent=agent,
            assistant_msg=assistant_msg,
            state=state
        )
        
        # Add the assistant's response to conversation history
        conv.append({"role": "assistant", "content": assistant_reply})
            
        # Log to Langfuse if enabled
        if cl.user_session.langfuse_enabled and cl.user_session.langfuse:
            try:
                trace = cl.user_session.langfuse.trace(
                    name="chat_session",
                    metadata={"model": cl.user_session.model_name, "temperature": cl.user_session.temperature},
                )
                trace.generation(
                    name="assistant_response",
                    model=cl.user_session.model_name,
                    prompt=user_input,
                    completion=assistant_msg.content,
                )
            except Exception as e:
                logger.error(f"Langfuse logging error: {e}")
            
                
    except Exception as e:
        logger.exception(f"Error processing stream events: {e}")
        await cl.Message(content=f"Error: {e}", author="System").send()

@cl.on_chat_end
async def on_chat_end():
    """Clean up resources when the chat session ends."""
    logger.info("Cleaning up resources...")

    try:
        # Clean up MCP servers using the agent's cleanup method
        if hasattr(cl.user_session, 'smart_agent'):
            cleanup_success = await cl.user_session.smart_agent.cleanup()
            if cleanup_success:
                logger.info("MCP servers cleanup successful")
            else:
                logger.warning("MCP servers cleanup completed with some issues")
        
        # Close the shared exit stack
        if hasattr(cl.user_session, 'exit_stack'):
            try:
                await cl.user_session.exit_stack.aclose()
                logger.info("Exit stack closed successfully")
            except Exception as e:
                logger.warning(f"Error closing exit stack: {e}")
        
        logger.info("Cleanup complete")
    except Exception as e:
        # Catch any exceptions during cleanup to prevent them from propagating
        logger.error(f"Error during cleanup: {e}")
        # Still mark cleanup as complete
        logger.info("Cleanup completed with some errors")
    finally:
        # Clear any session variables that might hold references to resources
        if hasattr(cl.user_session, 'mcp_servers'):
            cl.user_session.mcp_servers = []

if __name__ == "__main__":
    # This is used when running locally with `chainlit run`
    # The port can be overridden with the `--port` flag
    import argparse

    parser = argparse.ArgumentParser(description="Run the Chainlit web UI for Smart Agent")
    parser.add_argument("--port", type=int, default=8000, help="Port to run the server on")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to run the server on")
    parser.add_argument("--config", type=str, default=None, help="Path to configuration file")

    args = parser.parse_args()

    # Note: Chainlit handles the server startup when run with `chainlit run`
