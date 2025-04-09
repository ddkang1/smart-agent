"""
Chainlit web interface for Smart Agent.
This is a direct reflection of the CLI chat client.
"""

import os
import sys
import json
import asyncio
import logging
from typing import List, Dict, Any, Optional

import chainlit as cl

# Add parent directory to path to import smart_agent modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from smart_agent.tool_manager import ConfigManager
from smart_agent.agent import PromptGenerator

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Disable httpx and mcp.client.sse logs to reduce noise
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("mcp.client.sse").setLevel(logging.WARNING)

# Suppress asyncio errors about event loop being closed
# These are not critical and just add noise to the logs
logging.getLogger("asyncio").setLevel(logging.WARNING)

# Global variables
config_manager = None

@cl.on_settings_update
async def handle_settings_update(settings):
    """Handle settings updates from the UI."""
    # Update API key and other settings
    config_manager.set_api_key(settings.get("api_key", ""))
    config_manager.set_api_base_url(settings.get("api_base_url", ""))
    config_manager.set_model_name(settings.get("model_name", ""))
    
    # Save settings to config file
    config_manager.save_config()
    
    await cl.Message(
        content="Settings updated successfully!",
        author="System"
    ).send()

@cl.on_chat_start
async def on_chat_start():
    """Initialize the chat session."""
    global config_manager
    
    # Initialize config manager
    config_manager = ConfigManager()
    
    # Set up settings
    await cl.ChatSettings(
        [
            cl.input_widget.TextInput(
                id="api_key",
                label="OpenAI API Key",
                initial=config_manager.get_api_key() or "",
                placeholder="Enter your OpenAI API key",
                password=True,
            ),
            cl.input_widget.TextInput(
                id="api_base_url",
                label="API Base URL",
                initial=config_manager.get_api_base_url() or "https://api.openai.com/v1",
                placeholder="Enter API base URL",
            ),
            cl.input_widget.TextInput(
                id="model_name",
                label="Model Name",
                initial=config_manager.get_model_name() or "gpt-4o",
                placeholder="Enter model name",
            ),
        ]
    ).send()
    
    # Initialize conversation history
    cl.user_session.conversation_history = [{"role": "system", "content": PromptGenerator.create_system_prompt()}]
    
    # Welcome message
    await cl.Message(
        content="Welcome to Smart Agent! I'm ready to help you with your tasks.",
        author="Smart Agent"
    ).send()

@cl.on_message
async def on_message(message: cl.Message):
    """Process user messages."""
    # Get user input
    user_input = message.content
    
    # Check if API key is set
    api_key = config_manager.get_api_key()
    if not api_key:
        await cl.Message(
            content="Please set your OpenAI API key in the settings panel.",
            author="System"
        ).send()
        return
    
    # Create an agent steps element to track reasoning
    async with cl.Step(name="Agent Reasoning") as agent_steps:
        try:
            # Import required libraries
            try:
                from openai import AsyncOpenAI
            except ImportError:
                await cl.Message(
                    content="OpenAI package not installed. Please install it with 'pip install openai'",
                    author="System"
                ).send()
                return
            
            # Check if required packages are installed
            try:
                from agents import Agent, OpenAIChatCompletionsModel, Runner, ItemHelpers
                from agents.mcp import MCPServerSse
            except ImportError:
                await cl.Message(
                    content="Required packages not installed. Run 'pip install openai-agents' to use the agent.",
                    author="System"
                ).send()
                return
            
            # Add user message to conversation history
            cl.user_session.conversation_history.append({"role": "user", "content": user_input})
            
            # Get API configuration
            api_key = config_manager.get_api_key()
            base_url = config_manager.get_api_base_url()
            model_name = config_manager.get_model_name()
            
            # Initialize OpenAI client
            client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            
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
            
            # Create the agent
            agent = Agent(
                name="Assistant",
                instructions=cl.user_session.conversation_history[0]["content"],
                model=OpenAIChatCompletionsModel(
                    model=model_name,
                    openai_client=client,
                ),
                mcp_servers=mcp_servers_objects,
            )
            
            # Connect to MCP servers
            for server in mcp_servers_objects:
                try:
                    await server.connect()
                except Exception as e:
                    logger.error(f"Error connecting to MCP server: {e}")
                    await cl.Message(
                        content=f"Error connecting to a tool: {e}",
                        author="System"
                    ).send()
                    # Clean up already connected servers
                    for s in mcp_servers_objects:
                        try:
                            if hasattr(s, 'cleanup') and callable(s.cleanup):
                                await s.cleanup()
                        except Exception as cleanup_error:
                            logger.error(f"Error during server cleanup: {cleanup_error}")
                    return
            
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
            
            finally:
                # Clean up MCP servers
                for server in mcp_servers_objects:
                    if hasattr(server, 'cleanup') and callable(server.cleanup):
                        try:
                            await server.cleanup()
                        except Exception as e:
                            logger.error(f"Error during server cleanup: {e}")
        
        except Exception as e:
            # Handle any errors
            error_message = f"An error occurred: {str(e)}"
            logger.exception(error_message)
            await cl.Message(content=f"I encountered an error: {error_message}", author="Smart Agent").send()

if __name__ == "__main__":
    # This is used when running locally with `chainlit run`
    # The port can be overridden with the `--port` flag
    import argparse
    
    parser = argparse.ArgumentParser(description="Run the Chainlit web UI for Smart Agent")
    parser.add_argument("--port", type=int, default=8000, help="Port to run the server on")
    
    args = parser.parse_args()
    
    # Note: Chainlit handles the server startup when run with `chainlit run`
