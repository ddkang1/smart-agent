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

