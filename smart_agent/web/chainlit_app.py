"""Chainlit web interface for Smart Agent.

This module provides a web interface for Smart Agent using Chainlit.
It mirrors the functionality of the CLI chat client but in a web interface.
"""

# Standard library imports
import os
import sys
import logging
import asyncio
import time
import warnings
import functools
from agents import Runner, set_tracing_disabled
set_tracing_disabled(disabled=True)

# Suppress specific RuntimeError warnings related to async generators and cancel scopes
warnings.filterwarnings("ignore", message="async generator ignored GeneratorExit")
warnings.filterwarnings("ignore", message="Attempted to exit cancel scope in a different task than it was entered in")
warnings.filterwarnings("ignore", message="Error invoking MCP tool")
warnings.filterwarnings("ignore", message="Stream error")
warnings.filterwarnings("ignore", message="Error cleaning up server")
warnings.filterwarnings("ignore", category=RuntimeWarning)

# Set up a custom exception handler for the asyncio event loop
def custom_exception_handler(loop, context):
    """Custom exception handler for asyncio event loop.
    
    This handler suppresses specific errors related to async generators and cancel scopes,
    while still logging other exceptions.
    """
    exception = context.get('exception')
    message = context.get('message', '')
    
    # Suppress specific errors
    if exception:
        error_str = str(exception)
        
        # Suppress RuntimeErrors related to async generators and cancel scopes
        if isinstance(exception, RuntimeError):
            if "async generator ignored GeneratorExit" in error_str or \
               "Attempted to exit cancel scope in a different task than it was entered in" in error_str:
                # Just log these at debug level
                logger.debug(f"Suppressed RuntimeError: {message}")
                return
        
        # Suppress errors related to MCP tool calls being interrupted
        if "Error invoking MCP tool" in error_str or \
           "Stream error" in error_str or \
           "Error cleaning up server" in error_str or \
           "EndOfStream" in error_str or \
           "disconnected" in error_str.lower():
            logger.debug(f"Suppressed MCP error: {message}")
            return
    
    # For other exceptions, use the default handler
    loop.default_exception_handler(context)

# Install the custom exception handler
loop = asyncio.get_event_loop()
loop.set_exception_handler(custom_exception_handler)

# Set environment variables to suppress warnings
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["ABSL_LOGGING_LOG_TO_STDERR"] = "0"

# Add parent directory to path to import smart_agent modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Smart Agent imports
from smart_agent.tool_manager import ConfigManager
from smart_agent.agent import PromptGenerator
from smart_agent.web.helpers import (
    create_agent,
    initialize_mcp_servers,
    safely_close_exit_stack,
    process_agent_event,
    extract_response_from_assistant_reply,
    create_translation_files
)

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
        # await cl.Message(
        #     content="Welcome to Smart Agent! I'm ready to help you with your tasks.",
        #     author="Smart Agent"
        # ).send()

        # Initialize and connect to MCP servers
        exit_stack, connected_servers = await initialize_mcp_servers(cl.user_session.config_manager)
        if exit_stack is None or not connected_servers:
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

async def process_stream_with_retry(result, agent_steps, max_retries=3, initial_backoff=1.0):
    """Process stream events with retry mechanism for server disconnections.
    
    Args:
        result: The result object with stream_events method
        agent_steps: The Chainlit step object for streaming tokens
        max_retries: Maximum number of retry attempts
        initial_backoff: Initial backoff time in seconds (will increase exponentially)
        
    Returns:
        tuple: (assistant_reply, is_thought) - The accumulated assistant reply and thought state
    """
    assistant_reply = ""
    is_thought = False
    retry_count = 0
    backoff = initial_backoff
    stream = None
    
    while retry_count <= max_retries:
        try:
            # If this is a retry, inform the user
            if retry_count > 0:
                await agent_steps.stream_token(
                    f"\n\n*Reconnecting to server (attempt {retry_count}/{max_retries})...*\n\n"
                )
                
            # Process the stream events
            stream = result.stream_events()
            async for event in stream:
                is_thought, assistant_reply = await process_agent_event(
                    event, agent_steps, is_thought, assistant_reply
                )
                
            # If we get here, streaming completed successfully
            return assistant_reply, is_thought
            
        except Exception as e:
            retry_count += 1
            error_message = str(e)
            
            # Check if this is a browser close or session end error
            if "EndOfStream" in error_message or "disconnected" in error_message.lower() or "Error invoking MCP tool" in error_message:
                logger.debug(f"Browser may have been closed, suppressing error: {error_message}")
                # Don't retry or raise for these errors, just return what we have so far
                return assistant_reply, is_thought
            
            logger.warning(f"Stream error (attempt {retry_count}/{max_retries}): {error_message}")
            
            # If we've reached max retries, raise the exception
            if retry_count >= max_retries:
                try:
                    await agent_steps.stream_token(
                        f"\n\n❌ **Connection failed after {max_retries} attempts.**\n\n"
                    )
                except Exception:
                    # If this fails, the connection is probably already closed
                    logger.debug("Could not send failure message, connection may be closed")
                raise
                
            # Otherwise, wait with exponential backoff before retrying
            await agent_steps.stream_token(
                f"\n\n⚠️ *Server disconnected: {error_message}*\n\n"
            )
            
            # Exponential backoff with jitter
            jitter = 0.1 * backoff * (2 * asyncio.get_event_loop().time() % 1)
            wait_time = backoff + jitter
            
            await asyncio.sleep(wait_time)
            backoff = min(backoff * 2, 10)  # Double the backoff time, max 10 seconds
        finally:
            # Ensure the stream is properly closed if it exists
            if stream is not None:
                try:
                    await stream.aclose()
                except Exception as close_error:
                    logger.debug(f"Error closing stream: {close_error}")
    
    # This should never be reached due to the raise above, but just in case
    return assistant_reply, is_thought

@cl.on_message
async def on_message(message: cl.Message):
    """Process user messages.

    This function is called when a user sends a message. It runs the agent
    with the user's message and displays the agent's response.
    """
    # Get user input
    user_input = message.content

    # Check if agent is initialized
    if not hasattr(cl.user_session, 'agent') or cl.user_session.agent is None or not hasattr(cl.user_session.agent, 'mcp_servers') or not cl.user_session.agent.mcp_servers:
        await cl.Message(
            content="Agent is not properly initialized. Please refresh the page and try again.",
            author="System"
        ).send()
        return

    # Create an agent steps element to track reasoning
    async with cl.Step(name="Agent Reasoning") as agent_steps:
        try:
            # Add user message to conversation history
            cl.user_session.conversation_history.append({"role": "user", "content": user_input})

            try:
                # Display a processing message
                processing_msg = await cl.Message(content="Processing your request...", author="Smart Agent").send()

                # Run the agent
                result = None
                try:
                    result = Runner.run_streamed(cl.user_session.agent, cl.user_session.conversation_history, max_turns=100)

                    # Remove the processing message
                    await processing_msg.remove()

                    # Process the stream events with retry mechanism
                    assistant_reply, _ = await process_stream_with_retry(result, agent_steps)
                    
                    # Extract the response part for the conversation history
                    response = await extract_response_from_assistant_reply(assistant_reply)
                    
                    # Add assistant message to conversation history
                    cl.user_session.conversation_history.append({"role": "assistant", "content": response})
                except Exception as e:
                    # Handle streaming errors
                    error_message = str(e)
                    
                    # Check if this is a browser close or session end error
                    if "EndOfStream" in error_message or "disconnected" in error_message.lower() or "Error invoking MCP tool" in error_message:
                        logger.debug(f"Browser may have been closed, suppressing error: {error_message}")
                        # Don't try to send a message if the browser is closed
                        return
                    
                    if "Server disconnected" in error_message or "disconnected without sending" in error_message.lower():
                        error_display = "The server disconnected unexpectedly. Please try again."
                    else:
                        error_display = f"Error processing response: {error_message}"
                    
                    logger.debug(f"Stream processing error: {e}")
                    try:
                        await cl.Message(
                            content=error_display,
                            author="System"
                        ).send()
                    except Exception:
                        # If this fails, the connection is probably already closed
                        logger.debug("Could not send error message, connection may be closed")
                finally:
                    # Ensure the result is properly closed if it exists
                    if result is not None and hasattr(result, 'aclose'):
                        try:
                            await result.aclose()
                        except Exception as close_error:
                            logger.debug(f"Error closing result: {close_error}")

            except Exception as e:
                error_message = str(e)
                
                # Check if this is a browser close or session end error
                if "EndOfStream" in error_message or "disconnected" in error_message.lower() or "Error invoking MCP tool" in error_message:
                    logger.debug(f"Browser may have been closed, suppressing error: {error_message}")
                    # Don't try to send a message if the browser is closed
                    return
                
                logger.debug(f"Error running agent: {e}")
                try:
                    await cl.Message(
                        content=f"An error occurred while processing your request: {e}",
                        author="System"
                    ).send()
                except Exception:
                    # If this fails, the connection is probably already closed
                    logger.debug("Could not send error message, connection may be closed")

        except Exception as e:
            # Handle any errors
            error_message = str(e)
            
            # Check if this is a browser close or session end error
            if "EndOfStream" in error_message or "disconnected" in error_message.lower() or "Error invoking MCP tool" in error_message:
                logger.debug(f"Browser may have been closed, suppressing error: {error_message}")
                # Don't try to send a message if the browser is closed
                return
            
            logger.debug(f"An error occurred: {error_message}")
            try:
                await cl.Message(content=f"I encountered an error: {error_message}", author="Smart Agent").send()
            except Exception:
                # If this fails, the connection is probably already closed
                logger.debug("Could not send error message, connection may be closed")

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

        # Clear the list of MCP servers
        if hasattr(cl.user_session, 'mcp_servers_objects'):
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

    args = parser.parse_args()

    # Note: Chainlit handles the server startup when run with `chainlit run`
