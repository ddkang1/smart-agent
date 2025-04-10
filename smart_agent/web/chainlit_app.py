"""Chainlit web interface for Smart Agent.

This module provides a web interface for Smart Agent using Chainlit.
It mirrors the functionality of the CLI chat client but in a web interface.
"""

# Standard library imports
import os
import sys
import logging
from agents import Runner, set_tracing_disabled
set_tracing_disabled(disabled=True)

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
    cl.user_session.agent = None
    cl.user_session.exit_stack = None

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
            cl.user_session.exit_stack = None
            return

        # Store the agent in the user session
        cl.user_session.agent = agent

    except Exception as e:
        # Handle any errors during initialization
        error_message = f"An error occurred during initialization: {str(e)}"
        logger.exception(error_message)
        await cl.Message(content=error_message, author="System").send()

        # Make sure to clean up resources
        if hasattr(cl.user_session, 'exit_stack') and cl.user_session.exit_stack:
            await safely_close_exit_stack(cl.user_session.exit_stack)
            cl.user_session.exit_stack = None

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
                result = Runner.run_streamed(cl.user_session.agent, cl.user_session.conversation_history, max_turns=100)

                # Remove the processing message
                await processing_msg.remove()

                # Set up variables for tracking the conversation
                assistant_reply = ""
                is_thought = False

                # Process the stream events
                async for event in result.stream_events():
                    is_thought, assistant_reply = await process_agent_event(
                        event, agent_steps, is_thought, assistant_reply
                    )

                # Extract the response part for the conversation history
                response = await extract_response_from_assistant_reply(assistant_reply)

                # Add assistant message to conversation history
                cl.user_session.conversation_history.append({"role": "assistant", "content": response})

            except Exception as e:
                logger.exception(f"Error running agent: {e}")
                await cl.Message(
                    content=f"An error occurred while processing your request: {e}",
                    author="System"
                ).send()

        except Exception as e:
            # Handle any errors
            error_message = f"An error occurred: {str(e)}"
            logger.exception(error_message)
            await cl.Message(content=f"I encountered an error: {error_message}", author="Smart Agent").send()

@cl.on_chat_end
async def on_chat_end():
    """Clean up resources when the chat session ends.

    This function is called when a chat session ends. It cleans up all resources
    used by the agent, including MCP servers and the exit stack.
    """
    logger.info("Cleaning up resources...")

    # Use the exit stack to clean up all resources
    if hasattr(cl.user_session, 'exit_stack') and cl.user_session.exit_stack:
        await safely_close_exit_stack(cl.user_session.exit_stack)
        cl.user_session.exit_stack = None

    # Clear the list of MCP servers
    if hasattr(cl.user_session, 'mcp_servers_objects'):
        cl.user_session.mcp_servers_objects = []

    # Reset the agent
    if hasattr(cl.user_session, 'agent'):
        cl.user_session.agent = None

    logger.info("Cleanup complete")

if __name__ == "__main__":
    # This is used when running locally with `chainlit run`
    # The port can be overridden with the `--port` flag
    import argparse

    parser = argparse.ArgumentParser(description="Run the Chainlit web UI for Smart Agent")
    parser.add_argument("--port", type=int, default=8000, help="Port to run the server on")

    args = parser.parse_args()

    # Note: Chainlit handles the server startup when run with `chainlit run`
