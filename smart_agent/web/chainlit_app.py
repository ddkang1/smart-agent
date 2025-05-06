"""Chainlit web interface for Smart Agent.

This module provides a web interface for Smart Agent using Chainlit.
"""

# Standard library imports
import os
import sys
import json
import logging
import asyncio
import warnings
import argparse
from typing import List, Dict, Any
from contextlib import AsyncExitStack

# Import custom logging configuration
from smart_agent.web.logging_config import configure_logging

# Configure agents tracing
from agents import Runner, set_tracing_disabled
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

# Smart Agent imports
from smart_agent.tool_manager import ConfigManager
from smart_agent.agent import PromptGenerator
from smart_agent.core.chainlit_agent import ChainlitSmartAgent
from smart_agent.core.smooth_stream import SmoothStreamWrapper
from smart_agent.web.helpers.setup import create_translation_files

try:
    from agents import Agent, OpenAIChatCompletionsModel
except ImportError:
    Agent = None
    OpenAIChatCompletionsModel = None

# Chainlit import
import chainlit as cl

# Parse command line arguments
def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Chainlit web interface for Smart Agent")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--port", type=int, default=8000, help="Port to run the server on")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to run the server on")
    parser.add_argument("--config", type=str, default=None, help="Path to configuration file")
    
    # Parse known args only, to avoid conflicts with chainlit's own arguments
    args, _ = parser.parse_known_args()
    return args

# Get command line arguments
args = parse_args()

# Configure logging using our custom configuration
configure_logging(debug=args.debug)

# Define logger
logger = logging.getLogger(__name__)

# Get token batching settings from environment variables (set by the CLI)
use_token_batching = os.environ.get("SMART_AGENT_NO_STREAM_BATCHING", "") != "1"
batch_size = int(os.environ.get("SMART_AGENT_BATCH_SIZE", "20"))
flush_interval = float(os.environ.get("SMART_AGENT_FLUSH_INTERVAL", "0.1"))

# Log token batching settings
if use_token_batching:
    logger.info(f"Token batching enabled with batch size {batch_size} and flush interval {flush_interval}s")
else:
    logger.info("Token batching disabled")

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
    """Initialize the chat session."""
    # Create translation files
    create_translation_files()

    # Initialize config manager
    cl.user_session.config_manager = ConfigManager()

    # Get API configuration
    api_key = cl.user_session.config_manager.get_api_key()

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
        
        # Store the agent and other session variables
        cl.user_session.smart_agent = smart_agent
        cl.user_session.model_name = model_name
        cl.user_session.temperature = temperature
        cl.user_session.langfuse_enabled = smart_agent.langfuse_enabled
        cl.user_session.langfuse = smart_agent.langfuse
        
        # Store token batching settings
        cl.user_session.use_token_batching = use_token_batching
        cl.user_session.batch_size = batch_size
        cl.user_session.flush_interval = flush_interval
        
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

@cl.on_message
async def on_message(msg: cl.Message):
    """Handle user messages."""
    user_input = msg.content
    conv = cl.user_session.conversation_history
    
    # Add the user message to history
    conv.append({"role": "user", "content": user_input})

    # Create a placeholder message that will receive streamed tokens
    assistant_msg = cl.Message(content="", author="Smart Agent")
    await assistant_msg.send()
    
    # Wrap the message with SmoothStreamWrapper if token batching is enabled
    if getattr(cl.user_session, 'use_token_batching', False):
        stream_msg = SmoothStreamWrapper(
            assistant_msg,
            batch_size=cl.user_session.batch_size,
            flush_interval=cl.user_session.flush_interval,
            debug=args.debug
        )
    else:
        stream_msg = assistant_msg

    state = {
        "assistant_msg": stream_msg,
        "current_type": "assistant",  # Default type is assistant message
        "is_thought": False           # Track pending <thought> output
    }

    try:
        async with AsyncExitStack() as exit_stack:
            logger.info("Connecting to MCP servers...")
            mcp_servers = []
            for server in cl.user_session.smart_agent.mcp_servers:
                connected_server = await exit_stack.enter_async_context(server)
                mcp_servers.append(connected_server)
                logger.debug(f"Connected to MCP server: {connected_server.name}")

            logger.info(f"Successfully connected to {len(mcp_servers)} MCP servers")

            agent = Agent(
                name="Assistant",
                instructions=cl.user_session.smart_agent.system_prompt,
                model=OpenAIChatCompletionsModel(
                    model=cl.user_session.model_name,
                    openai_client=cl.user_session.smart_agent.openai_client,
                ),
                mcp_servers=mcp_servers,
            )

            assistant_reply = await cl.user_session.smart_agent.process_query(
                user_input,
                conv,
                agent=agent,
                assistant_msg=stream_msg,
                state=state
            )
        
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
    """Handle chat end event."""
    logger.info("Chat session ended")

if __name__ == "__main__":
    # This is used when running locally with `chainlit run`
    # Note: Chainlit handles the server startup when run with `chainlit run`
    configure_logging(debug=args.debug)
