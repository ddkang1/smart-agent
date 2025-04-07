"""
Chat command implementation for the Smart Agent CLI.
"""

import json
import asyncio
from typing import List, Dict, Any, Optional

import click
from rich.console import Console

from ..tool_manager import ConfigManager
from ..agent import SmartAgent, PromptGenerator

# Initialize console for rich output
console = Console()

# Import optional dependencies
try:
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None

try:
    from langfuse import Langfuse
except ImportError:
    Langfuse = None

def run_chat_loop(config_manager: ConfigManager):
    """
    Run the chat loop.

    Args:
        config_manager: Configuration manager instance
    """
    # Get API configuration
    api_key = config_manager.get_api_key()
    base_url = config_manager.get_api_base_url()

    # Check if API key is set
    if not api_key:
        print("Error: API key is not set in config.yaml or environment variable.")
        return

    # Get model configuration
    model_name = config_manager.get_model_name()
    temperature = config_manager.get_model_temperature()

    # Get Langfuse configuration
    langfuse_config = config_manager.get_langfuse_config()
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
            print("Langfuse monitoring enabled")
        except ImportError:
            print(
                "Langfuse package not installed. Run 'pip install langfuse' to enable monitoring."
            )
            langfuse_enabled = False

    try:
        # Import required libraries
        from openai import AsyncOpenAI
        from smart_agent.agent import SmartAgent

        # Initialize AsyncOpenAI client
        client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
        )

        # Get enabled tools
        enabled_tools = []
        for tool_id, tool_config in config_manager.get_tools_config().items():
            if config_manager.is_tool_enabled(tool_id):
                tool_url = config_manager.get_tool_url(tool_id)
                tool_name = tool_config.get("name", tool_id)
                enabled_tools.append((tool_id, tool_name, tool_url))

        # Create MCP server list for the agent
        mcp_servers = []
        for tool_id, tool_name, tool_url in enabled_tools:
            print(f"Adding {tool_name} at {tool_url} to agent")
            mcp_servers.append(tool_url)

        # Create the agent - using SmartAgent wrapper class
        smart_agent = SmartAgent(
            model_name=model_name,
            openai_client=client,
            mcp_servers=mcp_servers,
            system_prompt=PromptGenerator.create_system_prompt(),
        )

        print(f"Agent initialized with {len(mcp_servers)} tools")

    except ImportError:
        print(
            "Required packages not installed. Run 'pip install openai agent' to use the agent."
        )
        return

    print("\nSmart Agent Chat")
    print("Type 'exit' or 'quit' to end the conversation")
    print("Type 'clear' to clear the conversation history")

    # Initialize conversation history
    conversation_history = [{"role": "system", "content": PromptGenerator.create_system_prompt()}]

    # Chat loop
    while True:
        # Get user input
        user_input = input("\nYou: ")

        # Check for exit command
        if user_input.lower() in ["exit", "quit"]:
            print("Exiting chat...")
            break

        # Check for clear command
        if user_input.lower() == "clear":
            # Reset the conversation history
            conversation_history = [{"role": "system", "content": PromptGenerator.create_system_prompt()}]

            # Reset the agent - using SmartAgent wrapper class
            smart_agent = SmartAgent(
                model_name=model_name,
                openai_client=client,
                mcp_servers=mcp_servers,
                system_prompt=PromptGenerator.create_system_prompt(),
            )
            print("Conversation history cleared")
            continue

        # Add the user message to history
        conversation_history.append({"role": "user", "content": user_input})

        # Get assistant response
        print("\nAssistant: ", end="", flush=True)

        try:
            # Use the agent for streaming response
            async def run_agent():
                # Add the user message to history
                history = conversation_history.copy()

                # Get the MCP server URLs
                mcp_urls = [url for url in mcp_servers if isinstance(url, str)]

                # Create the OpenAI client
                client = AsyncOpenAI(
                    base_url=base_url,
                    api_key=api_key,
                )

                # Import required classes
                from agents.mcp import MCPServerSse
                from agents import Agent, OpenAIChatCompletionsModel, Runner, ItemHelpers

                # Create MCP servers using the same pattern as research.py
                mcp_servers_objects = []
                for url in mcp_urls:
                    mcp_servers_objects.append(MCPServerSse(params={"url": url}))

                # Connect to all MCP servers
                for server in mcp_servers_objects:
                    await server.connect()

                try:
                    # Create the agent directly like in research.py
                    agent = Agent(
                        name="Assistant",
                        instructions=history[0]["content"] if history and history[0]["role"] == "system" else None,
                        model=OpenAIChatCompletionsModel(
                            model=model_name,
                            openai_client=client,
                        ),
                        mcp_servers=mcp_servers_objects,
                    )

                    # Run the agent with the conversation history
                    result = Runner.run_streamed(agent, history, max_turns=100)
                    assistant_reply = ""
                    is_thought = False

                    # Process the stream events exactly like in research.py
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
                                        print(f"\n[thought]:\n{value}", flush=True)
                                        assistant_reply += "\n[thought]: " + value
                                    else:
                                        is_thought = False
                                        print(f"\n[{key}]:\n{value}", flush=True)
                                except (json.JSONDecodeError, StopIteration) as e:
                                    print(f"\n[Error parsing tool call]: {e}", flush=True)
                            elif event.item.type == "tool_call_output_item":
                                if not is_thought:
                                    try:
                                        output_text = json.loads(event.item.output).get("text", "")
                                        print(f"\n[Tool Output]:\n{output_text}", flush=True)
                                    except json.JSONDecodeError:
                                        print(f"\n[Tool Output]:\n{event.item.output}", flush=True)
                            elif event.item.type == "message_output_item":
                                role = event.item.raw_item.role
                                text_message = ItemHelpers.text_message_output(event.item)
                                if role == "assistant":
                                    print(f"\n[{role}]:\n{text_message}", flush=True)
                                    assistant_reply += "\n[response]: " + text_message
                                else:
                                    print(f"\n[{role}]:\n{text_message}", flush=True)

                    return assistant_reply.strip()
                finally:
                    # Clean up MCP servers
                    for server in mcp_servers_objects:
                        if hasattr(server, 'cleanup') and callable(server.cleanup):
                            try:
                                if asyncio.iscoroutinefunction(server.cleanup):
                                    await server.cleanup()  # Use await for async cleanup
                                else:
                                    server.cleanup()  # Call directly for sync cleanup
                            except Exception as e:
                                print(f"Error during server cleanup: {e}")

            # Run the agent in an event loop
            import asyncio
            assistant_response = asyncio.run(run_agent())

            # Append the assistant's response to maintain context
            conversation_history.append({"role": "assistant", "content": assistant_response})

            # Log to Langfuse if enabled
            if langfuse_enabled and langfuse:
                try:
                    trace = langfuse.trace(
                        name="chat_session",
                        metadata={"model": model_name, "temperature": temperature},
                    )
                    trace.generation(
                        name="assistant_response",
                        model=model_name,
                        prompt=user_input,
                        completion="Agent response (not captured)",
                    )
                except Exception as e:
                    print(f"Langfuse logging error: {e}")

        except KeyboardInterrupt:
            print("\nOperation interrupted by user.")
            continue
        except asyncio.CancelledError:
            print("\nOperation cancelled.")
            continue
        except Exception as e:
            print(f"\nError: {e}")
            import traceback
            traceback.print_exc()

    print("\nChat session ended")



@click.command()
@click.option(
    "--config",
    default=None,
    help="Path to configuration file",
)
@click.option(
    "--tools",
    default=None,
    help="Path to tools configuration file",
)
def chat(config, tools):
    """
    Start a chat session with the agent.

    Args:
        config: Path to configuration file
        tools: Path to tools configuration file
    """
    # Create configuration manager
    config_manager = ConfigManager(config_path=config, tools_path=tools)
    
    # Run the chat loop
    run_chat_loop(config_manager)
