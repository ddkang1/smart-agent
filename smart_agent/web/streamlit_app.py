"""
Streamlit web interface for Smart Agent.
This is a direct reflection of the CLI chat client.
"""

import os
import sys
import json
import asyncio
import logging

import streamlit as st

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Disable tracing if agents package is available
try:
    from agents import set_tracing_disabled
    set_tracing_disabled(disabled=True)
except ImportError:
    logger.debug("Agents package not installed. Tracing will not be disabled.")

# Add parent directory to path to import smart_agent modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from smart_agent.tool_manager import ConfigManager
from smart_agent.agent import PromptGenerator

# Page configuration
st.set_page_config(
    page_title="Smart Agent Chat",
    page_icon="🤖",
    layout="wide",
)

# Main chat interface
st.title("Smart Agent Chat")

# Sidebar with minimal controls
with st.sidebar:
    st.title("Smart Agent Chat")

    # Get config paths from environment variables
    config_path = os.environ.get("SMART_AGENT_CONFIG")
    tools_path = os.environ.get("SMART_AGENT_TOOLS")

    # Show config paths if available
    if config_path:
        st.info(f"Config: {config_path}")
    if tools_path:
        st.info(f"Tools: {tools_path}")

    # Initialize button
    initialize_button = st.button("Initialize Agent")

    # Clear chat button
    clear_button = st.button("Clear Chat")

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []

if "conversation_history" not in st.session_state:
    st.session_state.conversation_history = []

if "agent_initialized" not in st.session_state:
    st.session_state.agent_initialized = False

if "config_manager" not in st.session_state:
    st.session_state.config_manager = None

# Function to initialize the agent
def initialize_agent():
    try:
        # Create configuration manager
        config_manager = ConfigManager(config_path=config_path if config_path else None,
                                      tools_path=tools_path if tools_path else None)
        st.session_state.config_manager = config_manager

        # Get API configuration
        api_key = config_manager.get_api_key()

        # Check if API key is set
        if not api_key:
            st.error("Error: API key is not set in config.yaml or environment variable.")
            return False

        # Get model configuration
        model_name = config_manager.get_model_name()

        # Initialize conversation history with system prompt
        system_prompt = PromptGenerator.create_system_prompt()
        st.session_state.conversation_history = [{"role": "system", "content": system_prompt}]

        # Mark agent as initialized
        st.session_state.agent_initialized = True
        st.success(f"Agent initialized with model: {model_name}")
        return True

    except Exception as e:
        st.error(f"Error initializing agent: {e}")
        import traceback
        st.error(traceback.format_exc())
        return False

# Auto-initialize if config is provided
if config_path and not st.session_state.agent_initialized:
    initialize_agent()

# Handle initialize button click
if initialize_button:
    initialize_agent()

# Handle clear button click
if clear_button:
    if st.session_state.agent_initialized:
        # Reset the conversation history with system prompt
        system_prompt = PromptGenerator.create_system_prompt()
        st.session_state.conversation_history = [{"role": "system", "content": system_prompt}]
        st.session_state.messages = []
        st.success("Conversation history cleared")
    else:
        st.warning("Agent not initialized yet")

# Display chat messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Chat input
if prompt := st.chat_input("You: "):
    if not st.session_state.agent_initialized:
        st.error("Please initialize the agent first.")
    else:
        # Add user message to chat
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Add user message to conversation history
        st.session_state.conversation_history.append({"role": "user", "content": prompt})

        # Process with agent
        with st.chat_message("assistant"):
            # Create a container for the sequential output
            sequence_container = st.container()

            # Create a container for the final response
            # response_container = st.empty()

            # Process the message with the agent
            async def run_agent():
                try:
                    # Get API configuration
                    api_key = st.session_state.config_manager.get_api_key()
                    base_url = st.session_state.config_manager.get_api_base_url()
                    model_name = st.session_state.config_manager.get_model_name()

                    # Import required libraries
                    try:
                        from openai import AsyncOpenAI
                    except ImportError:
                        st.error("OpenAI package not installed. Please install it with 'pip install openai'")
                        return

                    # Create OpenAI client
                    client = AsyncOpenAI(
                        base_url=base_url,
                        api_key=api_key,
                    )

                    # Get tool configurations
                    mcp_servers = []

                    # Get enabled tool URLs
                    for tool_id, tool_config in st.session_state.config_manager.get_tools_config().items():
                        if not st.session_state.config_manager.is_tool_enabled(tool_id):
                            continue

                        url = tool_config.get("url")
                        if url:
                            mcp_servers.append(url)

                    # Import required classes
                    try:
                        from agents.mcp import MCPServerSse
                        from agents import Agent, OpenAIChatCompletionsModel, Runner, ItemHelpers
                    except ImportError:
                        st.error("Required packages not installed. Run 'pip install openai-agents' to use the agent.")
                        return

                    # Create MCP servers based on transport type
                    mcp_servers_objects = []
                    for tool_id, tool_config in st.session_state.config_manager.get_tools_config().items():
                        if not st.session_state.config_manager.is_tool_enabled(tool_id):
                            continue

                        transport_type = tool_config.get("transport", "stdio_to_sse").lower()
                        url = tool_config.get("url")

                        # Check if we have a URL (required for client-only mode)
                        if not url:
                            st.warning(f"Tool {tool_id} has no URL and will be skipped.")
                            continue

                        # For SSE-based transports (stdio_to_sse, sse), use MCPServerSse
                        if transport_type in ["stdio_to_sse", "sse"]:
                            mcp_servers_objects.append(MCPServerSse(name=tool_id, params={"url": url}))

                    # Connect to all MCP servers
                    for server in mcp_servers_objects:
                        await server.connect()

                    try:
                        # Create the agent directly like in CLI chat
                        agent = Agent(
                            name="Assistant",
                            instructions=st.session_state.conversation_history[0]["content"] if st.session_state.conversation_history and st.session_state.conversation_history[0]["role"] == "system" else None,
                            model=OpenAIChatCompletionsModel(
                                model=model_name,
                                openai_client=client,
                            ),
                            mcp_servers=mcp_servers_objects,
                        )

                        # Run the agent with the conversation history
                        result = Runner.run_streamed(agent, st.session_state.conversation_history, max_turns=100)
                        assistant_reply = ""
                        is_thought = False

                        # Process the stream events
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
                                            with sequence_container:
                                                with st.expander("Thought", expanded=False):
                                                    st.info(value)
                                            assistant_reply += "\n[thought]: " + value
                                        else:
                                            is_thought = False
                                            with sequence_container:
                                                with st.expander(f"Tool Call: {key}", expanded=False):
                                                    st.warning(value)
                                    except (json.JSONDecodeError, StopIteration) as e:
                                        st.error(f"Error parsing tool call: {e}")
                                elif event.item.type == "tool_call_output_item":
                                    if not is_thought:
                                        try:
                                            output_text = json.loads(event.item.output).get("text", "")
                                            with sequence_container:
                                                with st.expander("Tool Output", expanded=False):
                                                    st.success(output_text)
                                        except json.JSONDecodeError:
                                            with sequence_container:
                                                with st.expander("Tool Output", expanded=False):
                                                    st.success(event.item.output)
                                elif event.item.type == "message_output_item":
                                    role = event.item.raw_item.role
                                    text_message = ItemHelpers.text_message_output(event.item)
                                    # print(role, text_message, flush=True)
                                    if role == "assistant":
                                        with sequence_container:
                                            with st.expander("Assistant", expanded=True):
                                                st.markdown(text_message)
                                        # response_container.markdown(text_message)
                                        assistant_reply += "\n[response]: " + text_message
                                    else:
                                        with sequence_container:
                                            st.markdown(f"**{role.capitalize()}**: {text_message}")

                        # Add assistant message to conversation history
                        final_response = assistant_reply.strip()
                        if final_response:
                            # Extract just the response part for the conversation history
                            response_only = ""
                            for line in final_response.split("\n"):
                                if line.startswith("[response]:"):
                                    response_only += line[len("[response]:"):].strip() + "\n"

                            if response_only:
                                st.session_state.conversation_history.append({"role": "assistant", "content": response_only.strip()})
                                st.session_state.messages.append({"role": "assistant", "content": response_only.strip()})
                            else:
                                # If no response part found, use the whole thing
                                st.session_state.conversation_history.append({"role": "assistant", "content": final_response})
                                st.session_state.messages.append({"role": "assistant", "content": final_response})

                    finally:
                        # Clean up MCP servers
                        for server in mcp_servers_objects:
                            if hasattr(server, 'cleanup') and callable(server.cleanup):
                                try:
                                    if asyncio.iscoroutinefunction(server.cleanup):
                                        await server.cleanup()  # Use await for async cleanup
                                    else:
                                        server.cleanup()  # Call directly for sync cleanup
                                except Exception as e:
                                    st.error(f"Error during server cleanup: {e}")

                except Exception as e:
                    st.error(f"Error: {e}")
                    import traceback
                    st.error(traceback.format_exc())

            # Run the async function
            asyncio.run(run_agent())

# Footer
st.sidebar.markdown("---")
st.sidebar.markdown(f"Smart Agent v0.7.0")
st.sidebar.markdown("[GitHub Repository](https://github.com/ddkang1/smart-agent)")
