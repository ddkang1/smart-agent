"""
Core agent functionality for Smart Agent.
"""

import json
import datetime
import locale
import logging
import contextlib
from typing import List, Dict, Any, Optional, Callable
from contextlib import AsyncExitStack

# Set up logging
logger = logging.getLogger(__name__)

# Configure logging for various libraries to suppress specific error messages
openai_agents_logger = logging.getLogger('openai.agents')
asyncio_logger = logging.getLogger('asyncio')
httpx_logger = logging.getLogger('httpx')
httpcore_logger = logging.getLogger('httpcore')
mcp_client_sse_logger = logging.getLogger('mcp.client.sse')

# Set log levels to reduce verbosity
httpx_logger.setLevel(logging.WARNING)
mcp_client_sse_logger.setLevel(logging.WARNING)
# Set openai.agents logger to CRITICAL to suppress ERROR messages
openai_agents_logger.setLevel(logging.CRITICAL)

# Create a filter to suppress specific error messages
# class SuppressSpecificErrorFilter(logging.Filter):
#     """Filter to suppress specific error messages in logs.

#     This filter checks log messages against a list of patterns and
#     filters out any messages that match, preventing them from being
#     displayed to the user.
#     """
#     def filter(self, record) -> bool:
#         # Get the message from the record
#         message = record.getMessage()

#         # List of error patterns to suppress
#         suppress_patterns = [
#             'Error cleaning up server: Attempted to exit a cancel scope',
#             'Event loop is closed',
#             'Task exception was never retrieved',
#             'AsyncClient.aclose',
#         ]

#         # Check if any of the patterns are in the message
#         for pattern in suppress_patterns:
#             if pattern in message:
#                 return False  # Filter out this message

#         return True  # Keep this message

# # Add the filter to various loggers
# openai_agents_logger.addFilter(SuppressSpecificErrorFilter())
# asyncio_logger.addFilter(SuppressSpecificErrorFilter())
# httpx_logger.addFilter(SuppressSpecificErrorFilter())
# httpcore_logger.addFilter(SuppressSpecificErrorFilter())

# OpenAI and Agent imports
from openai import AsyncOpenAI
from agents import (
    Agent,
    OpenAIChatCompletionsModel,
    Runner,
    ItemHelpers,
)
from agents.mcp import MCPServerSse


class PromptGenerator:
    """Generates dynamic system prompts with current date and time.

    This class provides static methods for creating system prompts with
    current date and time information, and optionally including custom
    instructions provided by the user.
    """

    @staticmethod
    def create_system_prompt(custom_instructions: Optional[str] = None) -> str:
        """Generate a system prompt with current date and time.

        This method generates a system prompt that includes the current date and time,
        formatted according to the user's locale settings if possible. It provides
        guidelines for the assistant's behavior and can include custom instructions
        if provided.

        Args:
            custom_instructions: Optional custom instructions to include

        Returns:
            A formatted system prompt
        """
        # Get current date and time with proper locale handling
        current_datetime = PromptGenerator._get_formatted_datetime()

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

    @staticmethod
    def _get_formatted_datetime() -> str:
        """Get the current date and time formatted according to locale settings.

        This helper method attempts to format the current date and time using
        the user's locale settings. If that fails, it falls back to a simple
        format.

        Returns:
            A string containing the formatted current date and time
        """
        try:
            # Try to use the system's locale settings
            return datetime.datetime.now().strftime(
                locale.nl_langinfo(locale.D_T_FMT)
                if hasattr(locale, "nl_langinfo")
                else "%c"
            )
        except Exception as e:
            # Log the error but don't let it affect the user experience
            logger.debug(f"Error formatting datetime: {e}")
            # Fall back to a simple format if locale settings cause issues
            return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


class SmartAgent:
    """
    Smart Agent with reasoning and tool use capabilities.

    This class provides a high-level interface for interacting with the OpenAI Agent framework,
    handling the initialization, connection, and cleanup of MCP servers, and processing
    messages with proper error handling and resource management.

    Attributes:
        model_name (str): The name of the model to use
        openai_client (AsyncOpenAI): The OpenAI client for API calls
        mcp_servers (List): List of MCP servers or URLs
        system_prompt (str): The system prompt to use
        custom_instructions (Optional[str]): Custom instructions to append to the system prompt
        agent (Agent): The underlying Agent instance
        exit_stack (AsyncExitStack): Stack for managing async context managers
        connected_servers (List): List of successfully connected MCP servers
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        openai_client: Optional[AsyncOpenAI] = None,
        mcp_servers: Optional[List[Any]] = None,
        system_prompt: Optional[str] = None,
        custom_instructions: Optional[str] = None,
    ) -> None:
        """
        Initialize a new Smart Agent.

        Args:
            model_name: The name of the model to use (e.g., "gpt-4o")
            openai_client: An initialized AsyncOpenAI client
            mcp_servers: A list of MCP servers or URLs to use for tools
            system_prompt: Optional system prompt to use (overrides the default)
            custom_instructions: Optional custom instructions to append to the default system prompt

        Note:
            If openai_client is provided, the agent will be initialized immediately.
            Otherwise, you'll need to set the client later and call _initialize_agent() manually.
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

        # Initialize instance variables
        self.agent = None
        self.exit_stack = AsyncExitStack()
        self.connected_servers = []

        # Initialize the agent if we have the required components
        if self.openai_client:
            self._initialize_agent()

    def _initialize_agent(self) -> None:
        """Initialize the agent with the provided configuration.

        This method converts URL strings to MCPServerSse objects if needed,
        and creates the Agent instance with the appropriate configuration.

        Returns:
            None
        """
        # Convert URL strings to MCPServerSse objects if needed
        mcp_server_objects = []

        for server in self.mcp_servers:
            if isinstance(server, str):
                # Extract tool name from URL for better identification
                tool_name = self._extract_tool_name_from_url(server)

                # Create MCPServerSse object from URL string
                mcp_server_objects.append(MCPServerSse(
                    name=tool_name,
                    params={"url": server}
                ))
            else:
                # It's already an MCP server object
                mcp_server_objects.append(server)

        # Create the agent with the MCP servers
        self.agent = Agent(
            name="Assistant",
            instructions=self.system_prompt,
            model=OpenAIChatCompletionsModel(
                model=self.model_name,
                openai_client=self.openai_client,
            ),
            mcp_servers=mcp_server_objects,
        )

    def _extract_tool_name_from_url(self, url: str) -> str:
        """Extract a tool name from a URL string.

        Args:
            url: The URL string to extract the tool name from

        Returns:
            A string containing the extracted tool name
        """
        try:
            # Try to extract the tool name from the URL path
            if '/' in url:
                # Get the second-to-last path component as the tool name
                path_parts = url.rstrip('/').split('/')
                if len(path_parts) >= 2:
                    return path_parts[-2]

            # If we can't extract a meaningful name, use a generic one
            return 'tool'
        except Exception:
            # Fall back to a generic name if anything goes wrong
            return 'tool'

    async def process_message(
        self,
        history: List[Dict[str, str]],
        max_turns: int = 100,
        update_system_prompt: bool = True
    ) -> Any:
        """
        Process a message with the agent.

        This method handles the entire lifecycle of processing a message:
        1. Initializes and updates the system prompt if needed
        2. Connects to all MCP servers using an AsyncExitStack for proper resource management
        3. Runs the agent with the conversation history
        4. Ensures proper cleanup of resources even if exceptions occur

        Args:
            history: A list of message dictionaries with 'role' and 'content' keys
            max_turns: Maximum number of turns for the agent
            update_system_prompt: Whether to update the system prompt with current date/time

        Returns:
            The agent's response stream or an error message string
        """
        # Check if agent is properly initialized
        if not self.agent:
            logger.error("Agent not initialized. Check configuration.")
            raise ValueError("Agent not initialized. Please check your configuration.")

        # Update the system prompt with current date/time if requested
        if update_system_prompt and history and history[0].get("role") == "system":
            logger.debug("Updating system prompt with current date/time")
            history[0]["content"] = PromptGenerator.create_system_prompt(self.custom_instructions)

        # Reset the exit stack and connected servers for this message
        self.exit_stack = AsyncExitStack()
        self.connected_servers = []

        try:
            # Connect to all MCP servers using the exit stack for proper cleanup
            server_count = len(self.agent.mcp_servers)
            logger.debug(f"Connecting to {server_count} MCP servers")

            # Connect to each server
            await self._connect_to_mcp_servers()

            # If no servers connected successfully but servers were provided, log a warning
            if not self.connected_servers and server_count > 0:
                logger.warning("No MCP servers connected successfully. Some functionality may be limited.")

            # Run the agent with the conversation history
            result = Runner.run_streamed(self.agent, history, max_turns=max_turns)
            return result

        except Exception as e:
            # Log the error and return a user-friendly message
            logger.error(f"Error processing message: {e}")
            return f"I'm sorry, I encountered an error: {str(e)}. Please try again later."

        finally:
            # Use the exit stack to ensure proper cleanup of all resources
            # This will automatically call cleanup on all connected servers
            with contextlib.suppress(Exception):
                await self.exit_stack.aclose()
                logger.debug("Successfully closed all MCP server connections")

    async def _connect_to_mcp_servers(self) -> None:
        """Connect to all MCP servers in the agent.

        This helper method attempts to connect to each MCP server,
        handling errors gracefully to ensure that as many servers
        as possible are connected.

        Returns:
            None
        """
        for i, server in enumerate(self.agent.mcp_servers):
            # Get server name for logging
            server_name = getattr(server, 'name', f"server_{i}")
            logger.debug(f"Connecting to MCP server {server_name}")

            # Skip servers that don't have a connect method
            if not hasattr(server, 'connect') or not callable(server.connect):
                logger.warning(f"MCP server {server_name} does not have a connect method, skipping")
                continue

            try:
                # Use the exit stack to ensure proper cleanup
                await self.exit_stack.enter_async_context(server)
                self.connected_servers.append(server)
                logger.debug(f"Successfully connected to MCP server {server_name}")

            except Exception as e:
                # Log the error but continue with other servers
                logger.error(f"Failed to connect to MCP server {server_name}: {e}")

                # Suppress the exception to continue with other servers
                with contextlib.suppress(Exception):
                    if hasattr(server, 'cleanup') and callable(server.cleanup):
                        await server.cleanup()
                continue

    @staticmethod
    async def process_stream_events(result: Any, callback: Optional[callable] = None, verbose: bool = False) -> str:
        """
        Process stream events from the agent.

        This method processes the stream of events from the agent, extracting relevant
        information and formatting it into a coherent reply. It handles different types
        of events including tool calls, tool outputs, and assistant messages.

        Args:
            result: The result stream from process_message
            callback: Optional callback function to handle events
            verbose: Whether to include detailed tool outputs in the reply

        Returns:
            The formatted assistant's reply as a string
        """
        assistant_reply = ""
        current_tool = None  # Track the current tool being used

        try:
            async for event in result.stream_events():
                # Skip events that don't contain useful content for the reply
                if event.type in ("raw_response_event", "agent_updated_stream_event"):
                    continue

                # Process run item stream events (tool calls, outputs, messages)
                elif event.type == "run_item_stream_event":
                    assistant_reply = await SmartAgent._process_run_item_event(
                        event,
                        assistant_reply,
                        current_tool,
                        verbose,
                        callback
                    )

                    # Update current tool if this was a tool call
                    if event.item.type == "tool_call_item":
                        try:
                            arguments_dict = json.loads(event.item.raw_item.arguments)
                            current_tool = next(iter(arguments_dict.items()))[0]
                        except (json.JSONDecodeError, StopIteration):
                            # If we can't parse the arguments, don't update the current tool
                            pass
        except Exception as e:
            # Log any errors that occur during event processing
            logger.error(f"Error processing stream events: {e}")
            # Add error information to the reply if it's empty
            if not assistant_reply:
                assistant_reply = f"\n[error]: Error processing response: {str(e)}"
        finally:
            # Clean up is now handled by the exit stack in the agent's process_message method
            # We don't need to manually clean up here anymore
            pass

        return assistant_reply.strip()

    @staticmethod
    async def _process_run_item_event(event: Any, assistant_reply: str, current_tool: Optional[str],
                                     verbose: bool, callback: Optional[callable]) -> str:
        """
        Process a run item stream event and update the assistant reply.

        Args:
            event: The event to process
            assistant_reply: The current assistant reply
            current_tool: The current tool being used
            verbose: Whether to include detailed outputs
            callback: Optional callback function

        Returns:
            The updated assistant reply
        """
        # Handle tool call events
        if event.item.type == "tool_call_item":
            try:
                arguments_dict = json.loads(event.item.raw_item.arguments)
                key, value = next(iter(arguments_dict.items()))

                # Add appropriate content based on the tool type
                if key == "thought" and verbose:
                    assistant_reply += f"\n[thought]: {value}"
                elif verbose:
                    assistant_reply += f"\n[tool]: {key}\n{value}"
            except (json.JSONDecodeError, StopIteration) as e:
                logger.warning(f"Could not parse tool call arguments: {e}")

        # Handle tool output events
        elif event.item.type == "tool_call_output_item":
            assistant_reply = SmartAgent._process_tool_output(
                event, assistant_reply, current_tool, verbose)

        # Handle message output events
        elif event.item.type == "message_output_item":
            try:
                role = event.item.raw_item.role
                text_message = ItemHelpers.text_message_output(event.item)
                if role == "assistant":
                    assistant_reply += f"\n[response]: {text_message}"
            except Exception as e:
                logger.warning(f"Error processing message output: {e}")

        # Call the callback if provided
        if callback:
            try:
                await callback(event)
            except Exception as e:
                logger.warning(f"Error in callback: {e}")

        return assistant_reply

    @staticmethod
    def _process_tool_output(event: Any, assistant_reply: str, current_tool: Optional[str], verbose: bool) -> str:
        """
        Process a tool output event and update the assistant reply.

        Args:
            event: The tool output event
            assistant_reply: The current assistant reply
            current_tool: The current tool being used
            verbose: Whether to include detailed outputs

        Returns:
            The updated assistant reply
        """
        if not verbose:
            return assistant_reply

        try:
            # Try to parse the output as JSON
            output_data = json.loads(event.item.output)
            output_text = output_data.get("text", event.item.output)

            # Log the tool output
            logger.debug(f"Tool output: {output_text}")

            # Add tool output to the assistant reply if verbose and we have a current tool
            if current_tool:
                assistant_reply += f"\n[tool output]: {output_text}"
        except json.JSONDecodeError:
            # If not JSON, use the raw output
            assistant_reply += f"\n[tool output]: {event.item.output}"
        except Exception as e:
            logger.warning(f"Error processing tool output: {e}")

        return assistant_reply
