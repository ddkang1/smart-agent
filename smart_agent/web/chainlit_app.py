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
from collections import deque
from typing import List, Dict, Any, Optional

# Configure agents tracing
from agents import Runner, set_tracing_disabled, ItemHelpers
set_tracing_disabled(disabled=True)

# Suppress specific warnings
warnings.filterwarnings("ignore", message="Attempted to exit cancel scope in a different task than it was entered in")
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["ABSL_LOGGING_LOG_TO_STDERR"] = "0"

# Add parent directory to path to import smart_agent modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Smart Agent imports
from smart_agent.tool_manager import ConfigManager
from smart_agent.agent import SmartAgent, PromptGenerator
from smart_agent.web.helpers.setup import create_translation_files

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
    from agents.mcp import MCPServerSse, MCPServerStdio
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

    # Get model configuration
    model_name = cl.user_session.config_manager.get_model_name()
    temperature = cl.user_session.config_manager.get_model_temperature()

    # Get Langfuse configuration
    langfuse_config = cl.user_session.config_manager.get_langfuse_config()
    langfuse_enabled = langfuse_config.get("enabled", False)
    langfuse = None

    # Initialize Langfuse if enabled
    if langfuse_enabled:
        try:
            from langfuse import Langfuse

            langfuse = Langfuse(
                public_key=langfuse_config.get("public_key", ""),
                secret_key=langfuse_config.get("secret_key", ""),
                host=langfuse_config.get("host", "https://cloud.langfuse.com"),
            )
            await cl.Message(content="Langfuse monitoring enabled", author="System").send()
        except ImportError:
            await cl.Message(
                content="Langfuse package not installed. Run 'pip install langfuse' to enable monitoring.",
                author="System"
            ).send()
            langfuse_enabled = False

    try:
        # Import required libraries
        from openai import AsyncOpenAI

        # Initialize AsyncOpenAI client
        client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
        )

        # Get enabled tools
        enabled_tools = []
        for tool_id, tool_config in cl.user_session.config_manager.get_tools_config().items():
            if cl.user_session.config_manager.is_tool_enabled(tool_id):
                tool_url = cl.user_session.config_manager.get_tool_url(tool_id)
                tool_name = tool_config.get("name", tool_id)
                enabled_tools.append((tool_id, tool_name, tool_url))

        # Create MCP server list for the agent
        mcp_servers = []
        for tool_id, tool_name, tool_url in enabled_tools:
            # await cl.Message(content=f"Adding {tool_name} at {tool_url} to agent", author="System").send()
            mcp_servers.append(tool_url)

        # Initialize conversation history with system prompt
        system_prompt = PromptGenerator.create_system_prompt()
        cl.user_session.conversation_history = [{"role": "system", "content": system_prompt}]

        # Store configuration in user session
        cl.user_session.client = client
        cl.user_session.model_name = model_name
        cl.user_session.mcp_servers = mcp_servers
        cl.user_session.langfuse = langfuse
        cl.user_session.langfuse_enabled = langfuse_enabled
        cl.user_session.temperature = temperature

        # Create MCP server objects
        mcp_servers_objects = []
        for tool_id, tool_config in cl.user_session.config_manager.get_tools_config().items():
            if not cl.user_session.config_manager.is_tool_enabled(tool_id):
                continue
            
            transport_type = tool_config.get("transport", "stdio_to_sse").lower()
            
            # Import ReconnectingMCP for robust connections
            from smart_agent.web.helpers.reconnecting_mcp import ReconnectingMCP
            
            # For SSE-based transports (stdio_to_sse, sse), use ReconnectingMCP
            if transport_type in ["stdio_to_sse", "sse"]:
                url = tool_config.get("url")
                if url:
                    mcp_servers_objects.append(ReconnectingMCP(name=tool_id, params={"url": url}))
            # For stdio transport, use MCPServerStdio with the command directly
            elif transport_type == "stdio":
                command = tool_config.get("command")
                if command:
                    # For MCPServerStdio, we need to split the command into command and args
                    command_parts = command.split()
                    executable = command_parts[0]
                    args = command_parts[1:] if len(command_parts) > 1 else []
                    mcp_servers_objects.append(MCPServerStdio(name=tool_id, params={
                        "command": executable,
                        "args": args
                    }))
            # For sse_to_stdio transport, always construct the command from the URL
            elif transport_type == "sse_to_stdio":
                # Get the URL from the configuration
                url = tool_config.get("url")
                if url:
                    # Construct the full supergateway command
                    command = f"npx -y supergateway --sse \"{url}\""
                    logger.debug(f"Constructed command for sse_to_stdio transport: '{command}'")
                    # For MCPServerStdio, we need to split the command into command and args
                    command_parts = command.split()
                    executable = command_parts[0]
                    args = command_parts[1:] if len(command_parts) > 1 else []
                    mcp_servers_objects.append(MCPServerStdio(name=tool_id, params={
                        "command": executable,
                        "args": args
                    }))
                else:
                    logger.warning(f"Missing URL for sse_to_stdio transport type for tool {tool_id}")
            # For any other transport types, log a warning
            else:
                logger.warning(f"Unknown transport type '{transport_type}' for tool {tool_id}")

        # Connect to all MCP servers with timeout and retry
        connected_servers = []
        for server in mcp_servers_objects:
            try:
                # Use a timeout for connection
                connection_task = asyncio.create_task(server.connect())
                await asyncio.wait_for(connection_task, timeout=10)  # 10 seconds timeout
                
                # For ReconnectingMCP, verify connection is established
                if isinstance(server, ReconnectingMCP):
                    # Wait for ping to verify connection
                    await asyncio.sleep(1)
                    if not server._connected:
                        # await cl.Message(content=f"Connection to {server.name} not fully established. Skipping.", author="System").send()
                        continue
                
                connected_servers.append(server)
                # await cl.Message(content=f"Connected to {server.name}", author="System").send()
            except asyncio.TimeoutError:
                await cl.Message(content=f"Timeout connecting to MCP server {server.name}", author="System").send()
                # Cancel the connection task
                connection_task.cancel()
                try:
                    await connection_task
                except (asyncio.CancelledError, Exception):
                    pass
            except Exception as e:
                await cl.Message(content=f"Error connecting to MCP server {server.name}: {e}", author="System").send()

        # Store connected servers in user session
        cl.user_session.mcp_servers_objects = connected_servers

        # Create the agent - using SmartAgent wrapper class
        smart_agent = SmartAgent(
            model_name=model_name,
            openai_client=client,
            mcp_servers=connected_servers,
            system_prompt=system_prompt,
        )

        # Store the agent in user session
        cl.user_session.smart_agent = smart_agent

        # await cl.Message(
        #     content=f"Agent initialized with {len(connected_servers)} tools",
        #     author="System"
        # ).send()

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

        # Make sure to clean up resources
        if hasattr(cl.user_session, 'mcp_servers_objects'):
            for server in cl.user_session.mcp_servers_objects:
                try:
                    if hasattr(server, 'cleanup') and callable(server.cleanup):
                        if asyncio.iscoroutinefunction(server.cleanup):
                            await server.cleanup()
                        else:
                            server.cleanup()
                except Exception as cleanup_error:
                    logger.warning(f"Error during server cleanup: {cleanup_error}")
            
        # Force garbage collection to ensure resources are freed
        import gc
        gc.collect()

async def handle_event(event, state):
    """Handle events from the agent.
    
    Args:
        event: The event to handle
        state: The state object containing UI elements
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
                    
                    # Stream tokens character by character like CLI
                    for char in thought_opening:
                        await state["assistant_msg"].stream_token(char)
                        state["buffer"].append((char, "thought"))
                        await asyncio.sleep(0.001)  # Small delay for visual effect
                        
                    for char in value:
                        await state["assistant_msg"].stream_token(char)
                        state["buffer"].append((char, "thought"))
                        await asyncio.sleep(0.001)  # Small delay for visual effect
                        
                    for char in thought_closing:
                        await state["assistant_msg"].stream_token(char)
                        state["buffer"].append((char, "thought"))
                        await asyncio.sleep(0.001)  # Small delay for visual effect
                else:
                    # Format code without language specification
                    # Assume any value in a code key is code
                    if key == "code":
                        # Format tool call with code block (no language specification)
                        tool_opening = f"\n ``` \n"
                        tool_closing = "\n ``` \n"
                        
                        # Stream tokens character by character like CLI
                        for char in tool_opening:
                            await state["assistant_msg"].stream_token(char)
                            state["buffer"].append((char, "tool"))
                            await asyncio.sleep(0.001)  # Small delay for visual effect
                            
                        for char in value:
                            await state["assistant_msg"].stream_token(char)
                            state["buffer"].append((char, "tool"))
                            await asyncio.sleep(0.001)  # Small delay for visual effect
                            
                        for char in tool_closing:
                            await state["assistant_msg"].stream_token(char)
                            state["buffer"].append((char, "tool"))
                            await asyncio.sleep(0.001)  # Small delay for visual effect
                    else:
                        # Format regular tool call like CLI does
                        tool_opening = f"\n ``` \n"
                        tool_closing = "\n ``` \n"
                        
                        # Stream tokens character by character like CLI
                        for char in tool_opening:
                            await state["assistant_msg"].stream_token(char)
                            state["buffer"].append((char, "tool"))
                            await asyncio.sleep(0.001)  # Small delay for visual effect
                            
                        for char in value:
                            await state["assistant_msg"].stream_token(char)
                            state["buffer"].append((char, "tool"))
                            await asyncio.sleep(0.001)  # Small delay for visual effect
                            
                        for char in tool_closing:
                            await state["assistant_msg"].stream_token(char)
                            state["buffer"].append((char, "tool"))
                            await asyncio.sleep(0.001)  # Small delay for visual effect
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
                
                # Stream tokens character by character like CLI
                for char in output_opening:
                    await state["assistant_msg"].stream_token(char)
                    state["buffer"].append((char, "tool_output"))
                    await asyncio.sleep(0.001)  # Small delay for visual effect
                    
                for char in output_content:
                    await state["assistant_msg"].stream_token(char)
                    state["buffer"].append((char, "tool_output"))
                    await asyncio.sleep(0.001)  # Small delay for visual effect
                    
                for char in output_closing:
                    await state["assistant_msg"].stream_token(char)
                    state["buffer"].append((char, "tool_output"))
                    await asyncio.sleep(0.001)  # Small delay for visual effect
            except Exception as e:
                logger.error(f"Error processing tool output: {e}")
                return

        # ── final assistant chunk that is not streamed as delta ────────────────
        elif item.type == "message_output_item":
            txt = ItemHelpers.text_message_output(item)
            
            # Stream tokens character by character like CLI
            for char in txt:
                await state["assistant_msg"].stream_token(char)
                state["buffer"].append((char, "assistant"))
                await asyncio.sleep(0.001)  # Small delay for visual effect
            
    except Exception as e:
        # Catch any exceptions to prevent the event handling from crashing
        logger.exception(f"Error in handle_event: {e}")
        # Try to notify the user about the error
        try:
            await state["assistant_msg"].stream_token(f"\n\n[Error processing response: {str(e)}]\n\n")
        except Exception:
            pass

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
        
        # Reset the agent - using SmartAgent wrapper class
        smart_agent = SmartAgent(
            model_name=cl.user_session.model_name,
            openai_client=cl.user_session.client,
            mcp_servers=cl.user_session.mcp_servers_objects,
            system_prompt=PromptGenerator.create_system_prompt(),
        )
        
        cl.user_session.smart_agent = smart_agent
        await cl.Message(content="Conversation history cleared", author="System").send()
        return
    
    # Check for exit command
    if user_input.lower() in ["exit", "quit"]:
        await cl.Message(content="Exiting chat...", author="System").send()
        return
    
    # Add the user message to history
    conv.append({"role": "user", "content": user_input})

    # Create a placeholder message that will receive streamed tokens
    assistant_msg = cl.Message(content="", author="Smart Agent")
    await assistant_msg.send()

    # State container passed to the event handler with buffer for token streaming
    state = {
        "assistant_msg": assistant_msg,
        "buffer": [],  # Buffer for token streaming like CLI
        "current_type": "assistant",  # Default type is assistant message
        "is_thought": False           # Track pending <thought> output
    }

    try:
        # Define constants for consistent output like CLI
        output_interval = 0.05  # 50ms between outputs
        output_size = 6  # Output 6 characters at a time
        
        # Define colors for different content types like CLI
        type_colors = {
            "assistant": "green",
            "thought": "cyan",
            "tool_output": "bright_green",
            "tool": "yellow",
            "error": "red",
            "system": "magenta"
        }
        
        # Function to stream output at a consistent rate with different colors like CLI
        async def stream_output():
            try:
                while True:
                    if state["buffer"]:
                        # Get a batch of tokens from the buffer
                        batch = []
                        current_batch_type = None
                        
                        for _ in range(min(output_size, len(state["buffer"]))):
                            if not state["buffer"]:
                                break
                                
                            item = state["buffer"].pop(0)
                            
                            # Initialize batch type if not set
                            if current_batch_type is None:
                                current_batch_type = item[1]
                            
                            # If type changes within batch, process current batch and start new one
                            if item[1] != current_batch_type:
                                # Process batch
                                batch = [item[0]]
                                current_batch_type = item[1]
                            else:
                                batch.append(item[0])
                        
                        # Process any remaining batch content
                        if batch:
                            # In Chainlit, we stream tokens directly
                            pass
                    
                    await asyncio.sleep(output_interval)
            except asyncio.CancelledError:
                # Task cancellation is expected on completion
                pass
        
        # Start the streaming task
        streaming_task = asyncio.create_task(stream_output())
        
        # Run the agent with the conversation history
        result = Runner.run_streamed(cl.user_session.smart_agent.agent, conv, max_turns=100)
        assistant_reply = ""
        
        # Process the stream events
        async for ev in result.stream_events():
            await handle_event(ev, state)
            
        # Update the assistant message with final content
        await assistant_msg.update()
        
        # Cancel the streaming task
        streaming_task.cancel()
        try:
            await streaming_task
        except asyncio.CancelledError:
            pass
        
        # Add assistant message to conversation history
        conv.append({"role": "assistant", "content": assistant_msg.content})
        
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
    finally:
        if hasattr(result, "aclose"):
            await result.aclose()

@cl.on_chat_end
async def on_chat_end():
    """Clean up resources when the chat session ends."""
    logger.info("Cleaning up resources...")

    try:
        # Clean up MCP servers
        if hasattr(cl.user_session, 'mcp_servers_objects'):
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
