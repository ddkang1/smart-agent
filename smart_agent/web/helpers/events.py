"""Helper functions for processing agent events."""

import json
import logging
import chainlit as cl

logger = logging.getLogger(__name__)

async def process_agent_event(event, agent_steps, is_thought, assistant_reply):
    """Process a single event from the agent's stream.
    
    Args:
        event: The event to process
        agent_steps: The Chainlit step object for streaming tokens
        is_thought: Whether the current event is a thought
        assistant_reply: The accumulated assistant reply
        
    Returns:
        tuple: (is_thought, assistant_reply) - Updated values
    """
    from agents import ItemHelpers
    
    if event.type == "raw_response_event" or event.type == "agent_updated_stream_event":
        # Skip these event types
        return is_thought, assistant_reply
        
    if event.type != "run_item_stream_event":
        # Unknown event type
        return is_thought, assistant_reply
    
    # Process run_item_stream_event
    if event.item.type == "tool_call_item":
        try:
            arguments_dict = json.loads(event.item.raw_item.arguments)
            key, value = next(iter(arguments_dict.items()))

            if key == "thought":
                is_thought = True
                await agent_steps.stream_token(f"### 🤔 Thinking\n```\n{value}\n```\n\n")
                assistant_reply += "\n[thought]: " + value
            else:
                is_thought = False
                await agent_steps.stream_token(f"### 🔧 Using Tool: {key}\n```\n{value}\n```\n\n")
        except (json.JSONDecodeError, StopIteration) as e:
            await agent_steps.stream_token(f"Error parsing tool call: {e}\n\n")

    elif event.item.type == "tool_call_output_item":
        if not is_thought:
            try:
                parsed_output = json.loads(event.item.output)
                # Handle both dictionary and list outputs
                if isinstance(parsed_output, dict):
                    output_text = parsed_output.get("text", "")
                elif isinstance(parsed_output, list):
                    # For list outputs, join the elements if they're strings
                    if all(isinstance(item, str) for item in parsed_output):
                        output_text = "\n".join(parsed_output)
                    else:
                        # Otherwise, convert the list to a formatted string
                        output_text = json.dumps(parsed_output, indent=2)
                else:
                    # For any other type, convert to string
                    output_text = str(parsed_output)

                await agent_steps.stream_token(f"### 💾 Tool Result\n```\n{output_text}\n```\n\n")
            except (json.JSONDecodeError, AttributeError) as e:
                logger.debug(f"Error parsing tool output: {e}. Using raw output.")
                await agent_steps.stream_token(f"### 💾 Tool Result\n```\n{event.item.output}\n```\n\n")

    elif event.item.type == "message_output_item":
        role = event.item.raw_item.role
        text_message = ItemHelpers.text_message_output(event.item)

        if role == "assistant":
            assistant_reply += "\n[response]: " + text_message
            await cl.Message(content=text_message, author="Smart Agent").send()
        else:
            await agent_steps.stream_token(f"**{role.capitalize()}**: {text_message}\n\n")
    
    return is_thought, assistant_reply


async def extract_response_from_assistant_reply(assistant_reply):
    """Extract the response part from the assistant's reply.
    
    Args:
        assistant_reply: The full assistant reply including thoughts and responses
        
    Returns:
        str: The extracted response
    """
    response = ""
    for line in assistant_reply.split("\n"):
        if line.startswith("[response]:"):
            response += line[len("[response]:"):].strip() + "\n"

    if not response.strip():
        response = assistant_reply.strip()
        
    return response
