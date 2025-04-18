"""
Streamlit web interface for Smart Agent.
This is a direct translation of the CLI chat client.
"""

import os
import sys
import json
import asyncio
import logging
from collections import deque

import streamlit as st

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add parent directory to path to import smart_agent modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Import Smart Agent modules
from smart_agent.tool_manager import ConfigManager
from smart_agent.agent import SmartAgent, PromptGenerator

# Initialize console for rich output
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
        base_url = config_manager.get_api_base_url()

        # Check if API key is set
        if not api_key:
            st.error("Error: API key is not set in config.yaml or environment variable.")
            return False

        # Get model configuration
        model_name = config_manager.get_model_name()
        temperature = config_manager.get_model_temperature()

        # Get Langfuse configuration
        langfuse_config = config_manager.get_langfuse_config()
        langfuse_enabled = langfuse_config.get("enabled", False)
        langfuse = None

        # Initialize Langfuse if enabled
        if langfuse_enabled:
            try:
                from langfuse import Langfuse

                langfuse = Langfuse(
                    public_key=langfuse_config.get("public_key", ""),
                    secret_key=langfuse_config.get("secret_key", ""),
                    host=langfuse_config.get("host", "https://cloud.langfuse.com"),
                )
                st.success("Langfuse monitoring enabled")
            except ImportError:
                st.warning("Langfuse package not installed. Run 'pip install langfuse' to enable monitoring.")
                langfuse_enabled = False

        try:
            # Import required libraries
            from openai import AsyncOpenAI

            # Initialize AsyncOpenAI client
            client = AsyncOpenAI(
                base_url=base_url,
                api_key=api_key,
            )

            # Get enabled tools
            enabled_tools = []
            for tool_id, tool_config in config_manager.get_tools_config().items():
                if config_manager.is_tool_enabled(tool_id):
                    tool_url = config_manager.get_tool_url(tool_id)
                    tool_name = tool_config.get("name", tool_id)
                    enabled_tools.append((tool_id, tool_name, tool_url))

            # Create MCP server list for the agent
            mcp_servers = []
            for tool_id, tool_name, tool_url in enabled_tools:
                st.info(f"Adding {tool_name} at {tool_url} to agent")
                mcp_servers.append(tool_url)

            # Create the agent - using SmartAgent wrapper class
            smart_agent = SmartAgent(
                model_name=model_name,
                openai_client=client,
                mcp_servers=mcp_servers,
                system_prompt=PromptGenerator.create_system_prompt(),
            )

            # Store the agent in session state
            st.session_state.smart_agent = smart_agent
            st.session_state.mcp_servers = mcp_servers
            st.session_state.client = client
            st.session_state.model_name = model_name
            st.session_state.langfuse = langfuse
            st.session_state.langfuse_enabled = langfuse_enabled
            st.session_state.temperature = temperature

            st.success(f"Agent initialized with {len(mcp_servers)} tools")

        except ImportError:
            st.error("Required packages not installed. Run 'pip install openai agent' to use the agent.")
            return False

        # Initialize conversation history
        system_prompt = PromptGenerator.create_system_prompt()
        st.session_state.conversation_history = [{"role": "system", "content": system_prompt}]
        
        # Mark agent as initialized
        st.session_state.agent_initialized = True
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
        
        # Reset the agent - using SmartAgent wrapper class
        st.session_state.smart_agent = SmartAgent(
            model_name=st.session_state.model_name,
            openai_client=st.session_state.client,
            mcp_servers=st.session_state.mcp_servers,
            system_prompt=PromptGenerator.create_system_prompt(),
        )
        
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
            response_container = st.empty()

            # Process the message with the agent
            async def run_agent():
                try:
                    # Create a copy of the conversation history
                    history = st.session_state.conversation_history.copy()
                    
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
                                                # In Streamlit, we'll update the container instead of printing
                                                response_container.markdown(''.join(batch))
                                                batch = []
                                            current_type = item[1]
                                            current_batch_type = current_type
                                            continue
                                        
                                        # Initialize batch type if not set
                                        if current_batch_type is None:
                                            current_batch_type = item[1]
                                        
                                        # If type changes within batch, print current batch and start new one
                                        if item[1] != current_batch_type:
                                            # In Streamlit, we'll update the container instead of printing
                                            response_container.markdown(''.join(batch))
                                            batch = [item[0]]
                                            current_batch_type = item[1]
                                        else:
                                            batch.append(item[0])
                                    
                                    # Print any remaining batch content
                                    if batch:
                                        # In Streamlit, we'll update the container instead of printing
                                        response_container.markdown(''.join(batch))
                                
                                await asyncio.sleep(interval)
                        except asyncio.CancelledError:
                            # Task cancellation is expected on completion
                            pass
                    
                    # Track the assistant's response
                    assistant_reply = ""
                    
                    # Import required classes for MCP
                    from agents.mcp import MCPServerSse, MCPServerStdio
                    from agents import Agent, OpenAIChatCompletionsModel, Runner, ItemHelpers
                    
                    # Create MCP servers based on transport type
                    mcp_servers_objects = []
                    for tool_id, tool_config in st.session_state.config_manager.get_tools_config().items():
                        if not st.session_state.config_manager.is_tool_enabled(tool_id):
                            continue
                        
                        transport_type = tool_config.get("transport", "stdio_to_sse").lower()
                        
                        # Import ReconnectingMCP for robust connections
                        from smart_agent.web.helpers.reconnecting_mcp import ReconnectingMCP
                        
                        # For SSE-based transports (stdio_to_sse, sse), use ReconnectingMCP
                        if transport_type in ["stdio_to_sse", "sse"]:
                            url = tool_config.get("url")
                            if url:
                                mcp_servers_objects.append(ReconnectingMCP(name=tool_id, params={"url": url}))
                        # For stdio transport, use MCPServerStdio with the command directly
                        elif transport_type == "stdio":
                            command = tool_config.get("command")
                            if command:
                                # For MCPServerStdio, we need to split the command into command and args
                                command_parts = command.split()
                                executable = command_parts[0]
                                args = command_parts[1:] if len(command_parts) > 1 else []
                                mcp_servers_objects.append(MCPServerStdio(name=tool_id, params={
                                    "command": executable,
                                    "args": args
                                }))
                        # For sse_to_stdio transport, always construct the command from the URL
                        elif transport_type == "sse_to_stdio":
                            # Get the URL from the configuration
                            url = tool_config.get("url")
                            if url:
                                # Construct the full supergateway command
                                command = f"npx -y supergateway --sse \"{url}\""
                                logger.debug(f"Constructed command for sse_to_stdio transport: '{command}'")
                                # For MCPServerStdio, we need to split the command into command and args
                                command_parts = command.split()
                                executable = command_parts[0]
                                args = command_parts[1:] if len(command_parts) > 1 else []
                                mcp_servers_objects.append(MCPServerStdio(name=tool_id, params={
                                    "command": executable,
                                    "args": args
                                }))
                            else:
                                logger.warning(f"Missing URL for sse_to_stdio transport type for tool {tool_id}")
                        # For any other transport types, log a warning
                        else:
                            logger.warning(f"Unknown transport type '{transport_type}' for tool {tool_id}")
                    
                    # Connect to all MCP servers with timeout and retry
                    connected_servers = []
                    for server in mcp_servers_objects:
                        try:
                            # Use a timeout for connection
                            connection_task = asyncio.create_task(server.connect())
                            await asyncio.wait_for(connection_task, timeout=10)  # 10 seconds timeout
                            
                            # For ReconnectingMCP, verify connection is established
                            if isinstance(server, ReconnectingMCP):
                                # Wait for ping to verify connection
                                await asyncio.sleep(1)
                                if not server._connected:
                                    st.warning(f"Connection to {server.name} not fully established. Skipping.")
                                    continue
                            
                            connected_servers.append(server)
                            st.success(f"Connected to {server.name}")
                        except asyncio.TimeoutError:
                            st.warning(f"Timeout connecting to MCP server {server.name}")
                            # Cancel the connection task
                            connection_task.cancel()
                            try:
                                await connection_task
                            except (asyncio.CancelledError, Exception):
                                pass
                        except Exception as e:
                            st.warning(f"Error connecting to MCP server {server.name}: {e}")
                    
                    # Update the list with only connected servers
                    mcp_servers_objects = connected_servers
                    
                    try:
                        # Create the SmartAgent instead of direct Agent
                        agent = SmartAgent(
                            model_name=st.session_state.model_name,
                            openai_client=st.session_state.client,
                            mcp_servers=mcp_servers_objects,
                            system_prompt=history[0]["content"] if history and history[0]["role"] == "system" else None,
                        )
                        
                        # Start the streaming task
                        streaming_task = asyncio.create_task(
                            stream_output(buffer, output_interval, output_size, stream_ended)
                        )
                        
                        # Run the agent with the conversation history
                        # Access the underlying Agent instance from SmartAgent
                        result = Runner.run_streamed(agent.agent, history, max_turns=100)
                        is_thought = False
                        
                        # Create a placeholder for the assistant's response
                        assistant_placeholder = response_container.empty()
                        
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
                                            
                                            # Display thought directly in the sequence container like CLI
                                            with sequence_container:
                                                st.markdown(f"<div style='color: cyan'>&lt;thought&gt;</div>", unsafe_allow_html=True)
                                                st.markdown(f"<div style='color: cyan'>{value}</div>", unsafe_allow_html=True)
                                                st.markdown(f"<div style='color: cyan'>&lt;/thought&gt;</div>", unsafe_allow_html=True)
                                            
                                            # Add the opening thought tag to the buffer with thought type
                                            add_to_buffer("\n<thought>\n", "thought")
                                            
                                            # Add the thought content with thought type
                                            add_to_buffer(str(value), "thought")
                                            
                                            # Add the closing thought tag with thought type
                                            add_to_buffer("\n</thought>", "thought")
                                            
                                            # Update assistant reply
                                            assistant_reply += f"\n<thought>\n{value}\n</thought>"
                                        else:
                                            is_thought = False
                                            
                                            # Check if this is a code tool
                                            if key == "code":
                                                # Get code string
                                                code_str = str(value)
                                                
                                                # Display tool call directly in the sequence container like CLI
                                                with sequence_container:
                                                    st.markdown(f"<div style='color: yellow'>&lt;tool name=\"{key}\"&gt;</div>", unsafe_allow_html=True)
                                                    st.code(code_str, language=None)  # No language specification
                                                    st.markdown(f"<div style='color: yellow'>&lt;/tool&gt;</div>", unsafe_allow_html=True)
                                                
                                                # Add tool call to buffer with tool type
                                                tool_opening = f"\n<tool name=\"{key}\">\n"
                                                add_to_buffer(tool_opening, "tool")
                                                
                                                # Add code with markdown formatting (no language specification)
                                                add_to_buffer(f"```\n", "tool")
                                                add_to_buffer(code_str, "tool")
                                                add_to_buffer("\n```", "tool")
                                                
                                                add_to_buffer("\n</tool>", "tool")
                                                
                                                # Update assistant reply with formatted code (no language specification)
                                                assistant_reply += f"\n<tool name=\"{key}\">\n```\n{code_str}\n```\n</tool>"
                                            else:
                                                # Display tool call directly in the sequence container like CLI
                                                with sequence_container:
                                                    st.markdown(f"<div style='color: yellow'>&lt;tool name=\"{key}\"&gt;</div>", unsafe_allow_html=True)
                                                    st.markdown(f"<div style='color: yellow'>{value}</div>", unsafe_allow_html=True)
                                                    st.markdown(f"<div style='color: yellow'>&lt;/tool&gt;</div>", unsafe_allow_html=True)
                                                
                                                # Regular tool call
                                                tool_opening = f"\n<tool name=\"{key}\">\n"
                                                add_to_buffer(tool_opening, "tool")
                                                add_to_buffer(str(value), "tool")
                                                add_to_buffer("\n</tool>", "tool")
                                                
                                                # Update assistant reply
                                                assistant_reply += f"\n<tool name=\"{key}\">\n{value}\n</tool>"
                                    except (json.JSONDecodeError, StopIteration) as e:
                                        # Add error to buffer with error type
                                        error_text = f"Error parsing tool call: {e}"
                                        add_to_buffer("\n<error>", "error")
                                        add_to_buffer(error_text, "error")
                                        add_to_buffer("</error>", "error")
                                        
                                        # Update assistant reply
                                        assistant_reply += f"\n<error>{error_text}</error>"
                                        
                                        # Show error in UI
                                        with sequence_container:
                                            st.error(f"Error parsing tool call: {e}")
                                elif event.item.type == "tool_call_output_item":
                                    if not is_thought:
                                        try:
                                            output_text = json.loads(event.item.output).get("text", "")
                                            
                                            # Display tool output directly in the sequence container like CLI
                                            with sequence_container:
                                                st.markdown(f"<div style='color: bright_green'>&lt;tool_output&gt;</div>", unsafe_allow_html=True)
                                                st.markdown(f"<div style='color: bright_green'>{output_text}</div>", unsafe_allow_html=True)
                                                st.markdown(f"<div style='color: bright_green'>&lt;/tool_output&gt;</div>", unsafe_allow_html=True)
                                            
                                            # Pause token streaming
                                            stream_ended.set()
                                            await streaming_task
                                            
                                            # Update assistant reply
                                            assistant_reply += f"\n<tool_output>\n{output_text}\n</tool_output>"
                                            
                                            # Reset for continued streaming
                                            stream_ended.clear()
                                            streaming_task = asyncio.create_task(
                                                stream_output(buffer, output_interval, output_size, stream_ended)
                                            )
                                        except json.JSONDecodeError:
                                            # Display tool output directly in the sequence container like CLI
                                            with sequence_container:
                                                st.markdown(f"<div style='color: bright_green'>&lt;tool_output&gt;</div>", unsafe_allow_html=True)
                                                st.markdown(f"<div style='color: bright_green'>{event.item.output}</div>", unsafe_allow_html=True)
                                                st.markdown(f"<div style='color: bright_green'>&lt;/tool_output&gt;</div>", unsafe_allow_html=True)
                                            
                                            # Pause token streaming
                                            stream_ended.set()
                                            await streaming_task
                                            
                                            # Update assistant reply
                                            assistant_reply += f"\n<tool_output>\n{event.item.output}\n</tool_output>"
                                            
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
                                        
                                        # Update the assistant placeholder
                                        assistant_placeholder.markdown(text_message)
                                    else:
                                        # Add system message to buffer with system type
                                        add_to_buffer(f"\n<{role}>", "system")
                                        add_to_buffer(str(text_message), "system")
                                        add_to_buffer(f"</{role}>", "system")
                                        
                                        # Update assistant reply
                                        assistant_reply += f"\n<{role}>{text_message}</{role}>"
                                        
                                        # Show system message in UI
                                        with sequence_container:
                                            st.info(f"**{role.capitalize()}**: {text_message}")
                        
                        # Signal that the stream has ended
                        stream_ended.set()
                        # Wait for the streaming task to finish processing the buffer
                        await streaming_task
                        
                        # Add a newline after completion
                        assistant_placeholder.markdown(assistant_reply.strip())
                        
                        # Add assistant message to conversation history
                        st.session_state.conversation_history.append({"role": "assistant", "content": assistant_reply.strip()})
                        st.session_state.messages.append({"role": "assistant", "content": assistant_reply.strip()})
                        
                        # Log to Langfuse if enabled
                        if st.session_state.langfuse_enabled and st.session_state.langfuse:
                            try:
                                trace = st.session_state.langfuse.trace(
                                    name="chat_session",
                                    metadata={"model": st.session_state.model_name, "temperature": st.session_state.temperature},
                                )
                                trace.generation(
                                    name="assistant_response",
                                    model=st.session_state.model_name,
                                    prompt=prompt,
                                    completion=assistant_reply,
                                )
                            except Exception as e:
                                st.error(f"Langfuse logging error: {e}")
                        
                        return assistant_reply.strip()
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
