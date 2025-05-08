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
from openai.types.responses import ResponseTextDeltaEvent

# Set up logging
logger = logging.getLogger(__name__)

# Rich imports for CLI formatting
from rich.console import Console

# Import base SmartAgent
from .agent import BaseSmartAgent

# Initialize console for rich output
console = Console()


class CLISmartAgent(BaseSmartAgent):
    """
    CLI-specific implementation of SmartAgent with features tailored for command-line interaction.
    """
    
    def __init__(self, config_manager, session_id=None):
        """
        Initialize the CLI Smart Agent.
        
        Args:
            config_manager: Configuration manager instance
            session_id: Unique identifier for this chat session
        """
        super().__init__(config_manager, session_id=session_id)

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
        
        # Define constants for consistent output
        output_interval = 0.05  # 50ms between outputs
        output_size = 12  # Output characters at a time
        
        # Define colors for different content types
        type_colors = {
            "assistant": "green",
            "thought": "cyan",
            "tool_output": "bright_green",
            "tool": "yellow",
            "error": "red"
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
            current_batch_type = "assistant"
            try:
                while not end_event.is_set() or buffer:  # Continue until signaled and buffer is empty
                    if buffer:
                        # Get a batch of tokens from the buffer
                        batch = []
                        
                        for _ in range(min(size, len(buffer))):
                            if not buffer:
                                break
                                
                            item = buffer.popleft()
                            
                            # Handle type change marker
                            if item[0] == "TYPE_CHANGE":
                                if batch:  # Print current batch before changing type
                                    rich_console.print(''.join(batch), end="", style=type_colors.get(current_batch_type, "green"))
                                    batch = []
                                current_batch_type = item[1]
                                continue
                            
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
            
            # Process the stream events
            async for event in result.stream_events():
                # Handle token streaming
                if event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):
                    add_to_buffer(event.data.delta, "assistant")
                    continue
                elif event.type == "agent_updated_stream_event":
                    continue
                elif event.type == "run_item_stream_event":
                    # Handle tool calls
                    if event.item.type == "tool_call_item":
                        try:
                            arguments_dict = json.loads(event.item.raw_item.arguments)
                            key, value = next(iter(arguments_dict.items()))
                            if key == "thought":
                                is_thought = True
                                add_to_buffer("\n<thought>\n", "thought")
                                add_to_buffer(str(value), "thought")
                                add_to_buffer("\n</thought>", "thought")
                            else:
                                is_thought = False
                                add_to_buffer("\n<tool>\n", "tool")
                                for arg_key, arg_value in arguments_dict.items():
                                    add_to_buffer(f"{arg_key}={str(arg_value)}\n", "tool")
                                add_to_buffer("</tool>", "tool")
                        except Exception as e:
                            error_text = f"Error parsing tool call: {e}"
                            add_to_buffer(f"\n<error>{error_text}</error>", "error")
                    
                    # Handle tool outputs
                    elif event.item.type == "tool_call_output_item" and not is_thought:
                        try:
                            try:
                                output_json = json.loads(event.item.output)
                                output_text = output_json.get("text", json.dumps(output_json, indent=2))
                            except json.JSONDecodeError:
                                output_text = event.item.output
                            
                            # Pause token streaming
                            stream_ended.set()
                            await streaming_task
                            
                            # Print tool output all at once
                            rich_console.print("\n<tool_output>\n", end="", style="bright_green bold")
                            rich_console.print(str(output_text), style="bright_green", end="")
                            rich_console.print("\n</tool_output>", style="bright_green bold")
                            
                            # Ensure output is flushed immediately
                            sys.stdout.flush()
                            
                            # Reset for continued streaming
                            stream_ended.clear()
                            streaming_task = asyncio.create_task(
                                stream_output(buffer, output_interval, output_size, stream_ended)
                            )
                        except Exception as e:
                            add_to_buffer(f"\n<error>Error processing tool output: {e}</error>", "error")
                    
                    # Handle final message
                    elif event.item.type == "message_output_item" and event.item.raw_item.role == "assistant":
                        assistant_reply += ItemHelpers.text_message_output(event.item)
            
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
                except Exception:
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
        print(f"Session ID: {self.session_id}")
        print("Type 'exit' or 'quit' to end the conversation")
        print("Type 'clear' to clear the conversation history")
        print(f"To continue this session later, use: smart-agent chat --session-id {self.session_id}")

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
        # self.mcp_servers = self.setup_mcp_servers()
        
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
            
            print("\nChat session ended")
            
            # Save command history
            try:
                readline.write_history_file(history_file)
            except Exception as e:
                logger.error(f"Error saving command history: {e}")