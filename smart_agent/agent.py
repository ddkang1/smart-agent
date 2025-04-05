"""
Core agent functionality for Smart Agent.
"""

import json
import datetime
import locale
import logging
from typing import List, Dict, Any, Optional

# Set up logging
logger = logging.getLogger(__name__)

from agents import (
    Agent,
    OpenAIChatCompletionsModel,
    Runner,
    ItemHelpers,
)
from agents.mcp import MCPServerSse
from openai import AsyncOpenAI


class PromptGenerator:
    """Generates dynamic system prompts with current date and time."""

    @staticmethod
    def create_system_prompt(custom_instructions: str = None) -> str:
        """Generate a system prompt with current date and time.

        Args:
            custom_instructions: Optional custom instructions to include

        Returns:
            A formatted system prompt
        """
        # Get current date and time in the local format
        current_datetime = datetime.datetime.now().strftime(
            locale.nl_langinfo(locale.D_T_FMT)
            if hasattr(locale, "nl_langinfo")
            else "%c"
        )

        # Base system prompt
        base_prompt = f"""## Guidelines for Using the Think Tool
The think tool is designed to help you "take a break and think"—a deliberate pause for reflection—both before initiating any action (like calling a tool) and after processing any new evidence. Use it as your internal scratchpad for careful analysis, ensuring that each step logically informs the next. Follow these steps:

0. Assumption
   - Current date and time is {current_datetime}

1. **Pre-Action Pause ("Take a Break and Think"):**
   - Before initiating any external action or calling a tool, pause to use the think tool.

2. **Post-Evidence Reflection:**
   - After receiving results or evidence from any tool, take another break using the think tool.
   - Reassess the new information by:
     - Reiterating the relevant rules, guidelines, and policies.
     - Examining the consistency, correctness, and relevance of the tool results.
     - Reflecting on any insights that may influence the final answer.
   - Incorporate updated or new information ensuring that it fits logically with your earlier conclusions.
   - **Maintain Logical Flow:** Connect the new evidence back to your original reasoning, ensuring that this reflection fills in any gaps or uncertainties in your reasoning.

3. **Iterative Review and Verification:**
   - Verify that you have gathered all necessary information.
   - Use the think tool to repeatedly validate your reasoning.
   - Revisit each step of your thought process, ensuring that no essential details have been overlooked.
   - Check that the insights gained in each phase flow logically into the next—confirm there are no abrupt jumps or inconsistencies in your reasoning.

4. **Proceed to Final Action:**
   - Only after these reflective checks should you proceed with your final answer.
   - Synthesize the insights from all prior steps to form a comprehensive, coherent, and logically connected final response.

## Guidelines for the final answer
For each part of your answer, indicate which sources most support it via valid citation markers with the markdown hyperlink to the source at the end of sentences, like ([Source](URL)).
"""

        # Combine with custom instructions if provided
        if custom_instructions:
            return f"{base_prompt}\n\n{custom_instructions}"

        return base_prompt


class SmartAgent:
    """
    Smart Agent with reasoning and tool use capabilities.
    """

    def __init__(
        self,
        model_name: str = None,
        openai_client: AsyncOpenAI = None,
        mcp_servers: List[Any] = None,
        system_prompt: Optional[str] = None,
        custom_instructions: Optional[str] = None,
    ):
        """
        Initialize a new Smart Agent.

        Args:
            model_name: The name of the model to use
            openai_client: An initialized OpenAI client
            mcp_servers: A list of MCP servers to use
            system_prompt: Optional system prompt to use (overrides the default)
            custom_instructions: Optional custom instructions to append to the default system prompt
        """
        self.model_name = model_name
        self.openai_client = openai_client
        self.mcp_servers = mcp_servers or []
        self.custom_instructions = custom_instructions

        # Use provided system prompt or generate a dynamic one
        if system_prompt:
            self.system_prompt = system_prompt
        else:
            self.system_prompt = PromptGenerator.create_system_prompt(custom_instructions)

        self.agent = None

        if self.mcp_servers and self.openai_client:
            self._initialize_agent()

    def _initialize_agent(self):
        """Initialize the agent with the provided configuration."""
        # Convert URL strings to MCPServerSse objects if needed
        mcp_server_objects = []
        for server in self.mcp_servers:
            if isinstance(server, str):
                # It's a URL string, convert to MCPServerSse
                # Parse the URL to extract tool information
                tool_name = server.split('/')[-2] if '/' in server else 'tool'
                mcp_server_objects.append(MCPServerSse(
                    name=tool_name,  # Add a name for better identification
                    params={"url": server}
                ))
            else:
                # It's already an MCP server object
                mcp_server_objects.append(server)

        self.agent = Agent(
            name="Assistant",
            instructions=self.system_prompt,
            model=OpenAIChatCompletionsModel(
                model=self.model_name,
                openai_client=self.openai_client,
            ),
            mcp_servers=[],#mcp_server_objects
        )

    async def process_message(
        self, history: List[Dict[str, str]], max_turns: int = 100, update_system_prompt: bool = True
    ):
        """
        Process a message with the agent.

        Args:
            history: A list of message dictionaries with 'role' and 'content' keys
            max_turns: Maximum number of turns for the agent
            update_system_prompt: Whether to update the system prompt with current date/time

        Returns:
            The agent's response
        """
        if not self.agent:
            raise ValueError(
                "Agent not initialized. Make sure to provide openai_client and mcp_servers."
            )

        # Update the system prompt with current date/time if requested
        if update_system_prompt and history and history[0].get("role") == "system":
            logger.debug("Updating system prompt with current date/time")
            history[0]["content"] = PromptGenerator.create_system_prompt(self.custom_instructions)

        # Use async context managers for MCP servers when possible
        # This ensures proper cleanup even if an exception occurs
        connected_servers = []

        try:
            # Connect to all MCP servers
            logger.debug(f"Connecting to {len(self.agent.mcp_servers)} MCP servers")
            for i, server in enumerate(self.agent.mcp_servers):
                server_name = getattr(server, 'name', f"server_{i}")
                logger.debug(f"Connecting to MCP server {server_name}")
                if hasattr(server, 'connect') and callable(server.connect):
                    try:
                        await server.connect()
                        connected_servers.append(server)
                        logger.debug(f"Successfully connected to MCP server {server_name}")
                    except Exception as e:
                        logger.error(f"Failed to connect to MCP server {server_name}: {e}")
                        raise

            # Run the agent with the conversation history
            result = Runner.run_streamed(self.agent, history, max_turns=max_turns)
            return result
        except Exception as e:
            # Clean up MCP servers on error
            logger.debug(f"Cleaning up {len(connected_servers)} MCP servers due to error")
            for server in connected_servers:
                server_name = getattr(server, 'name', 'unknown')
                logger.debug(f"Cleaning up MCP server {server_name}")
                if hasattr(server, 'cleanup') and callable(server.cleanup):
                    try:
                        server.cleanup()
                        logger.debug(f"Successfully cleaned up MCP server {server_name}")
                    except Exception as cleanup_error:
                        logger.error(f"Error cleaning up MCP server {server_name}: {cleanup_error}")
            raise e

    @staticmethod
    async def process_stream_events(result, callback=None, agent=None, verbose=False):
        """
        Process stream events from the agent.

        Args:
            result: The result from process_message
            callback: Optional callback function to handle events
            agent: Optional agent instance for cleanup
            verbose: Whether to include detailed tool outputs in the reply

        Returns:
            The assistant's reply
        """
        assistant_reply = ""
        current_tool = None  # Track the current tool being used

        try:
            async for event in result.stream_events():
                if event.type == "raw_response_event":
                    continue
                elif event.type == "agent_updated_stream_event":
                    continue
                elif event.type == "run_item_stream_event":
                    if event.item.type == "tool_call_item":
                        arguments_dict = json.loads(event.item.raw_item.arguments)
                        key, value = next(iter(arguments_dict.items()))

                        # Store the current tool being used
                        current_tool = key

                        if key == "thought":
                            # Add thought to the assistant reply
                            if verbose:
                                assistant_reply += f"\n[thought]: {value}"
                        else:
                            # Add tool call to the assistant reply if verbose
                            if verbose:
                                assistant_reply += f"\n[tool]: {key}\n{value}"

                    elif event.item.type == "tool_call_output_item":
                        # Process tool output
                        try:
                            # Try to parse the output as JSON
                            output_data = json.loads(event.item.output)
                            output_text = output_data.get("text", event.item.output)

                            # Log the tool output
                            logger.debug(f"Tool output: {output_text}")

                            # Add tool output to the assistant reply if verbose
                            if verbose and current_tool:
                                assistant_reply += f"\n[tool output]: {output_text}"
                        except json.JSONDecodeError:
                            # If not JSON, use the raw output
                            if verbose:
                                assistant_reply += f"\n[tool output]: {event.item.output}"

                    elif event.item.type == "message_output_item":
                        role = event.item.raw_item.role
                        text_message = ItemHelpers.text_message_output(event.item)
                        if role == "assistant":
                            assistant_reply += f"\n[response]: {text_message}"

                    # Call the callback if provided
                    if callback:
                        await callback(event)
        finally:
            # Clean up MCP servers if agent is provided
            if agent and hasattr(agent, 'mcp_servers'):
                logger.debug(f"Cleaning up {len(agent.mcp_servers)} MCP servers in process_stream_events")
                for i, server in enumerate(agent.mcp_servers):
                    server_name = getattr(server, 'name', f"server_{i}")
                    logger.debug(f"Cleaning up MCP server {server_name}")
                    if hasattr(server, 'cleanup') and callable(server.cleanup):
                        try:
                            server.cleanup()
                            logger.debug(f"Successfully cleaned up MCP server {server_name}")
                        except Exception as cleanup_error:
                            logger.error(f"Error cleaning up MCP server {server_name}: {cleanup_error}")

        return assistant_reply.strip()
