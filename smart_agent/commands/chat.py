"""
OpenAI MCP Chat - Combines OpenAI agents with MCP connection management in a continuous chat loop.
"""

import asyncio
import json
import os
import sys
import logging
import readline
from typing import List, Dict, Any, Optional
from contextlib import AsyncExitStack
from collections import deque

# Set up logging
logger = logging.getLogger(__name__)

# Configure OpenAI client logger to suppress retry messages
openai_logger = logging.getLogger("openai")
openai_logger.setLevel(logging.WARNING)

# Configure MCP client logger to suppress verbose messages
mcp_client_logger = logging.getLogger("mcp.client")
mcp_client_logger.setLevel(logging.WARNING)

import click
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.text import Text

# Import OpenAI agents components
from agents import Agent, Runner, gen_trace_id, trace, ItemHelpers
from agents.mcp import MCPServer, MCPServerSse
from agents import OpenAIChatCompletionsModel

# Import OpenAI client
from openai import AsyncOpenAI

# Import Smart Agent components
from ..tool_manager import ConfigManager
from ..agent import PromptGenerator

# Initialize console for rich output
console = Console()

class SmartAgent:
    """
    OpenAI MCP Chat class that combines OpenAI agents with MCP connection management
    in a continuous chat loop.
    """

    def __init__(self, config_manager: ConfigManager):
        """
        Initialize the OpenAI MCP Chat.

        Args:
            config_manager: Configuration manager instance
        """
        self.config_manager = config_manager
        self.api_key = config_manager.get_api_key()
        self.base_url = config_manager.get_api_base_url()
        self.model_name = config_manager.get_model_name()
        self.temperature = config_manager.get_model_temperature()
        self.mcp_servers = []
        self.conversation_history = []
        self.system_prompt = PromptGenerator.create_system_prompt()
        
        # Get Langfuse configuration
        self.langfuse_config = config_manager.get_langfuse_config()
        self.langfuse_enabled = self.langfuse_config.get("enabled", False)
        self.langfuse = None
        
        # Initialize Langfuse if enabled
        if self.langfuse_enabled:
            try:
                from langfuse import Langfuse
                
                self.langfuse = Langfuse(
                    public_key=self.langfuse_config.get("public_key", ""),
                    secret_key=self.langfuse_config.get("secret_key", ""),
                    host=self.langfuse_config.get("host", "https://cloud.langfuse.com"),
                )
                print("Langfuse monitoring enabled")
            except ImportError:
                print(
                    "Langfuse package not installed. Run 'pip install langfuse' to enable monitoring."
                )
                self.langfuse_enabled = False
        
        # Initialize AsyncOpenAI client
        self.openai_client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
        )

    def setup_mcp_servers(self) -> List[MCPServer]:
        """
        Set up MCP servers based on the configuration.

        Returns:
            List of MCP server objects
        """
        mcp_servers = []
        
        # Get enabled tools
        for tool_id, tool_config in self.config_manager.get_tools_config().items():
            if not self.config_manager.is_tool_enabled(tool_id):
                continue
                
            transport_type = tool_config.get("transport", "stdio_to_sse").lower()
            
            # For SSE-based transports (stdio_to_sse, sse), use MCPServerSse
            if transport_type in ["stdio_to_sse", "sse"]:
                url = tool_config.get("url")
                if url:
                    logger.info(f"Adding MCP server {tool_id} at {url}")
                    mcp_servers.append(MCPServerSse(
                        name=tool_id,
                        params={"url": url}
                    ))
            # For stdio transport, use MCPServerStdio with the command directly
            elif transport_type == "stdio":
                command = tool_config.get("command")
                if command:
                    # Import MCPServerStdio here to avoid circular imports
                    from agents.mcp import MCPServerStdio
                    
                    # For MCPServerStdio, we need to split the command into command and args
                    command_parts = command.split()
                    executable = command_parts[0]
                    args = command_parts[1:] if len(command_parts) > 1 else []
                    mcp_servers.append(MCPServerStdio(
                        name=tool_id,
                        params={
                            "command": executable,
                            "args": args
                        }
                    ))
            # For sse_to_stdio transport, always construct the command from the URL
            elif transport_type == "sse_to_stdio":
                # Get the URL from the configuration
                url = tool_config.get("url")
                if url:
                    # Import MCPServerStdio here to avoid circular imports
                    from agents.mcp import MCPServerStdio
                    
                    # Construct the full supergateway command
                    command = f"npx -y supergateway --sse \"{url}\""
                    logger.debug(f"Constructed command for sse_to_stdio transport: '{command}'")
                    # For MCPServerStdio, we need to split the command into command and args
                    command_parts = command.split()
                    executable = command_parts[0]
                    args = command_parts[1:] if len(command_parts) > 1 else []
                    mcp_servers.append(MCPServerStdio(
                        name=tool_id,
                        params={
                            "command": executable,
                            "args": args
                        }
                    ))
                else:
                    logger.warning(f"Missing URL for sse_to_stdio transport type for tool {tool_id}")
            # For any other transport types, log a warning
            else:
                logger.warning(f"Unknown transport type '{transport_type}' for tool {tool_id}")
        
        return mcp_servers

    async def process_query(self, query: str, history: List[Dict[str, str]] = None) -> str:
        """
        Process a query using the OpenAI agent with MCP tools.

        Args:
            query: The user's query
            history: Optional conversation history

        Returns:
            The agent's response
        """
        # Create message history with system prompt and user query if not provided
        if history is None:
            history = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": query}
            ]
        
        # Configure rich console for smoother output
        rich_console = Console(soft_wrap=True, highlight=False)
        
        # Set stdout to line buffering for more immediate output
        import sys
        sys.stdout.reconfigure(line_buffering=True)
        
        # Create a buffer for tokens with type information
        buffer = deque()
        stream_ended = asyncio.Event()
        current_type = "assistant"  # Default type is assistant message
        
        # Define constants for consistent output
        output_interval = 0.05  # 50ms between outputs
        output_size = 6  # Output 6 characters at a time
        
        # Define colors for different content types
        type_colors = {
            "assistant": "green",
            "thought": "cyan",
            "tool_output": "bright_green",
            "tool": "yellow",
            "error": "red",
            "system": "magenta"
        }
        
        # Function to add content to buffer with type information
        def add_to_buffer(content, content_type="assistant"):
            # Add special marker for type change
            if buffer and buffer[-1][1] != content_type:
                buffer.append(("TYPE_CHANGE", content_type))
            
            # Add each character with its type
            for char in content:
                buffer.append((char, content_type))
        
        # Function to stream output at a consistent rate with different colors
        async def stream_output(buffer, interval, size, end_event):
            nonlocal current_type
            try:
                while not end_event.is_set() or buffer:  # Continue until signaled and buffer is empty
                    if buffer:
                        # Get a batch of tokens from the buffer
                        batch = []
                        current_batch_type = None
                        
                        for _ in range(min(size, len(buffer))):
                            if not buffer:
                                break
                                
                            item = buffer.popleft()
                            
                            # Handle type change marker
                            if item[0] == "TYPE_CHANGE":
                                if batch:  # Print current batch before changing type
                                    rich_console.print(''.join(batch), end="", style=type_colors.get(current_batch_type, "green"))
                                    batch = []
                                current_type = item[1]
                                current_batch_type = current_type
                                continue
                            
                            # Initialize batch type if not set
                            if current_batch_type is None:
                                current_batch_type = item[1]
                            
                            # If type changes within batch, print current batch and start new one
                            if item[1] != current_batch_type:
                                rich_console.print(''.join(batch), end="", style=type_colors.get(current_batch_type, "green"))
                                batch = [item[0]]
                                current_batch_type = item[1]
                            else:
                                batch.append(item[0])
                        
                        # Print any remaining batch content
                        if batch:
                            rich_console.print(''.join(batch), end="", style=type_colors.get(current_batch_type, "green"))
                    
                    await asyncio.sleep(interval)
            except asyncio.CancelledError:
                # Task cancellation is expected on completion
                pass
        
        # Track the assistant's response
        assistant_reply = ""
        
        # Create an agent with the current model settings
        agent = Agent(
            name="Assistant",
            instructions=self.system_prompt,
            model=OpenAIChatCompletionsModel(
                model=self.model_name,
                openai_client=self.openai_client,
            ),
            mcp_servers=self.mcp_servers,
        )
        
        # Print the assistant prefix with rich styling
        rich_console.print("\nAssistant: ", end="", style="bold green")
        
        # Start the streaming task
        streaming_task = asyncio.create_task(
            stream_output(buffer, output_interval, output_size, stream_ended)
        )
        
        try:
            # Run the agent with streaming
            result = Runner.run_streamed(agent, history, max_turns=100)
            is_thought = False
            
            # Process the stream events with a holistic output approach
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
                                
                                # Add the opening thought tag to the buffer with thought type
                                add_to_buffer("\n<thought>", "thought")
                                
                                # Add the thought content with thought type
                                add_to_buffer(str(value), "thought")
                                
                                # Add the closing thought tag with thought type
                                add_to_buffer("</thought>", "thought")
                                
                                # Update assistant reply
                                assistant_reply += f"\n<thought>{value}</thought>"
                            else:
                                is_thought = False
                                
                                # Check if this is a code tool
                                if key == "code":
                                    # Get code string
                                    code_str = str(value)
                                    
                                    # Add tool call to buffer with tool type
                                    tool_opening = f"\n<tool name=\"{key}\">"
                                    add_to_buffer(tool_opening, "tool")
                                    
                                    # Add code with markdown formatting (no language specification)
                                    add_to_buffer(f"\n```\n", "tool")
                                    add_to_buffer(code_str, "tool")
                                    add_to_buffer("\n```", "tool")
                                    
                                    add_to_buffer("</tool>", "tool")
                                    
                                    # Update assistant reply with formatted code (no language specification)
                                    assistant_reply += f"\n<tool name=\"{key}\">\n```\n{code_str}\n```</tool>"
                                else:
                                    # Regular tool call
                                    tool_opening = f"\n<tool name=\"{key}\">"
                                    add_to_buffer(tool_opening, "tool")
                                    add_to_buffer(str(value), "tool")
                                    add_to_buffer("</tool>", "tool")
                                    
                                    # Update assistant reply
                                    assistant_reply += f"\n<tool name=\"{key}\">{value}</tool>"
                        except (json.JSONDecodeError, StopIteration) as e:
                            # Add error to buffer with error type
                            error_text = f"Error parsing tool call: {e}"
                            add_to_buffer("\n<error>", "error")
                            add_to_buffer(error_text, "error")
                            add_to_buffer("</error>", "error")
                            
                            # Update assistant reply
                            assistant_reply += f"\n<error>{error_text}</error>"
                    elif event.item.type == "tool_call_output_item":
                        if not is_thought:
                            try:
                                output_text = json.loads(event.item.output).get("text", "")
                                
                                # Pause token streaming
                                stream_ended.set()
                                await streaming_task
                                
                                # Print tool output all at once
                                rich_console.print("\n<tool_output>", end="", style="bright_green bold")
                                rich_console.print(str(output_text), style="bright_green", end="")
                                    
                                rich_console.print("</tool_output>", style="bright_green bold")
                                
                                # Ensure output is flushed immediately
                                sys.stdout.flush()
                                
                                # Update assistant reply
                                assistant_reply += f"\n<tool_output>{output_text}</tool_output>"
                                
                                # Reset for continued streaming
                                stream_ended.clear()
                                streaming_task = asyncio.create_task(
                                    stream_output(buffer, output_interval, output_size, stream_ended)
                                )
                            except json.JSONDecodeError:
                                # Pause token streaming
                                stream_ended.set()
                                await streaming_task
                                
                                # Print tool output all at once
                                rich_console.print("\n<tool_output>", end="", style="bright_green bold")
                                rich_console.print(str(event.item.output), style="bright_green", end="")
                                    
                                rich_console.print("</tool_output>", style="bright_green bold")
                                
                                # Ensure output is flushed immediately
                                sys.stdout.flush()
                                
                                # Update assistant reply
                                assistant_reply += f"\n<tool_output>{event.item.output}</tool_output>"
                                
                                # Reset for continued streaming
                                stream_ended.clear()
                                streaming_task = asyncio.create_task(
                                    stream_output(buffer, output_interval, output_size, stream_ended)
                                )
                    elif event.item.type == "message_output_item":
                        role = event.item.raw_item.role
                        text_message = ItemHelpers.text_message_output(event.item)
                        if role == "assistant":
                            # Add tokens to buffer for streaming with assistant type
                            add_to_buffer(text_message, "assistant")
                            assistant_reply += text_message
                        else:
                            # Add system message to buffer with system type
                            add_to_buffer(f"\n<{role}>", "system")
                            add_to_buffer(str(text_message), "system")
                            add_to_buffer(f"</{role}>", "system")
                            
                            # Update assistant reply
                            assistant_reply += f"\n<{role}>{text_message}</{role}>"
            
            # Signal that the stream has ended
            stream_ended.set()
            # Wait for the streaming task to finish processing the buffer
            await streaming_task
            
            # Add a newline after completion
            print()
            
            return assistant_reply.strip()
        except Exception as e:
            # Log the error and return a user-friendly message
            logger.error(f"Error processing query: {e}")
            return f"I'm sorry, I encountered an error: {str(e)}. Please try again later."
        finally:
            # Make sure the streaming task is properly cleaned up
            if not stream_ended.is_set():
                stream_ended.set()
                try:
                    await streaming_task
                except:
                    pass

    async def run_chat_loop(self):
        """
        Run the chat loop with OpenAI agent and MCP tools.
        """
        # Check if API key is set
        if not self.api_key:
            print("Error: API key is not set in config.yaml or environment variable.")
            return

        print("\nSmart Agent Chat")
        print("Type 'exit' or 'quit' to end the conversation")
        print("Type 'clear' to clear the conversation history")

        # Set up readline for command history
        history_file = os.path.expanduser("~/.smart_agent_history")
        try:
            readline.read_history_file(history_file)
            readline.set_history_length(1000)
        except FileNotFoundError:
            pass
            
        # Enable arrow key navigation through history
        readline.parse_and_bind('"\e[A": previous-history')  # Up arrow
        readline.parse_and_bind('"\e[B": next-history')      # Down arrow
        
        # Initialize conversation history with system prompt
        self.conversation_history = [{"role": "system", "content": self.system_prompt}]
        
        # Set up MCP servers
        self.mcp_servers = self.setup_mcp_servers()
        
        # Chat loop
        async with AsyncExitStack() as exit_stack:
            # Connect to all MCP servers
            for server in self.mcp_servers:
                await exit_stack.enter_async_context(server)
                logger.info(f"Connected to MCP server: {server.name}")
            
            while True:
                # Get user input with history support
                user_input = input("\nYou: ")
                
                # Add non-empty inputs to history
                if user_input.strip() and user_input.lower() not in ["exit", "quit", "clear"]:
                    readline.add_history(user_input)
                
                # Check for exit command
                if user_input.lower() in ["exit", "quit"]:
                    print("Exiting chat...")
                    break
                
                # Check for clear command
                if user_input.lower() == "clear":
                    # Reset the conversation history
                    self.conversation_history = [{"role": "system", "content": self.system_prompt}]
                    print("Conversation history cleared")
                    continue
                    
                # Skip empty or whitespace-only inputs
                if not user_input.strip():
                    continue
                
                # Add the user message to history
                self.conversation_history.append({"role": "user", "content": user_input})
                
                try:
                    # Process the query with the full conversation history
                    response = await self.process_query(user_input, self.conversation_history)
                    
                    # Add the assistant's response to history
                    self.conversation_history.append({"role": "assistant", "content": response})
                    
                    # Log to Langfuse if enabled
                    if self.langfuse_enabled and self.langfuse:
                        try:
                            trace = self.langfuse.trace(
                                name="chat_session",
                                metadata={"model": self.model_name, "temperature": self.temperature},
                            )
                            trace.generation(
                                name="assistant_response",
                                model=self.model_name,
                                prompt=user_input,
                                completion=response,
                            )
                        except Exception as e:
                            logger.error(f"Langfuse logging error: {e}")
                        
                except Exception as e:
                    logger.error(f"Error processing query: {e}")
                    print(f"\nError: {e}")
                    import traceback
                    traceback.print_exc()
            
            print("\nChat session ended")
            
            # Save command history
            try:
                readline.write_history_file(history_file)
            except Exception as e:
                logger.error(f"Error saving command history: {e}")


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
@click.option(
    "--debug",
    is_flag=True,
    help="Enable debug logging",
)
def chat(config, tools, debug):
    """
    Start a chat session with the agent.

    Args:
        config: Path to configuration file
        tools: Path to tools configuration file
        debug: Enable debug logging
    """
    # Create configuration manager
    config_manager = ConfigManager(config_path=config, tools_path=tools)
    
    # Configure logging
    from ..cli import configure_logging
    configure_logging(config_manager, debug)
    
    # Create and run the chat
    chat_agent = SmartAgent(config_manager)
    asyncio.run(chat_agent.run_chat_loop())


if __name__ == "__main__":
    chat()