import json, logging, chainlit as cl
from agents import ItemHelpers

log = logging.getLogger(__name__)

async def handle_event(event, state):
    """
    state = {
        "assistant_msg": cl.Message  # the one long-lived streamed message
    }
    """
    try:
        # ── token delta from the LLM ────────────────────────────────────────────
        if event.type == "raw_response_event":
            delta = getattr(event.data, "delta", None)
            token = getattr(delta, "content", None)
            if token:
                await state["assistant_msg"].stream_token(token)
            return

        if event.type != "run_item_stream_event":
            return

        item = event.item

        # ── model called the special 'thought' function tool ───────────────────
        if item.type == "tool_call_item":
            try:
                arg = json.loads(item.raw_item.arguments)
                key, value = next(iter(arg.items()))
                
                # Log the tool call for debugging
                log.debug(f"Tool call: {key} with value: {value}")
                
                if key == "thought":
                    # Keep thoughts hidden in the UI but available in the message content
                    # This creates a seamless experience while preserving the thought process
                    pass
                else:
                    # Don't show tool calls in the UI to maintain the seamless experience
                    # But log them for debugging purposes
                    log.info(f"Tool called: {key}")
            except Exception as e:
                log.error(f"Error processing tool call: {e}")
                return

        # ── tool result ────────────────────────────────────────────────────────
        elif item.type == "tool_call_output_item":
            try:
                # Log the raw tool output for debugging
                log.debug(f"Tool output: {item.output}")
                
                # Try to parse as JSON for better handling
                output_json = json.loads(item.output)
                
                # If it's a text response, integrate it seamlessly
                if isinstance(output_json, dict) and "text" in output_json:
                    # Extract just the text content for a seamless experience
                    await state["assistant_msg"].stream_token(f"\n\n{output_json['text']}\n\n")
                    log.info(f"Integrated text output: {output_json['text'][:50]}...")
                else:
                    # For other types of results, log them but don't display directly
                    # They will be processed by the model and incorporated into its response
                    log.info(f"Non-text JSON output received: {str(output_json)[:50]}...")
                    
            except json.JSONDecodeError:
                # For non-JSON outputs, integrate them seamlessly if they seem like text
                if isinstance(item.output, str) and len(item.output) > 0 and not item.output.startswith('{'):
                    await state["assistant_msg"].stream_token(f"\n\n{item.output}\n\n")
                    log.info(f"Integrated non-JSON output: {item.output[:50]}...")
                else:
                    log.warning(f"Unhandled tool output format: {item.output[:50]}...")

        # ── final assistant chunk that is not streamed as delta ────────────────
        elif item.type == "message_output_item":
            txt = ItemHelpers.text_message_output(item)
            await state["assistant_msg"].stream_token(txt)
            log.debug(f"Message output: {txt[:50]}...")
            
    except Exception as e:
        # Catch any exceptions to prevent the event handling from crashing
        log.exception(f"Error in handle_event: {e}")
        # Try to notify the user about the error
        try:
            await state["assistant_msg"].stream_token(f"\n\n[Error processing response: {str(e)}]\n\n")
        except Exception:
            pass
