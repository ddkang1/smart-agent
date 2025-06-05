"""Chainlit web interface for Smart Agent.

This module provides a web interface for Smart Agent using Chainlit.
"""

from smart_agent.web.suppress_errors import install_global_error_suppression
from smart_agent.web.httpcore_patch import patch_httpcore, suppress_async_warnings

# Standard library imports
import os
import sys
import json
import logging
import asyncio
import warnings
import argparse
import signal
from typing import List, Dict, Any
from contextlib import AsyncExitStack
import sys

# Suppress specific warnings that can cause runtime errors
warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*async generator ignored GeneratorExit.*")
warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*Attempted to exit cancel scope in a different task.*")
warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*coroutine.*was never awaited.*")

# Suppress httpcore and anyio related warnings
warnings.filterwarnings("ignore", module="httpcore.*")
warnings.filterwarnings("ignore", module="anyio.*")

# Configure asyncio to handle connection cleanup better
def configure_asyncio():
    """Configure asyncio for better connection handling."""
    try:
        import asyncio
        import platform
        
        # Set a more robust event loop policy for better cleanup
        if platform.system() == 'Windows':
            # Use ProactorEventLoop on Windows
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        else:
            # Use default policy but with better exception handling
            loop = asyncio.get_event_loop()
            # Set exception handler to suppress connection errors
            def exception_handler(loop, context):
                exception = context.get('exception')
                if exception:
                    # Suppress specific connection-related exceptions
                    if isinstance(exception, (ConnectionResetError, BrokenPipeError)):
                        return
                    if 'async generator ignored GeneratorExit' in str(exception):
                        return
                    if 'cancel scope in a different task' in str(exception):
                        return
                # Log other exceptions normally
                loop.default_exception_handler(context)
            
            loop.set_exception_handler(exception_handler)
    except Exception as e:
        # If configuration fails, continue without it
        logger.debug(f"Failed to configure asyncio: {e}")

# Configure asyncio when module loads
configure_asyncio()

# Global shutdown flag
_shutdown_requested = False

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global _shutdown_requested
    _shutdown_requested = True
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")

# Register signal handlers for graceful shutdown
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

from smart_agent.web.logging_config import configure_logging

# Configure agents tracing
from agents import Runner, set_tracing_disabled
set_tracing_disabled(disabled=True)

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
    
    # Initialize state
    state = {
        "current_type": "assistant",  # Default type is assistant message
        "is_thought": False,          # Track pending <thought> output
        "tool_count": 0               # Track the number of tool calls
    }

    # Create a dummy step first
    dummy_step = cl.Step(type="run", name="Tools")
    await dummy_step.send()
    
    # Store the step in state for later reference
    state["agent_step"] = dummy_step
    
    # Create a placeholder message that will receive streamed tokens
    # Set the parent_id to the step's ID to make it appear inside the step
    assistant_msg = cl.Message(content="", author="Smart Agent", parent_id=dummy_step.id)
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

    # Add the message to state
    state["assistant_msg"] = stream_msg

    try:
        async with AsyncExitStack() as exit_stack:
            logger.info("Connecting to MCP servers...")
            mcp_servers = []
            connection_errors = []
            
            # Connect to MCP servers with individual error handling
            for server in cl.user_session.smart_agent.mcp_servers:
                server_name = getattr(server, 'name', 'unknown')
                try:
                    # Use timeout for connection to prevent hanging
                    connected_server = await asyncio.wait_for(
                        exit_stack.enter_async_context(server),
                        timeout=10.0
                    )
                    mcp_servers.append(connected_server)
                    logger.debug(f"Connected to MCP server: {connected_server.name}")
                except asyncio.TimeoutError:
                    error_msg = f"Timeout connecting to MCP server: {server_name}"
                    logger.warning(error_msg)
                    connection_errors.append(error_msg)
                except Exception as e:
                    error_msg = f"Error connecting to MCP server {server_name}: {e}"
                    logger.warning(error_msg)
                    connection_errors.append(error_msg)

            logger.info(f"Successfully connected to {len(mcp_servers)} MCP servers")
            
            # Show connection warnings to user if any
            if connection_errors:
                warning_msg = "Warning: Some MCP servers failed to connect:\n" + "\n".join(connection_errors)
                await cl.Message(content=warning_msg, author="System").send()

            agent = Agent(
                name="Assistant",
                instructions=cl.user_session.smart_agent.system_prompt,
                model=OpenAIChatCompletionsModel(
                    model=cl.user_session.model_name,
                    openai_client=cl.user_session.smart_agent.openai_client,
                ),
                mcp_servers=mcp_servers,
            )

            try:
                # Process query with timeout to prevent hanging
                assistant_reply = await asyncio.wait_for(
                    cl.user_session.smart_agent.process_query(
                        user_input,
                        conv,
                        agent=agent,
                        assistant_msg=stream_msg,
                        state=state
                    ),
                    timeout=300.0  # 5 minute timeout for query processing
                )
                
                conv.append({"role": "assistant", "content": assistant_reply})
                
            except asyncio.TimeoutError:
                error_msg = "Request timed out. Please try a simpler query or try again later."
                logger.error("Query processing timed out")
                await cl.Message(content=error_msg, author="System").send()
                return
            except Exception as e:
                error_msg = f"Error processing query: {str(e)}"
                logger.exception(error_msg)
                await cl.Message(content=error_msg, author="System").send()
                return
            
        # Log to Langfuse if enabled (with error handling)
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
        logger.exception(f"Unexpected error in message handler: {e}")
        error_msg = "An unexpected error occurred. Please refresh the page and try again."
        try:
            await cl.Message(content=error_msg, author="System").send()
        except Exception:
            # If we can't even send an error message, log it
            logger.critical("Failed to send error message to user")

@cl.on_chat_end
async def on_chat_end():
    """Handle chat end event with robust cleanup."""
    logger.info("Chat session ended - starting cleanup")
    
    cleanup_tasks = []
    
    # Clean up the smart agent if it exists
    if hasattr(cl.user_session, 'smart_agent') and cl.user_session.smart_agent:
        try:
            # Create a cleanup task with timeout
            async def cleanup_agent():
                try:
                    if hasattr(cl.user_session.smart_agent, 'cleanup'):
                        await cl.user_session.smart_agent.cleanup()
                    elif hasattr(cl.user_session.smart_agent, 'aclose'):
                        await cl.user_session.smart_agent.aclose()
                    logger.info("Smart agent cleaned up successfully")
                except Exception as e:
                    logger.error(f"Error in smart agent cleanup: {e}")
            
            # Add cleanup task with timeout
            cleanup_tasks.append(asyncio.wait_for(cleanup_agent(), timeout=10.0))
            
        except Exception as e:
            logger.error(f"Error setting up smart agent cleanup: {e}")
    
    # Clean up HTTP client connections if they exist
    if hasattr(cl.user_session, 'smart_agent') and cl.user_session.smart_agent:
        try:
            async def cleanup_http_client():
                try:
                    if hasattr(cl.user_session.smart_agent, 'openai_client'):
                        client = cl.user_session.smart_agent.openai_client
                        if hasattr(client, 'close'):
                            await client.close()
                        elif hasattr(client, 'aclose'):
                            await client.aclose()
                    logger.debug("HTTP client cleaned up successfully")
                except Exception as e:
                    logger.debug(f"Error cleaning up HTTP client: {e}")
            
            cleanup_tasks.append(asyncio.wait_for(cleanup_http_client(), timeout=5.0))
            
        except Exception as e:
            logger.error(f"Error setting up HTTP client cleanup: {e}")
    
    # Execute all cleanup tasks concurrently with individual error handling
    if cleanup_tasks:
        try:
            # Use asyncio.gather with return_exceptions=True to handle individual failures
            results = await asyncio.gather(*cleanup_tasks, return_exceptions=True)
            
            # Log any cleanup failures
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    if isinstance(result, asyncio.TimeoutError):
                        logger.warning(f"Cleanup task {i} timed out")
                    else:
                        logger.error(f"Cleanup task {i} failed: {result}")
                        
        except Exception as e:
            logger.error(f"Unexpected error during cleanup: {e}")
    
    # Force cleanup of session variables
    try:
        for attr in ['smart_agent', 'config_manager', 'conversation_history', 'langfuse']:
            if hasattr(cl.user_session, attr):
                setattr(cl.user_session, attr, None)
    except Exception as e:
        logger.error(f"Error clearing session variables: {e}")
    
    logger.info("Chat session cleanup completed")

# if __name__ == "__main__":
    # This is used when running locally with `chainlit run`
    # Note: Chainlit handles the server startup when run with `chainlit run`
    # configure_logging(debug=args.debug)
