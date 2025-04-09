"""
Chainlit web interface for Smart Agent.
This is a direct reflection of the CLI chat client.
"""

import os
# Suppress gRPC fork warnings
os.environ["GRPC_ENABLE_FORK_SUPPORT"] = "false"
# Suppress absl logging warnings
os.environ["ABSL_LOGGING_LOG_TO_STDERR"] = "false"

import sys
import json
import asyncio
import logging
import pathlib
from typing import List, Dict, Any, Optional

import chainlit as cl

# These imports are used dynamically in the code
# and will be properly imported when needed
# from openai import AsyncOpenAI
# from agents import Agent, OpenAIChatCompletionsModel, Runner, ItemHelpers
# from agents.mcp import MCPServerSse

# Add parent directory to path to import smart_agent modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from smart_agent.tool_manager import ConfigManager
from smart_agent.agent import PromptGenerator

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Suppress specific asyncio warnings
logging.getLogger('asyncio').setLevel(logging.ERROR)

# Disable tracing if agents package is available
try:
    from agents import set_tracing_disabled
    set_tracing_disabled(disabled=True)
except ImportError:
    logger.debug("Agents package not installed. Tracing will not be disabled.")

# Disable httpx and mcp.client.sse logs to reduce noise
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("mcp.client.sse").setLevel(logging.WARNING)

# Suppress asyncio errors about event loop being closed
# These are not critical and just add noise to the logs
logging.getLogger("asyncio").setLevel(logging.WARNING)

# Global variables
config_manager = None
mcp_servers_objects = []
agent = None
exit_stack = None

@cl.on_settings_update
async def handle_settings_update(settings):
    """Handle settings updates from the UI."""
    # Update API key and other settings
    config_manager.set_api_base_url(settings.get("api_base_url", ""))
    config_manager.set_model_name(settings.get("model_name", ""))
    config_manager.set_api_key(settings.get("api_key", ""))

    # Save settings to config file
    config_manager.save_config()

    await cl.Message(
        content="Settings updated successfully!",
        author="System"
    ).send()

# Create translation directory and files if they don't exist
def create_translation_files():
    # Create .chainlit directory in the current working directory
    chainlit_dir = pathlib.Path.cwd() / ".chainlit"
    translations_dir = chainlit_dir / "translations"

    # Create directories if they don't exist
    translations_dir.mkdir(parents=True, exist_ok=True)

    # Create en.json translation file
    en_file = translations_dir / "en.json"
    if not en_file.exists():
        # Copy content from en-US.json if it exists, otherwise create a minimal file
        en_us_file = translations_dir / "en-US.json"
        if en_us_file.exists():
            en_file.write_text(en_us_file.read_text())
        else:
            # Create a minimal translation file
            en_file.write_text('{}')

    # Create chainlit.md file if it doesn't exist
    chainlit_md = chainlit_dir / "chainlit.md"
    if not chainlit_md.exists():
        chainlit_md.write_text("# Welcome to Smart Agent\n\nThis is a Chainlit UI for Smart Agent.")

@cl.on_chat_start
async def on_chat_start():
    """Initialize the chat session."""
    global config_manager, mcp_servers_objects, agent, exit_stack

    # Create translation files
    create_translation_files()

    # Initialize config manager
    config_manager = ConfigManager()

    # Initialize conversation history
    cl.user_session.conversation_history = [{"role": "system", "content": PromptGenerator.create_system_prompt()}]

    try:
        # Import required libraries
        try:
            import asyncio
            from contextlib import AsyncExitStack
            from openai import AsyncOpenAI
            from agents import Agent, OpenAIChatCompletionsModel, Runner, ItemHelpers
            from agents.mcp import MCPServerSse
        except ImportError:
            await cl.Message(
                content="Required packages not installed. Run 'pip install openai-agents' to use the agent.",
                author="System"
            ).send()
            return

        # Welcome message - send this before connecting to servers
        await cl.Message(
            content="Welcome to Smart Agent! I'm ready to help you with your tasks.",
            author="Smart Agent"
        ).send()

        # Initialize OpenAI client
        client = AsyncOpenAI(base_url=config_manager.get_api_base_url(), api_key=config_manager.get_api_key())

        # Create MCP server objects
        mcp_servers_objects = []

        # Get enabled tools
        for tool_id, tool_config in config_manager.get_tools_config().items():
            if not config_manager.is_tool_enabled(tool_id):
                continue

            transport_type = tool_config.get("transport", "stdio_to_sse").lower()
            url = tool_config.get("url")

            # Check if we have a URL (required for client-only mode)
            if not url:
                logger.warning(f"Tool {tool_id} has no URL and will be skipped.")
                continue

            # For SSE-based transports (stdio_to_sse, sse), use MCPServerSse
            if transport_type in ["stdio_to_sse", "sse"]:
                logger.info(f"Adding {tool_id} at {url} to agent")
                mcp_servers_objects.append(MCPServerSse(name=tool_id, params={"url": url}))

        # Check if we have any MCP servers
        if not mcp_servers_objects:
            await cl.Message(
                content="No tools are enabled or available. Please check your configuration.",
                author="System"
            ).send()
            return

        # Create an AsyncExitStack to manage server connections
        exit_stack = AsyncExitStack()

        # Connect to MCP servers using the exit stack
        connected_servers = []
        for server in mcp_servers_objects:
            try:
                # Use the exit stack to ensure proper cleanup
                await exit_stack.enter_async_context(server)
                logger.info(f"Connected to MCP server: {server.name}")
                connected_servers.append(server)
            except Exception as e:
                logger.error(f"Error connecting to MCP server: {e}")
                await cl.Message(
                    content=f"Error connecting to tool {server.name}: {e}",
                    author="System"
                ).send()
                # Don't return here, continue with other servers

        # Check if we have any connected servers
        if not connected_servers:
            await cl.Message(
                content="Could not connect to any tools. Please check your configuration.",
                author="System"
            ).send()
            # Close the exit stack to clean up any resources
            await exit_stack.aclose()
            exit_stack = None
            return

        # Update the mcp_servers_objects list to only include connected servers
        mcp_servers_objects = connected_servers

        try:
            # Debug: Log what we're about to do
            logger.info("About to create agent with %d MCP servers", len(mcp_servers_objects))
            for i, server in enumerate(mcp_servers_objects):
                logger.info("Server %d: %s", i+1, server.name)

            # Create the model
            model = OpenAIChatCompletionsModel(
                model=config_manager.get_model_name(),
                openai_client=client,
            )
            logger.info("Model created successfully")

            # Create the agent with MCP servers
            logger.info("Creating agent...")
            agent = Agent(
                name="Assistant",
                instructions=cl.user_session.conversation_history[0]["content"],
                model=model,
                mcp_servers=mcp_servers_objects,
            )

            logger.info("Agent created successfully")
        except Exception as e:
            logger.error(f"Error creating agent: {e}")
            await cl.Message(
                content=f"Error initializing agent: {e}",
                author="System"
            ).send()
            # Close the exit stack to clean up any resources
            await exit_stack.aclose()
            exit_stack = None
            return

    except Exception as e:
        # Handle any errors during initialization
        error_message = f"An error occurred during initialization: {str(e)}"
        logger.exception(error_message)
        await cl.Message(content=error_message, author="System").send()

        # Make sure to clean up resources
        if exit_stack:
            await exit_stack.aclose()
            exit_stack = None

@cl.on_message
async def on_message(message: cl.Message):
    """Process user messages."""
    global agent, mcp_servers_objects

    # Get user input
    user_input = message.content

    # Check if agent is initialized
    if agent is None or not hasattr(agent, 'mcp_servers') or not agent.mcp_servers:
        await cl.Message(
            content="Agent is not properly initialized. Please refresh the page and try again.",
            author="System"
        ).send()
        return

    # Create an agent steps element to track reasoning
    async with cl.Step(name="Agent Reasoning") as agent_steps:
        try:
            # Import required libraries
            try:
                from agents import Runner, ItemHelpers
            except ImportError:
                await cl.Message(
                    content="Required packages not installed. Run 'pip install openai-agents' to use the agent.",
                    author="System"
                ).send()
                return

            # Add user message to conversation history
            cl.user_session.conversation_history.append({"role": "user", "content": user_input})

            try:
                # Display a processing message
                processing_msg = await cl.Message(content="Processing your request...", author="Smart Agent").send()

                # Run the agent
                result = Runner.run_streamed(agent, cl.user_session.conversation_history, max_turns=100)

                # Remove the processing message
                await processing_msg.remove()

                # Set up variables for tracking the conversation
                assistant_reply = ""
                is_thought = False

                # Process the stream events
                async for event in result.stream_events():
                    if event.type == "raw_response_event":
                        continue
                    elif event.type == "agent_updated_stream_event":
                        continue
                    elif event.type == "run_item_stream_event":
                        if event.item.type == "tool_call_item":
                            try:
                                arguments_dict = json.loads(event.item.raw_item.arguments)
                                key, value = next(iter(arguments_dict.items()))

                                if key == "thought":
                                    is_thought = True
                                    await agent_steps.stream_token(f"### 🤔 Thinking\n```\n{value}\n```\n\n")
                                    assistant_reply += "\n[thought]: " + value
                                else:
                                    is_thought = False
                                    await agent_steps.stream_token(f"### 🔧 Using Tool: {key}\n```\n{value}\n```\n\n")
                            except (json.JSONDecodeError, StopIteration) as e:
                                await agent_steps.stream_token(f"Error parsing tool call: {e}\n\n")

                        elif event.item.type == "tool_call_output_item":
                            if not is_thought:
                                try:
                                    output_text = json.loads(event.item.output).get("text", "")
                                    await agent_steps.stream_token(f"### 💾 Tool Result\n```\n{output_text}\n```\n\n")
                                except json.JSONDecodeError:
                                    await agent_steps.stream_token(f"### 💾 Tool Result\n```\n{event.item.output}\n```\n\n")

                        elif event.item.type == "message_output_item":
                            role = event.item.raw_item.role
                            text_message = ItemHelpers.text_message_output(event.item)

                            if role == "assistant":
                                assistant_reply += "\n[response]: " + text_message
                                await cl.Message(content=text_message, author="Smart Agent").send()
                            else:
                                await agent_steps.stream_token(f"**{role.capitalize()}**: {text_message}\n\n")

                # Extract the response part for the conversation history
                response = ""
                for line in assistant_reply.split("\n"):
                    if line.startswith("[response]:"):
                        response += line[len("[response]:"):].strip() + "\n"

                if not response.strip():
                    response = assistant_reply.strip()

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
    """Clean up resources when the chat session ends."""
    global mcp_servers_objects, agent, exit_stack

    logger.info("Cleaning up resources...")

    # Use the exit stack to clean up all resources
    if exit_stack:
        try:
            logger.info("Closing exit stack...")
            await exit_stack.aclose()
            logger.info("Exit stack closed successfully")
        except Exception as e:
            logger.error(f"Error closing exit stack: {e}")
        finally:
            exit_stack = None

    # Clear the list of MCP servers
    mcp_servers_objects = []

    # Reset the agent
    agent = None

    # Force garbage collection to clean up any remaining resources
    import gc
    gc.collect()

    logger.info("Cleanup complete")

if __name__ == "__main__":
    # This is used when running locally with `chainlit run`
    # The port can be overridden with the `--port` flag
    import argparse

    parser = argparse.ArgumentParser(description="Run the Chainlit web UI for Smart Agent")
    parser.add_argument("--port", type=int, default=8000, help="Port to run the server on")

    args = parser.parse_args()

    # Note: Chainlit handles the server startup when run with `chainlit run`
