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


async def process_agent_message(
    smart_agent: SmartAgent,
    conversation_history: List[Dict[str, str]],
) -> str:
    """
    Process a message with the agent and return the response.

    Args:
        smart_agent: The SmartAgent instance
        conversation_history: The conversation history

    Returns:
        The assistant's response
    """
    try:
        # Process the message with the agent
        result = await smart_agent.process_message(
            history=conversation_history,
            max_turns=100,
            update_system_prompt=True,
        )
        
        # Process the stream events
        assistant_reply = await SmartAgent.process_stream_events(
            result=result,
            callback=None,
            verbose=True,
        )
        
        return assistant_reply
    except Exception as e:
        console.print(f"\\n[bold red]Error processing message:[/] {e}")
        return f"I'm sorry, I encountered an error: {str(e)}. Please try again."


def run_chat_loop(config_manager: ConfigManager) -> None:
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
        console.print("[bold red]Error:[/] API key is not set in config.yaml or environment variable.")
        console.print("Please set the api_key in config/config.yaml or use OPENAI_API_KEY environment variable.")
        return

    # Get model configuration
    model_name = config_manager.get_model_name()
    temperature = config_manager.get_model_temperature()

    # Get Langfuse configuration
    langfuse_config = config_manager.get_langfuse_config()
    langfuse_enabled = langfuse_config.get("enabled", False)
    langfuse = None

    # Initialize Langfuse if enabled
    if langfuse_enabled and Langfuse:
        try:
            langfuse = Langfuse(
                public_key=langfuse_config.get("public_key", ""),
                secret_key=langfuse_config.get("secret_key", ""),
                host=langfuse_config.get("host", "https://cloud.langfuse.com"),
            )
            console.print("[green]Langfuse monitoring enabled[/]")
        except Exception as e:
            console.print(f"[yellow]Error initializing Langfuse: {e}[/]")
            langfuse_enabled = False
    elif langfuse_enabled:
        console.print(
            "[yellow]Langfuse package not installed. Run 'pip install langfuse' to enable monitoring.[/]"
        )
        langfuse_enabled = False

    try:
        # Check if required packages are installed
        if not AsyncOpenAI:
            console.print(
                "[bold red]Required packages not installed. Run 'pip install openai agent' to use the agent.[/]"
            )
            return

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
            console.print(f"Adding {tool_name} at {tool_url} to agent")
            mcp_servers.append(tool_url)

        # Create the agent - using SmartAgent wrapper class
        smart_agent = SmartAgent(
            model_name=model_name,
            openai_client=client,
            mcp_servers=mcp_servers,
            system_prompt=PromptGenerator.create_system_prompt(),
        )

        console.print(f"Agent initialized with {len(mcp_servers)} tools")

    except Exception as e:
        console.print(f"[bold red]Error initializing agent:[/] {e}")
        return

    console.print("\n[bold]Smart Agent Chat[/]")
    console.print("Type 'exit' or 'quit' to end the conversation")
    console.print("Type 'clear' to clear the conversation history")

    # Initialize conversation history
    conversation_history = [{"role": "system", "content": PromptGenerator.create_system_prompt()}]

    # Chat loop
    while True:
        # Get user input
        user_input = input("\nYou: ")

        # Check for exit command
        if user_input.lower() in ["exit", "quit"]:
            console.print("Exiting chat...")
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
            console.print("Conversation history cleared")
            continue

        # Add the user message to history
        conversation_history.append({"role": "user", "content": user_input})

        # Get assistant response
        console.print("\nAssistant: ", end="")

        try:
            # Run the agent in an event loop
            assistant_response = asyncio.run(process_agent_message(smart_agent, conversation_history))

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
                        name="chat_response",
                        model=model_name,
                        prompt=user_input,
                        completion=assistant_response,
                    )
                except Exception as e:
                    console.print(f"[yellow]Error logging to Langfuse: {e}[/]")
        except Exception as e:
            console.print(f"[bold red]Error:[/] {e}")


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
