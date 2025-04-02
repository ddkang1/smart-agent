"""
Core agent functionality for Smart Agent.
"""

import os
import json
from typing import List, Dict, Any, Optional

from agents import (
    Agent,
    OpenAIChatCompletionsModel,
    Runner,
    ItemHelpers,
)


class SmartAgent:
    """
    Smart Agent with reasoning and tool use capabilities.
    """

    def __init__(
        self,
        model_name: str = None,
        openai_client: Any = None,
        mcp_servers: List[Any] = None,
        system_prompt: Optional[str] = None,
    ):
        """
        Initialize a new Smart Agent.

        Args:
            model_name: The name of the model to use
            openai_client: An initialized OpenAI client
            mcp_servers: A list of MCP servers to use
            system_prompt: Optional system prompt to use
        """
        self.model_name = model_name
        self.openai_client = openai_client
        self.mcp_servers = mcp_servers or []
        self.system_prompt = system_prompt
        self.agent = None

        if self.mcp_servers and self.openai_client:
            self._initialize_agent()

    def _initialize_agent(self):
        """Initialize the agent with the provided configuration."""
        self.agent = Agent(
            name="Assistant",
            instructions=self.system_prompt,
            model=OpenAIChatCompletionsModel(
                model=self.model_name,
                openai_client=self.openai_client,
            ),
            mcp_servers=self.mcp_servers,
        )

    async def process_message(
        self, history: List[Dict[str, str]], max_turns: int = 100
    ):
        """
        Process a message with the agent.

        Args:
            history: A list of message dictionaries with 'role' and 'content' keys
            max_turns: Maximum number of turns for the agent

        Returns:
            The agent's response
        """
        if not self.agent:
            raise ValueError(
                "Agent not initialized. Make sure to provide openai_client and mcp_servers."
            )

        result = Runner.run_streamed(self.agent, history, max_turns=max_turns)
        return result

    @staticmethod
    async def process_stream_events(result, callback=None):
        """
        Process stream events from the agent.

        Args:
            result: The result from process_message
            callback: Optional callback function to handle events

        Returns:
            The assistant's reply
        """
        assistant_reply = ""
        is_thought = False

        async for event in result.stream_events():
            if event.type == "raw_response_event":
                continue
            elif event.type == "agent_updated_stream_event":
                continue
            elif event.type == "run_item_stream_event":
                if event.item.type == "tool_call_item":
                    arguments_dict = json.loads(event.item.raw_item.arguments)
                    key, value = next(iter(arguments_dict.items()))
                    if key == "thought":
                        is_thought = True
                        assistant_reply += "\n[thought]: " + value
                    else:
                        is_thought = False
                elif event.item.type == "tool_call_output_item":
                    pass  # Handle tool output if needed
                elif event.item.type == "message_output_item":
                    role = event.item.raw_item.role
                    text_message = ItemHelpers.text_message_output(event.item)
                    if role == "assistant":
                        assistant_reply += "\n[response]: " + text_message

                # Call the callback if provided
                if callback:
                    await callback(event)

        return assistant_reply.strip()
