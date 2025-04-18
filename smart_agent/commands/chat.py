"""
Chat command implementation for the Smart Agent CLI.
"""

import json
import asyncio
import logging
from typing import List, Dict, Any, Optional

import click
from rich.console import Console

# Set up logging
logger = logging.getLogger(__name__)

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
        # print("\nAssistant: ", end="", flush=True)

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
                from agents.mcp import MCPServerSse, MCPServerStdio
                from agents import Agent, OpenAIChatCompletionsModel, Runner, ItemHelpers

                # Create MCP servers based on transport type
                mcp_servers_objects = []
                for tool_id, tool_config in config_manager.get_tools_config().items():
                    if not config_manager.is_tool_enabled(tool_id):
                        continue

                    transport_type = tool_config.get("transport", "stdio_to_sse").lower()

                    # For SSE-based transports (stdio_to_sse, sse), use MCPServerSse
                    if transport_type in ["stdio_to_sse", "sse"]:
                        url = tool_config.get("url")
                        if url:
                            mcp_servers_objects.append(MCPServerSse(name=tool_id, params={"url": url}))
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

                    # Import rich for colorful output
                    from rich.console import Console
                    from rich.panel import Panel
                    from rich.markdown import Markdown

                    # Create a console for rich output
                    rich_console = Console()
                    # Set stdout to line buffering for more immediate output
                    import sys
                    sys.stdout.reconfigure(line_buffering=True)

                    # Process the stream events with rich colorful output
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
                                        rich_console.print(Panel(value, title="Thought", border_style="cyan", title_align="left"))
                                        # Ensure output is flushed immediately
                                        sys.stdout.flush()
                                        assistant_reply += "\n[thought]: " + value
                                    else:
                                        is_thought = False
                                        rich_console.print(Panel(value, title=key, border_style="yellow", title_align="left"))
                                        # Ensure output is flushed immediately
                                        sys.stdout.flush()
                                except (json.JSONDecodeError, StopIteration) as e:
                                    rich_console.print(f"[bold red]Error parsing tool call:[/] {e}")
                                    # Ensure output is flushed immediately
                                    sys.stdout.flush()
                            elif event.item.type == "tool_call_output_item":
                                if not is_thought:
                                    try:
                                        output_text = json.loads(event.item.output).get("text", "")
                                        rich_console.print(Panel(output_text, title="Tool Output", border_style="green", title_align="left"))
                                        # Ensure output is flushed immediately
                                        sys.stdout.flush()
                                    except json.JSONDecodeError:
                                        rich_console.print(Panel(event.item.output, title="Tool Output", border_style="green", title_align="left"))
                                        # Ensure output is flushed immediately
                                        sys.stdout.flush()
                            elif event.item.type == "message_output_item":
                                role = event.item.raw_item.role
                                text_message = ItemHelpers.text_message_output(event.item)
                                if role == "assistant":
                                    # Try to render as markdown if possible
                                    try:
                                        rich_console.print(Panel(Markdown(text_message), title="Assistant", border_style="blue", title_align="left"))
                                        # Ensure output is flushed immediately
                                        sys.stdout.flush()
                                    except Exception:
                                        rich_console.print(Panel(text_message, title="Assistant", border_style="blue", title_align="left"))
                                        # Ensure output is flushed immediately
                                        sys.stdout.flush()
                                    assistant_reply += "\n[response]: " + text_message
                                else:
                                    rich_console.print(Panel(text_message, title=role.capitalize(), border_style="magenta", title_align="left"))
                                    # Ensure output is flushed immediately
                                    sys.stdout.flush()

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
