"""
CLI-specific SmartAgent implementation.

This module provides a CLI-specific implementation of the SmartAgent class
with features tailored for command-line interaction.
"""

import asyncio
import os
import readline
import sys
import logging
import json
from collections import deque
from typing import List, Dict, Any, Optional
from contextlib import AsyncExitStack

# Import agent components
from agents import Agent, OpenAIChatCompletionsModel, Runner, ItemHelpers
from agents.extensions.models.litellm_model import LitellmModel
from openai.types.responses import ResponseTextDeltaEvent

# Set up logging
logger = logging.getLogger(__name__)

# Rich imports for CLI formatting
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.text import Text

# Import base SmartAgent
from .agent import BaseSmartAgent

# Initialize console for rich output
console = Console()


class CLISmartAgent(BaseSmartAgent):
    """
    CLI-specific implementation of SmartAgent with features tailored for command-line interaction.
    """

    async def process_query(self, query: str, history: List[Dict[str, str]] = None, agent=None) -> str:
        """
        Process a query using the OpenAI agent with MCP tools, with CLI-specific output formatting.

        Args:
            query: The user's query
            history: Optional conversation history
            agent: The Agent instance to use for processing the query

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
        sys.stdout.reconfigure(line_buffering=True)
        
        # Create a buffer for tokens with type information
        buffer = deque()
        stream_ended = asyncio.Event()
        current_type = "assistant"  # Default type is assistant message
        
        # Define constants for consistent output
        output_interval = 0.05  # 50ms between outputs
        output_size = 12  # Output 6 characters at a time
        
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
        
        # Ensure we have an agent
        if agent is None:
            raise ValueError("Agent must be provided to process_query")
        
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
                # Process all events through the normal CLI processing path
                # Normal processing (only used when no custom handler is provided)
                if event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):                    
                    add_to_buffer(event.data.delta, "assistant")
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
                                # assistant_reply += f"\n<thought>{value}</thought>"
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
                                    # assistant_reply += f"\n<tool name=\"{key}\">\n```\n{code_str}\n```</tool>"
                                else:
                                    # Regular tool call
                                    tool_opening = f"\n<tool name=\"{key}\">"
                                    add_to_buffer(tool_opening, "tool")
                                    add_to_buffer(str(value), "tool")
                                    add_to_buffer("</tool>", "tool")
                                    
                                    # Update assistant reply
                                    # assistant_reply += f"\n<tool name=\"{key}\">{value}</tool>"
                        except (json.JSONDecodeError, StopIteration) as e:
                            # Add error to buffer with error type
                            error_text = f"Error parsing tool call: {e}"
                            add_to_buffer("\n<error>", "error")
                            add_to_buffer(error_text, "error")
                            add_to_buffer("</error>", "error")
                            
                            # Update assistant reply
                            # assistant_reply += f"\n<error>{error_text}</error>"
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
                                # assistant_reply += f"\n<tool_output>{output_text}</tool_output>"
                                
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
                                # assistant_reply += f"\n<tool_output>{event.item.output}</tool_output>"
                                
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
                            # add_to_buffer(text_message, "assistant")
                            assistant_reply += text_message
                        else:
                            # Add system message to buffer with system type
                            add_to_buffer(f"\n<{role}>", "system")
                            add_to_buffer(str(text_message), "system")
                            add_to_buffer(f"</{role}>", "system")
                            
                            # Update assistant reply
                            # assistant_reply += f"\n<{role}>{text_message}</{role}>"
            
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
        readline.parse_and_bind('"\x1b[A": previous-history')  # Up arrow
        readline.parse_and_bind('"\x1b[B": next-history')      # Down arrow
        
        # Initialize conversation history with system prompt
        self.conversation_history = [{"role": "system", "content": self.system_prompt}]
        
        # Set up MCP servers
        self.mcp_servers = self.setup_mcp_servers()
        
        # Chat loop
        async with AsyncExitStack() as exit_stack:
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
                    # Set up MCP servers for this query
                    mcp_servers = []
                    for server in self.mcp_servers:
                        # Create a fresh connection for each server
                        connected_server = await exit_stack.enter_async_context(server)
                        mcp_servers.append(connected_server)
                        logger.debug(f"Connected to MCP server: {connected_server.name}")
                    
                    # Create a fresh agent for each query
                    agent = Agent(
                        name="Assistant",
                        # instructions=self.system_prompt,
                        # model=LitellmModel(
                        #     model=self.model_name,
                        #     base_url=self.base_url,
                        #     api_key=self.api_key,
                        # ),
                        model=OpenAIChatCompletionsModel(
                            model=self.model_name,
                            openai_client=self.openai_client,
                        ),
                        mcp_servers=mcp_servers,
                    )
                    # print(agent.model_settings.to_json_dict(), flush=True)
                    # agent.model_settings.max_tokens = 10000
                    # print(self.conversation_history, flush=True)
                    # Process the query with the full conversation history and fresh agent
                    response = await self.process_query(user_input, self.conversation_history, agent=agent)
                    
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