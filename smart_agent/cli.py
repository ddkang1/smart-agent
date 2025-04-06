#!/usr/bin/env python
"""
CLI interface for Smart Agent.
"""

import os
import sys
import time
import signal
import socket
import yaml
import json
import click
import subprocess
import logging
import re
import urllib.parse
import locale
import shutil
import getpass
import datetime
from typing import List, Dict, Optional, Any, Tuple
from pathlib import Path
import asyncio
import platform

from rich.console import Console
from rich.markdown import Markdown

from . import __version__
from .tool_manager import ConfigManager
from .agent import SmartAgent
from agents import set_tracing_disabled

set_tracing_disabled(disabled=True)

console = Console()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

try:
    from openai import AsyncOpenAI
except ImportError:
    pass

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

class PromptGenerator:
    @staticmethod
    def create_system_prompt():
        """
        Generates the system prompt guidelines with a dynamically updated datetime.
        """
        current_datetime = datetime.datetime.now().strftime(
            locale.nl_langinfo(locale.D_T_FMT)
            if hasattr(locale, "nl_langinfo")
            else "%c"
        )

        return f"""## Guidelines for Using the Think Tool
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


def chat_loop(config_manager: ConfigManager):
    """
    Run the chat loop.

    Args:
        config_manager: Configuration manager instance
    """
    # Get API configuration
    api_key = config_manager.get_api_key()
    base_url = config_manager.get_api_base_url()

    # Check if API key is set
    if not api_key:
        print("Error: API key is not set in config.yaml or environment variable.")
        print("Please set the api_key in config/config.yaml or use OPENAI_API_KEY environment variable.")
        return

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
            print("Langfuse monitoring enabled")
        except ImportError:
            print(
                "Langfuse package not installed. Run 'pip install langfuse' to enable monitoring."
            )
            langfuse_enabled = False

    try:
        # Import required libraries
        from openai import AsyncOpenAI
        from smart_agent.agent import SmartAgent

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
            print(f"Adding {tool_name} at {tool_url} to agent")
            mcp_servers.append(tool_url)

        # Create the agent - using SmartAgent wrapper class
        smart_agent = SmartAgent(
            model_name=model_name,
            openai_client=client,
            mcp_servers=mcp_servers,
            system_prompt=PromptGenerator.create_system_prompt(),
        )

        print(f"Agent initialized with {len(mcp_servers)} tools")

    except ImportError:
        print(
            "Required packages not installed. Run 'pip install openai agent' to use the agent."
        )
        return

    print("\nSmart Agent Chat")
    print("Type 'exit' or 'quit' to end the conversation")
    print("Type 'clear' to clear the conversation history")

    # Initialize conversation history
    conversation_history = [{"role": "system", "content": PromptGenerator.create_system_prompt()}]

    # Chat loop
    while True:
        # Get user input
        user_input = input("\nYou: ")

        # Check for exit command
        if user_input.lower() in ["exit", "quit"]:
            print("Exiting chat...")
            break

        # Check for clear command
        if user_input.lower() == "clear":
            # Reset the conversation history
            conversation_history = [{"role": "system", "content": PromptGenerator.create_system_prompt()}]
            
            # Reset the agent - using SmartAgent wrapper class
            smart_agent = SmartAgent(
                model_name=model_name,
                openai_client=client,
                mcp_servers=mcp_servers,
                system_prompt=PromptGenerator.create_system_prompt(),
            )
            print("Conversation history cleared")
            continue

        # Add the user message to history
        conversation_history.append({"role": "user", "content": user_input})

        # Get assistant response
        print("\nAssistant: ", end="", flush=True)

        try:
            # Use the agent for streaming response
            async def run_agent():
                # Add the user message to history
                history = conversation_history.copy()
                
                # Get the MCP server URLs
                mcp_urls = [url for url in mcp_servers if isinstance(url, str)]

                # Create the OpenAI client
                client = AsyncOpenAI(
                    base_url=base_url,
                    api_key=api_key,
                )

                # Import required classes
                from agents.mcp import MCPServerSse
                from agents import Agent, OpenAIChatCompletionsModel, Runner, ItemHelpers

                # Create MCP servers using the same pattern as research.py
                mcp_servers_objects = []
                for url in mcp_urls:
                    mcp_servers_objects.append(MCPServerSse(params={"url": url}))

                # Connect to all MCP servers
                for server in mcp_servers_objects:
                    await server.connect()

                try:
                    # Create the agent directly like in research.py
                    agent = Agent(
                        name="Assistant",
                        instructions=history[0]["content"] if history and history[0]["role"] == "system" else None,
                        model=OpenAIChatCompletionsModel(
                            model=model_name,
                            openai_client=client,
                        ),
                        mcp_servers=mcp_servers_objects,
                    )

                    # Run the agent with the conversation history
                    result = Runner.run_streamed(agent, history, max_turns=100)
                    assistant_reply = ""
                    is_thought = False

                    # Process the stream events exactly like in research.py
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
                                        print(f"\n[thought]:\n{value}", flush=True)
                                        assistant_reply += "\n[thought]: " + value
                                    else:
                                        is_thought = False
                                        print(f"\n[{key}]:\n{value}", flush=True)
                                except (json.JSONDecodeError, StopIteration) as e:
                                    print(f"\n[Error parsing tool call]: {e}", flush=True)
                            elif event.item.type == "tool_call_output_item":
                                if not is_thought:
                                    try:
                                        output_text = json.loads(event.item.output).get("text", "")
                                        print(f"\n[Tool Output]:\n{output_text}", flush=True)
                                    except json.JSONDecodeError:
                                        print(f"\n[Tool Output]:\n{event.item.output}", flush=True)
                            elif event.item.type == "message_output_item":
                                role = event.item.raw_item.role
                                text_message = ItemHelpers.text_message_output(event.item)
                                if role == "assistant":
                                    print(f"\n[{role}]:\n{text_message}", flush=True)
                                    assistant_reply += "\n[response]: " + text_message
                                else:
                                    print(f"\n[{role}]:\n{text_message}", flush=True)

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
                                print(f"Error during server cleanup: {e}")

            # Run the agent in an event loop
            import asyncio
            assistant_response = asyncio.run(run_agent())

            # Append the assistant's response to maintain context
            conversation_history.append({"role": "assistant", "content": assistant_response})

            # Log to Langfuse if enabled
            if langfuse_enabled and langfuse:
                try:
                    trace = langfuse.trace(
                        name="chat_session",
                        metadata={"model": model_name, "temperature": temperature},
                    )
                    trace.generation(
                        name="assistant_response",
                        model=model_name,
                        prompt=user_input,
                        completion="Agent response (not captured)",
                    )
                except Exception as e:
                    print(f"Langfuse logging error: {e}")

        except KeyboardInterrupt:
            print("\nOperation interrupted by user.")
            continue
        except asyncio.CancelledError:
            print("\nOperation cancelled.")
            continue
        except Exception as e:
            print(f"\nError: {e}")
            import traceback
            traceback.print_exc()

    print("\nChat session ended")


def start_chat(config_manager: ConfigManager):
    """
    Start a chat session with Smart Agent.

    Args:
        config_manager: Configuration manager
    """
    # Start chat loop
    chat_loop(config_manager)


def launch_tools(config_manager: ConfigManager) -> List[subprocess.Popen]:
    """
    Launch all enabled tool services.

    Args:
        config_manager: Configuration manager

    Returns:
        List of subprocesses
    """
    processes = []
    tools_config = config_manager.get_tools_config()
    print("Launching tool services...")

    # Check if tools are present
    if not tools_config:
        print("No tool configurations found.")
        return processes

    # First, clean up any existing tool processes to prevent duplicates
    print("Checking for existing tool processes...")
    cleaned = cleanup_existing_tool_processes()
    if cleaned > 0:
        print(f"Cleaned up {cleaned} existing tool processes.")

    # Launch each enabled tool
    for tool_id, tool_config in tools_config.items():
        if tool_config.get("enabled", False):
            # Check if this tool is already running
            is_running, tool_pids = is_tool_running(tool_id)
            if is_running:
                print(f"Tool {tool_id} is already running. Skipping.")
                continue

            # Get URL and extract port
            url = tool_config.get("url")
            port = None
            try:
                from urllib.parse import urlparse
                parsed_url = urlparse(url)
                port = parsed_url.port
            except Exception:
                pass

            # Default port if not specified
            if not port:
                # Auto-assign a port starting from 8000
                # Find a free port to avoid conflicts
                port = find_free_port(8000)

                # Update the URL with the new port
                url_parts = urllib.parse.urlparse(url)
                netloc_parts = url_parts.netloc.split(':')
                netloc = f"{netloc_parts[0]}:{port}"
                url_parts = url_parts._replace(netloc=netloc)
                url = urllib.parse.urlunparse(url_parts)

                # Update the tool config with the new URL
                tool_config["url"] = url

            # Launch based on tool type
            tool_type = tool_config.get("type", "").lower()

            if tool_type == "uvx":
                print(f"Launching UVX tool: {tool_id}")
                try:
                    # Get the executable name from the repository URL
                    # The executable name should match what's used in the repository
                    repo = tool_config.get("repository", "")

                    # Extract the repository name from the URL
                    # Example: git+https://github.com/ddkang1/mcp-think-tool -> mcp-think-tool
                    if repo:
                        # Extract the last part of the URL (after the last /)
                        executable_name = repo.split("/")[-1]

                        # Remove git+ prefix if present
                        if executable_name.startswith("git+"):
                            executable_name = executable_name[4:]

                        # Remove .git suffix if present
                        if executable_name.endswith(".git"):
                            executable_name = executable_name[:-4]
                    else:
                        # Fallback to tool_id with hyphens if repository is not specified
                        executable_name = tool_id.replace("_", "-")

                    print(f"Using executable name: {executable_name}")

                    # Get the repository
                    repo = tool_config.get("repository", "")

                    # Construct the launch command exactly as in the working examples
                    # Get the hostname from the URL or use grai-dev.gilead.com
                    parsed_url = urllib.parse.urlparse(url)
                    hostname = parsed_url.hostname or "grai-dev.gilead.com"

                    # Format the command exactly as in the examples
                    tool_cmd = [
                        "npx", "-y", "supergateway",
                        "--stdio", f"uvx --from {repo} {executable_name}",
                        "--header", "X-Accel-Buffering: no",
                        "--port", str(port),
                        "--baseUrl", f"http://{hostname}:{port}",
                        "--cors"
                    ]

                    # Print the command for debugging
                    cmd_str = " ".join(tool_cmd)
                    print(f"Launching command: {cmd_str}")

                    # Initialize environment variables
                    env = os.environ.copy()

                    # Get the tool environment variables prefix
                    # E.g., DDGMCP_ for ddg_mcp
                    env_prefix = config_manager.get_env_prefix(tool_id)

                    # Set the URL environment variable
                    # E.g., DDGMCP_URL for ddg_mcp
                    env[f"{env_prefix}URL"] = url

                    # Launch the process in the background using the exact format that works
                    if os.name != 'nt':  # Not on Windows
                        # Format the command exactly like the working example
                        # npx -y supergateway --stdio "uvx --from git+https://github.com/ddkang1/mcp-think-tool mcp-think-tool" --header "X-Accel-Buffering: no" --port 8000 --baseUrl http://grai-dev.gilead.com:8000 --cors &

                        # Combine the command parts
                        cmd_parts = [
                            "npx", "-y", "supergateway",
                            "--stdio", f'"uvx --from {repo} {executable_name}"',
                            "--header", '"X-Accel-Buffering: no"',
                            "--port", str(port),
                            "--baseUrl", f"http://{hostname}:{port}",
                            "--cors",
                            "&"  # Run in background
                        ]

                        # Create the command string
                        cmd_str = " ".join(cmd_parts)
                        print(f"Executing shell command: {cmd_str}")

                        # Use os.system to run the command in the background
                        os.system(cmd_str)

                        # Create a dummy process object for tracking
                        class DummyProcess:
                            def __init__(self):
                                self.pid = None

                        process = DummyProcess()
                    else:
                        # Windows doesn't have the same background process handling
                        print("Warning: Windows support is limited. Process may not start correctly.")
                        process = subprocess.Popen(
                            tool_cmd,
                            env=env,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if hasattr(subprocess, 'CREATE_NEW_PROCESS_GROUP') else 0
                        )

                    # We can't track PIDs directly since we're using os.system with &
                    # Just mark the tool as available
                    processes.append(process)
                    print(f"{tool_id} available at {url}")
                except Exception as e:
                    print(f"Failed to launch UVX tool {tool_id}: {str(e)}")

            elif tool_type == "docker":
                print(f"Launching Docker tool: {tool_id}")
                try:
                    # Get the container image
                    container_image = tool_config.get("image", "")
                    if not container_image:
                        print(f"No container image specified for {tool_id}")
                        continue

                    # Prepare Docker run command
                    # Use a standardized container name for easier management
                    container_name = f"smart-agent-{tool_id}"

                    # Check if container already exists and is running
                    try:
                        result = subprocess.run(
                            ["docker", "ps", "-q", "-f", f"name={container_name}"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            check=False,
                        )
                        if result.stdout.strip():
                            # Container exists and is running
                            print(f"Docker container {container_name} is already running.")
                            continue

                        # Check if container exists but is not running
                        result = subprocess.run(
                            ["docker", "ps", "-aq", "-f", f"name={container_name}"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            check=False,
                        )
                        if result.stdout.strip():
                            # Container exists but is not running, remove it to avoid conflicts
                            subprocess.run(
                                ["docker", "rm", "-f", container_name],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                check=False,
                            )
                            print(f"Removed existing Docker container {container_name}")
                    except Exception as e:
                        print(f"Error checking container status: {str(e)}")

                    # Start the SSE server via supergateway using stdio
                    print(f"Launching Docker container via supergateway: {tool_id}")

                    # Get the storage path for Docker volume mounting
                    storage_path = tool_config.get("storage_path", "./data")

                    # Format the command exactly as in the examples
                    # Example: docker run -i --rm --pull=always -v ./data:/mnt/data/ ghcr.io/ddkang1/mcp-py-repl:latest
                    docker_run_cmd = f"docker run -i --rm --pull=always -v {storage_path}:/mnt/data/ {container_image}"
                    print(f"Docker run command: {docker_run_cmd}")

                    # Get the hostname from the URL or use grai-dev.gilead.com
                    parsed_url = urllib.parse.urlparse(url)
                    hostname = parsed_url.hostname or "grai-dev.gilead.com"

                    # Build the supergateway command exactly as in the examples
                    gateway_cmd = [
                        "npx", "-y", "supergateway",
                        "--stdio", docker_run_cmd,
                        "--header", "X-Accel-Buffering: no",
                        "--port", str(port),
                        "--baseUrl", f"http://{hostname}:{port}",
                        "--cors"
                    ]

                    # Print the command for debugging
                    cmd_str = " ".join(gateway_cmd)
                    print(f"Launching command: {cmd_str}")

                    # Initialize environment variables
                    env = os.environ.copy()

                    # Launch the gateway process in the background using the exact format that works
                    if os.name != 'nt':  # Not on Windows
                        # Format the command exactly like the working example
                        # npx -y supergateway --stdio "docker run -i --rm --pull=always -v ./data:/mnt/data/ ghcr.io/ddkang1/mcp-py-repl:latest" --header "X-Accel-Buffering: no" --port 8002 --baseUrl http://grai-dev.gilead.com:8002 --cors &

                        # Combine the command parts
                        cmd_parts = [
                            "npx", "-y", "supergateway",
                            "--stdio", f'"{docker_run_cmd}"',
                            "--header", '"X-Accel-Buffering: no"',
                            "--port", str(port),
                            "--baseUrl", f"http://{hostname}:{port}",
                            "--cors",
                            "&"  # Run in background
                        ]

                        # Create the command string
                        cmd_str = " ".join(cmd_parts)
                        print(f"Executing shell command: {cmd_str}")

                        # Use os.system to run the command in the background
                        os.system(cmd_str)

                        # Create a dummy process object for tracking
                        class DummyProcess:
                            def __init__(self):
                                self.pid = None

                        process = DummyProcess()
                    else:
                        # Windows doesn't have the same background process handling
                        print("Warning: Windows support is limited. Process may not start correctly.")
                        process = subprocess.Popen(
                            gateway_cmd,
                            env=env,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if hasattr(subprocess, 'CREATE_NEW_PROCESS_GROUP') else 0
                        )

                    # We can't track PIDs directly since we're using os.system with &
                    # Just mark the tool as available
                    processes.append(process)
                    print(f"{tool_id} available at {url}")
                except Exception as e:
                    print(f"Failed to launch Docker tool {tool_id}: {str(e)}")

    # If we found some tools but none were actually started, check what's happening
    if tools_config and not processes:
        already_running = []
        for tool_id, tool_config in tools_config.items():
            if tool_config.get("enabled", False):
                is_running, _ = is_tool_running(tool_id)
                if is_running:
                    already_running.append(tool_id)

        if already_running:
            print(f"\nAll enabled tools are already running: {', '.join(already_running)}")
        else:
            print("\nNo tools were started. Check configuration.")
    elif processes:
        print("\nAll enabled tools are now running.")

    return processes


@click.command()
@click.option(
    "--config",
    default=None,
    help="Path to configuration file",
)
@click.option("--tools", is_flag=True, help="Start tool services")
@click.option("--proxy", is_flag=True, help="Start LiteLLM proxy service")
@click.option("--all", is_flag=True, help="Start all services (tools and proxy)")
@click.option("--foreground", "-f", is_flag=True, help="Run services in foreground (blocks terminal)")
def start(config, tools, proxy, all, foreground):
    """
    Start tool and proxy services.

    Args:
        config: Path to config file
        tools: Whether to start tool services
        proxy: Whether to start proxy services
        all: Whether to start all services
        foreground: Whether to run in foreground mode (blocks terminal)
    """
    # Start processes
    tool_processes = []
    proxy_process = None

    # If --all is specified, enable both tools and proxy
    if all:
        tools = True
        proxy = True

    # If neither flag is specified, default to starting all services
    if not tools and not proxy:
        tools = True
        proxy = True

    # Save terminal state
    if os.name != 'nt':
        try:
            # Save terminal settings
            os.system('stty -g > /tmp/smart_agent_stty_settings.txt')
        except Exception:
            pass

    try:
        # Use a more compatible way to clear the screen
        if os.name == 'nt':
            os.system('cls')
        else:
            os.system('clear')
        if config:
            config_manager = ConfigManager(config_file=config)
        else:
            config_manager = ConfigManager()

        # Start tool services
        if tools:
            tool_processes = launch_tools(config_manager)
            if tool_processes:
                print("Tool services started successfully.")
            else:
                print("No tool services were started.")

        # Start proxy services
        if proxy:
            base_url = config_manager.get_config("api", "base_url") or "http://localhost:4000"

            if base_url is None or "localhost" in base_url or "127.0.0.1" in base_url:
                # Use Docker to run LiteLLM proxy
                proxy_process = launch_litellm_proxy(config_manager)
                if proxy_process:
                    print("LiteLLM proxy started successfully.")
                else:
                    print("LiteLLM proxy not started. It may already be running.")
            else:
                # Remote proxy
                print(f"Using remote LiteLLM proxy at {base_url}")

        if not (tool_processes or proxy_process):
            print("No services were started. Use --tools or --proxy flags to specify which services to start.")
            return

        # If running in foreground mode, keep the terminal blocked until Ctrl+C
        if foreground:
            # Keep services running until Ctrl+C
            print("\nPress Ctrl+C to stop all services.")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nStopping all services...")
            finally:
                # Clean up all processes
                all_processes = tool_processes or []
                if proxy_process:
                    all_processes.append(proxy_process)
                # Terminate all processes
                for process in all_processes:
                    if process and process.pid:
                        try:
                            if os.name == 'nt':  # Windows
                                subprocess.run(
                                    ["taskkill", "/F", "/PID", str(process.pid)],
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    check=False
                                )
                            else:  # Unix-like
                                os.kill(process.pid, signal.SIGTERM)
                        except Exception as e:
                            print(f"Error terminating process {process.pid}: {e}")

        else:
            # Running in background mode (default) - return immediately after starting services
            # Write process IDs to a file for potential cleanup later
            pid_file = os.path.join(os.path.expanduser("~"), ".smart_agent_pids")
            with open(pid_file, "w") as f:
                if tool_processes:
                    for proc in tool_processes:
                        if proc and proc.pid:
                            f.write(f"{proc.pid}\n")
                if proxy_process and proxy_process.pid:
                    f.write(f"{proxy_process.pid}\n")

            print("\nServices are running in the background.")
            print(f"Process IDs saved to {pid_file}")
            print("Use 'smart-agent stop' to terminate the services.")

            # Restore terminal state
            if os.name != 'nt':
                try:
                    if os.path.exists('/tmp/smart_agent_stty_settings.txt'):
                        with open('/tmp/smart_agent_stty_settings.txt', 'r') as f:
                            stty_settings = f.read().strip()
                            os.system(f'stty {stty_settings}')
                        os.remove('/tmp/smart_agent_stty_settings.txt')
                except Exception:
                    # If restoring fails, use a generic reset
                    os.system('stty sane')

            return
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        # Clean up on error
        all_processes = tool_processes or []
        if proxy_process:
            all_processes.append(proxy_process)
        # Terminate all processes
        for process in all_processes:
            if process and process.pid:
                try:
                    if os.name == 'nt':  # Windows
                        subprocess.run(
                            ["taskkill", "/F", "/PID", str(process.pid)],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            check=False
                        )
                    else:  # Unix-like
                        os.kill(process.pid, signal.SIGTERM)
                except Exception as e:
                    print(f"Error terminating process {process.pid}: {e}")

        # Restore terminal state
        if os.name != 'nt':
            try:
                if os.path.exists('/tmp/smart_agent_stty_settings.txt'):
                    with open('/tmp/smart_agent_stty_settings.txt', 'r') as f:
                        stty_settings = f.read().strip()
                        os.system(f'stty {stty_settings}')
                    os.remove('/tmp/smart_agent_stty_settings.txt')
            except Exception:
                # If restoring fails, use a generic reset
                os.system('stty sane')


@click.command()
@click.option(
    "--config",
    default=None,
    help="Path to configuration file",
)
def stop(config):
    """
    Stop all running services.

    Args:
        config: Path to config file
    """
    print("Stopping tool services...")

    # Save terminal state
    if os.name != 'nt':
        try:
            # Save terminal settings
            os.system('stty -g > /tmp/smart_agent_stty_settings.txt')
        except Exception:
            pass

    # Load the configuration to find all registered tools
    if config:
        config_manager = ConfigManager(config_file=config)
    else:
        config_manager = ConfigManager()

    all_tools = []
    tools_config = config_manager.get_tools_config()
    if tools_config:
        all_tools = list(tools_config.keys())

    # First, find all tool-specific processes
    tool_processes = {}
    python_processes = []

    try:
        if platform.system() != "Windows":
            # Use ps on Unix-like systems to get all processes
            result = subprocess.run(
                ["ps", "-ef"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            for line in result.stdout.strip().split('\n'):
                # Check for UV tool processes
                for tool_id in all_tools:
                    tool_name = tool_id.replace("_", "-")
                    if tool_name in line and "uvx" in line:
                        parts = line.split()
                        if len(parts) > 1:
                            try:
                                pid = int(parts[1])
                                ppid = int(parts[2])  # parent PID
                                if tool_id not in tool_processes:
                                    tool_processes[tool_id] = []
                                tool_processes[tool_id].append((pid, ppid, "UV"))
                            except (ValueError, IndexError):
                                pass

                # Check for Python processes related to our tools
                if "Python" in line:
                    for tool_id in all_tools:
                        tool_name = tool_id.replace("_", "-")
                        if tool_name in line:
                            parts = line.split()
                            if len(parts) > 1:
                                try:
                                    pid = int(parts[1])
                                    ppid = int(parts[2])  # parent PID
                                    python_processes.append((pid, ppid, tool_id))
                                except (ValueError, IndexError):
                                    pass

                # Also check for supergateway processes
                if "supergateway" in line:
                    parts = line.split()
                    if len(parts) > 1:
                        try:
                            pid = int(parts[1])
                            ppid = int(parts[2])  # parent PID
                            for tool_id in all_tools:
                                tool_name = tool_id.replace("_", "-")
                                if tool_name in line:
                                    if tool_id not in tool_processes:
                                        tool_processes[tool_id] = []
                                    tool_processes[tool_id].append((pid, ppid, "Gateway"))
                        except (ValueError, IndexError):
                            pass
        else:
            # Windows would need a different approach with tasklist
            print("Process tracking on Windows is limited. Some processes may remain.")

        # Match Python processes to their tool parents
        for pid, ppid, tool_id in python_processes:
            for t_id, processes in tool_processes.items():
                for proc_pid, _, _ in processes:
                    if ppid == proc_pid:
                        if t_id not in tool_processes:
                            tool_processes[t_id] = []
                        tool_processes[t_id].append((pid, ppid, "Python"))

        # Now terminate all found processes by tool
        terminated_count = 0
        for tool_id, processes in tool_processes.items():
            if processes:
                print(f"Stopping {tool_id} ({len(processes)} processes)")
                for pid, ppid, proc_type in processes:
                    try:
                        if os.name == 'nt':  # Windows
                            subprocess.run(
                                ["taskkill", "/F", "/PID", str(pid)],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                check=False
                            )
                        else:  # Unix-like
                            os.kill(pid, signal.SIGTERM)
                            # Fall back to SIGKILL if needed for hard-to-kill processes
                            try:
                                # Check if process still exists after a short delay
                                time.sleep(0.1)
                                os.kill(pid, 0)  # This will raise an error if process doesn't exist
                                # Process still exists, use SIGKILL
                                os.kill(pid, signal.SIGKILL)
                            except OSError:
                                # Process already gone, good
                                pass

                        print(f"  Stopped {proc_type} process with PID {pid}")
                        terminated_count += 1
                    except (ProcessLookupError, OSError) as e:
                        print(f"  Process {pid} not found: {e}")
    except Exception as e:
        print(f"Error finding and stopping tool processes: {e}")

    # Get the main PID file path
    pid_file = os.path.join(os.path.expanduser("~"), ".smart_agent_pids")

    # Find and collect all tool-specific PID files
    tool_pid_files = {}
    home_dir = os.path.expanduser("~")
    for filename in os.listdir(home_dir):
        if filename.startswith(".smart_agent_") and filename.endswith("_pid"):
            tool_id = filename.replace(".smart_agent_", "").replace("_pid", "")
            tool_pid_files[tool_id] = os.path.join(home_dir, filename)

    # Also look for supergateway processes running Docker commands
    # This is needed for Docker tools that are run with --rm flag
    try:
        # Get a list of all running processes
        if os.name == 'nt':  # Windows
            # Windows implementation would go here
            pass
        else:  # Unix-like
            # Get all processes with their command lines
            result = subprocess.run(
                ["ps", "-eo", "pid,command"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if "supergateway" in line and "docker run" in line:
                        # This is a Docker-based tool running through supergateway
                        parts = line.strip().split()
                        if len(parts) > 1:
                            try:
                                pid = int(parts[0])

                                # Try to identify which tool this is
                                cmd = line.strip()
                                tool_name = "Docker tool"

                                # Check if this matches any of our configured Docker tools
                                for tool_id, tool_config in config_manager.get_tools_config().items():
                                    if tool_config.get("enabled", False) and tool_config.get("type") == "docker":
                                        container_image = tool_config.get("container_image", "") or tool_config.get("image", "")
                                        if container_image and container_image in cmd:
                                            tool_name = tool_id
                                            break

                                        # Also check for the image name without registry
                                        if container_image:
                                            image_parts = container_image.split("/")
                                            if len(image_parts) > 0:
                                                image_name = image_parts[-1].split(":")[0]  # Get the name without the tag
                                                if image_name in cmd:
                                                    tool_name = tool_id
                                                    break

                                print(f"Found {tool_name} supergateway process with PID {pid}")

                                # Kill the process
                                os.kill(pid, signal.SIGTERM)
                                print(f"Stopped {tool_name} supergateway process with PID {pid}")

                                # Give it a moment to shut down
                                time.sleep(0.5)

                                # Check if it's still running and use SIGKILL if needed
                                try:
                                    os.kill(pid, 0)  # This will raise an error if process doesn't exist
                                    # Process still exists, use SIGKILL
                                    os.kill(pid, signal.SIGKILL)
                                    print(f"Forcefully stopped {tool_name} supergateway process with PID {pid}")
                                except OSError:
                                    # Process already gone, good
                                    pass
                            except (ValueError, OSError) as e:
                                print(f"Error stopping Docker supergateway process: {e}")
    except Exception as e:
        print(f"Error finding and stopping Docker supergateway processes: {e}")

    # Process running tools using tool-specific PID files
    if tool_pid_files:
        for tool_id, pid_file_path in tool_pid_files.items():
            try:
                with open(pid_file_path, "r") as f:
                    pid = int(f.read().strip())

                try:
                    # Try to terminate the process
                    if os.name == 'nt':  # Windows
                        subprocess.run(
                            ["taskkill", "/F", "/PID", str(pid)],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            check=False
                        )
                    else:  # Unix-like
                        os.kill(pid, signal.SIGTERM)

                    print(f"Stopped {tool_id} process with PID {pid}")

                    # Remove the PID file
                    os.remove(pid_file_path)
                except (ProcessLookupError, OSError):
                    # Process already gone
                    os.remove(pid_file_path)
                    pass
            except Exception as e:
                print(f"Error stopping {tool_id}: {e}")

    # Check if the main PID file exists
    if os.path.exists(pid_file):
        # Read the PIDs from the file
        pids = []
        try:
            with open(pid_file, "r") as f:
                pids = [int(line.strip()) for line in f.readlines() if line.strip()]

            # Terminate each process
            for pid in pids:
                try:
                    # Try to terminate the process
                    if os.name == 'nt':  # Windows
                        try:
                            subprocess.run(
                                ["taskkill", "/F", "/PID", str(pid)],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                check=False
                            )
                            print(f"Stopped process with PID {pid}")
                        except Exception:
                            pass
                    else:  # Unix-like
                        try:
                            os.kill(pid, signal.SIGTERM)
                            print(f"Stopped process with PID {pid}")
                        except (ProcessLookupError, OSError):
                            pass

                except:
                    # Process may not exist anymore
                    pass

            # Delete the PID file
            os.remove(pid_file)
        except Exception as e:
            print(f"Error reading PID file: {e}")

    # Stop LiteLLM proxy service
    print("Stopping LiteLLM proxy service...")
    try:
        # Stop the Docker container
        result = subprocess.run(
            ["docker", "stop", "smart-agent-litellm-proxy"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            print("Stopped LiteLLM proxy Docker container")

            # Also remove the container
            subprocess.run(
                ["docker", "rm", "-f", "smart-agent-litellm-proxy"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        else:
            # Check if process is running
            litellm_pid_file = os.path.join(os.path.expanduser("~"), ".litellm_proxy_pid")
            if os.path.exists(litellm_pid_file):
                try:
                    with open(litellm_pid_file, "r") as f:
                        pid = int(f.read().strip())

                    # Try to terminate the process
                    if os.name == 'nt':  # Windows
                        subprocess.run(
                            ["taskkill", "/F", "/PID", str(pid)],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            check=False
                        )
                    else:  # Unix-like
                        os.kill(pid, signal.SIGTERM)

                    os.remove(litellm_pid_file)
                    print(f"Stopped LiteLLM proxy process with PID {pid}")
                except Exception:
                    print("No LiteLLM proxy process found.")
            else:
                print("No LiteLLM proxy process found.")
    except Exception as e:
        print(f"Error stopping LiteLLM proxy: {e}")

    print("All requested services stopped.")

    # Clean up Docker containers
    try:
        # List all running Docker containers with the smart-agent prefix
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", "name=smart-agent-", "--format", "{{.Names}}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

        container_names = [name for name in result.stdout.strip().split('\n') if name]

        if container_names:
            print(f"Stopping {len(container_names)} Docker containers...")
            for container in container_names:
                try:
                    subprocess.run(
                        ["docker", "stop", container],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        check=False,
                    )
                    subprocess.run(
                        ["docker", "rm", "-f", container],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        check=False,
                    )
                    print(f"Stopped and removed Docker container: {container}")
                except Exception as e:
                    print(f"Error stopping container {container}: {e}")

            print("All Docker containers stopped and removed.")
        else:
            print("No Docker containers found.")

        # Find and stop Docker containers launched by tools
        print("Checking for tool-specific Docker containers...")
        tool_containers_found = False
        for tool_id, tool_config in config_manager.get_tools_config().items():
            if tool_config.get("type") == "docker":
                container_image = tool_config.get("container_image", "") or tool_config.get("image", "")
                if container_image:
                    # Extract the image name without the tag
                    image_name = container_image.split("/")[-1].split(":")[0]

                    # Find containers using this image
                    try:
                        result = subprocess.run(
                            ["docker", "ps", "--filter", f"ancestor={container_image}", "--format", "{{.ID}}"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            check=False,
                        )

                        if result.returncode == 0 and result.stdout.strip():
                            container_ids = result.stdout.strip().split('\n')
                            for container_id in container_ids:
                                if container_id.strip():
                                    tool_containers_found = True
                                    print(f"Stopping Docker container for {tool_id} (ID: {container_id})")
                                    subprocess.run(
                                        ["docker", "stop", container_id],
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE,
                                        check=False,
                                    )
                                    subprocess.run(
                                        ["docker", "rm", "-f", container_id],
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE,
                                        check=False,
                                    )

                        # Also try to find containers by image name without registry
                        result = subprocess.run(
                            ["docker", "ps", "--filter", f"ancestor={image_name}", "--format", "{{.ID}}"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            check=False,
                        )

                        if result.returncode == 0 and result.stdout.strip():
                            container_ids = result.stdout.strip().split('\n')
                            for container_id in container_ids:
                                if container_id.strip():
                                    tool_containers_found = True
                                    print(f"Stopping Docker container for {tool_id} (ID: {container_id})")
                                    subprocess.run(
                                        ["docker", "stop", container_id],
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE,
                                        check=False,
                                    )
                                    subprocess.run(
                                        ["docker", "rm", "-f", container_id],
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE,
                                        check=False,
                                    )
                    except Exception as e:
                        print(f"Error stopping Docker container for {tool_id}: {e}")

        if not tool_containers_found:
            print("No tool-specific Docker containers found.")
    except Exception as e:
        print(f"Error stopping Docker containers: {e}")

    # Verify all processes are actually stopped
    print("Verifying all processes are stopped...")
    try:
        remaining_processes = []
        for tool_id in all_tools:
            tool_name = tool_id.replace("_", "-")
            # Check if any processes still exist for this tool
            if platform.system() != "Windows":
                result = subprocess.run(
                    ["pgrep", "-f", tool_name],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                if result.returncode == 0:
                    pids = [int(pid.strip()) for pid in result.stdout.split('\n') if pid.strip()]
                    for pid in pids:
                        # Double-check it's really our tool process
                        # This prevents false positives from the verification command itself
                        verify = subprocess.run(
                            ["ps", "-p", str(pid), "-o", "command="],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            check=False,
                        )
                        if verify.returncode == 0 and tool_name in verify.stdout:
                            remaining_processes.append((pid, tool_id))

        if remaining_processes:
            print(f"Warning: {len(remaining_processes)} processes still running. Forcefully terminating...")
            for pid, tool_id in remaining_processes:
                try:
                    if os.name == 'nt':  # Windows
                        subprocess.run(
                            ["taskkill", "/F", "/PID", str(pid)],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            check=False
                        )
                    else:  # Unix-like
                        # Use SIGKILL for forceful termination
                        os.kill(pid, signal.SIGKILL)
                    print(f"Forcefully terminated {tool_id} process with PID {pid}")
                except (ProcessLookupError, OSError) as e:
                    print(f"Could not terminate process {pid}: {e}")
        else:
            print("All processes successfully stopped.")
    except Exception as e:
        print(f"Error verifying process termination: {e}")

    # Restore terminal state
    if os.name != 'nt':
        try:
            if os.path.exists('/tmp/smart_agent_stty_settings.txt'):
                with open('/tmp/smart_agent_stty_settings.txt', 'r') as f:
                    stty_settings = f.read().strip()
                    os.system(f'stty {stty_settings}')
                os.remove('/tmp/smart_agent_stty_settings.txt')
        except Exception:
            # If restoring fails, use a generic reset
            os.system('stty sane')

    print("All services stopped successfully.")


@click.command()
@click.option("--config", help="Path to configuration file")
def chat(config):
    """Start a chat session with Smart Agent."""
    config_manager = ConfigManager(config)

    # Check if services need to be started
    print("Starting chat session. Make sure you've already run 'smart-agent start' to launch required services.")

    # Start chat session
    start_chat(config_manager)


@click.command()
@click.option(
    "--quick",
    is_flag=True,
    help="Quick setup: just copy example files without interactive prompts",
)
@click.option("--config", is_flag=True, help="Only set up config.yaml")
@click.option("--tools", is_flag=True, help="Only set up tools.yaml")
@click.option("--litellm", is_flag=True, help="Only set up litellm_config.yaml")
@click.option(
    "--all",
    is_flag=True,
    help="Set up all configuration files (equivalent to default behavior)",
)
def setup(quick, config, tools, litellm, all):
    """Set up the environment for Smart Agent through an interactive process."""
    print("Welcome to Smart Agent Setup!")

    # Determine which configs to set up
    setup_all = all or not (config or tools or litellm)
    if setup_all:
        print(
            "This wizard will guide you through configuring your Smart Agent environment.\n"
        )
    else:
        configs_to_setup = []
        if config:
            configs_to_setup.append("config.yaml")
        if tools:
            configs_to_setup.append("tools.yaml")
        if litellm:
            configs_to_setup.append("litellm_config.yaml")
        print(f"Setting up: {', '.join(configs_to_setup)}\n")

    # Create config directory if it doesn't exist
    if not os.path.exists("config"):
        os.makedirs("config")
        print("Created config directory.")

    # Check for example files in current directory first
    config_example_path = "config/config.yaml.example"
    tools_example_path = "config/tools.yaml.example"
    litellm_example_path = "config/litellm_config.yaml.example"

    # If not found in current directory, try to find them in the package installation
    if not os.path.exists(config_example_path) or not os.path.exists(tools_example_path):
        import importlib.resources as pkg_resources
        try:
            # Try to get the package installation path
            from smart_agent import __path__ as package_path
            package_config_dir = os.path.join(package_path[0], "config")

            # Update paths to use package installation
            if os.path.exists(package_config_dir):
                if not os.path.exists(config_example_path) and os.path.exists(os.path.join(package_config_dir, "config.yaml.example")):
                    config_example_path = os.path.join(package_config_dir, "config.yaml.example")
                if not os.path.exists(tools_example_path) and os.path.exists(os.path.join(package_config_dir, "tools.yaml.example")):
                    tools_example_path = os.path.join(package_config_dir, "tools.yaml.example")
                if not os.path.exists(litellm_example_path) and os.path.exists(os.path.join(package_config_dir, "litellm_config.yaml.example")):
                    litellm_example_path = os.path.join(package_config_dir, "litellm_config.yaml.example")
        except (ImportError, ModuleNotFoundError):
            # If we can't find the package, continue with local paths
            pass

    # Check if example files exist at the determined paths
    config_example = os.path.exists(config_example_path)
    tools_example = os.path.exists(tools_example_path)
    litellm_example = os.path.exists(litellm_example_path)

    if not config_example or not tools_example:
        print("Error: Example configuration files not found.")
        print("Please ensure the following files exist:")
        if not config_example:
            print(f"- {config_example_path}")
        if not tools_example:
            print(f"- {tools_example_path}")
        sys.exit(1)

    # Quick setup option - just copy the example files
    if quick:
        print("Performing quick setup (copying example files)...")

        # Copy config.yaml if needed
        if (setup_all or config) and not os.path.exists("config/config.yaml"):
            shutil.copy(config_example_path, "config/config.yaml")
            print("✓ Created config/config.yaml from example")
        elif os.path.exists("config/config.yaml"):
            print("! config/config.yaml already exists, skipping")

        # Copy tools.yaml if needed
        if (setup_all or tools) and not os.path.exists("config/tools.yaml"):
            shutil.copy(tools_example_path, "config/tools.yaml")
            print("✓ Created config/tools.yaml from example")
        elif os.path.exists("config/tools.yaml"):
            print("! config/tools.yaml already exists, skipping")

        # Copy litellm_config.yaml if needed
        if (
            (setup_all or litellm)
            and litellm_example
            and not os.path.exists("config/litellm_config.yaml")
        ):
            shutil.copy(litellm_example_path, "config/litellm_config.yaml")
            print("✓ Created config/litellm_config.yaml from example")
        elif os.path.exists("config/litellm_config.yaml"):
            print("! config/litellm_config.yaml already exists, skipping")

        # Create storage directories based on tools.yaml
        if os.path.exists("config/tools.yaml"):
            with open("config/tools.yaml", "r") as f:
                tools_yaml = yaml.safe_load(f)

            print("\n===== CREATING STORAGE DIRECTORIES =====")
            for tool_id, tool_config in tools_yaml.get("tools", {}).items():
                if tool_config.get("enabled", True) and "storage_path" in tool_config:
                    storage_path = tool_config["storage_path"]

                    # Convert relative paths to absolute paths
                    if not os.path.isabs(storage_path):
                        # Use a storage directory in the current working directory
                        abs_storage_path = os.path.abspath(
                            os.path.join(os.getcwd(), storage_path)
                        )
                        print(
                            f"⚠️ Converting relative path to absolute: {storage_path} -> {abs_storage_path}"
                        )

                        # Update the file with absolute path
                        tools_yaml["tools"][tool_id]["storage_path"] = abs_storage_path
                        storage_path = abs_storage_path

                        # Save the updated tools.yaml
                        with open("config/tools.yaml", "w") as f:
                            yaml.dump(tools_yaml, f, default_flow_style=False)

                    if not os.path.exists(storage_path):
                        os.makedirs(storage_path, exist_ok=True)
                        print(f"✓ Created storage directory: {storage_path}")

        print("\n===== QUICK SETUP COMPLETE =====")
        print("You can now run Smart Agent using:")
        print("  smart-agent start                # Start all services")
        print("  smart-agent chat                 # Start chat session")
        return

    # Get existing models from current config if it exists
    existing_models = []
    if os.path.exists("config/litellm_config.yaml"):
        with open("config/litellm_config.yaml", "r") as f:
            litellm_data = yaml.safe_load(f)
            existing_models = [
                model["model_name"]
                for model in litellm_data.get("model_list", [])
            ]

    # Extract example models from the example file
    example_models = []
    if os.path.exists(litellm_example_path):
        try:
            with open(litellm_example_path, 'r') as f:
                litellm_example = yaml.safe_load(f) or {}
                # Extract unique model names from example file
                for model in litellm_example.get("model_list", []):
                    model_name = model.get("model_name")
                    if model_name and model_name not in example_models:
                        example_models.append(model_name)
        except Exception as e:
            print(f"Warning: Error parsing litellm_config.yaml.example: {e}")

    # If we have existing models, use those
    if existing_models:
        available_models = existing_models
    # Otherwise, if we have models from example, prompt user to select from those
    elif not existing_models and example_models:
        # Present numbered options to the user
        print("\nNo models configured. Select a model to use (you can change this later):")

        for idx, model in enumerate(example_models):
            print(f"{idx+1}. {model}")
        print(f"{len(example_models) + 1}. Custom (enter your own)")

        print("\nYou'll need to edit config/litellm_config.yaml later to add your API keys.")

        while True:
            selection = input("\nSelect model [1]: ").strip()

            # Default to first option if nothing entered
            if not selection:
                selection = "1"

            # Check if selection is a valid number
            if selection.isdigit():
                option = int(selection)
                if 1 <= option <= len(example_models):
                    available_models = [example_models[option - 1]]
                    break
                elif option == len(example_models) + 1:
                    custom_model = input("Enter model name: ").strip()
                    if custom_model:
                        available_models = [custom_model]
                        break

            print("Invalid selection. Please try again.")
    # Fallback if no models at all
    else:
        print("Warning: Could not find any model options. Using a placeholder.")
        available_models = ["model-placeholder"]

    # Start by setting up LiteLLM first as it's a dependency for config.yaml
    if setup_all or litellm:
        print("\n===== LITELLM PROXY CONFIGURATION =====")

        # Check if LiteLLM config already exists and use it as base
        if os.path.exists("config/litellm_config.yaml"):
            print("Found existing litellm_config.yaml, using as default...")
            with open("config/litellm_config.yaml", "r") as f:
                litellm_config = yaml.safe_load(f)
        elif litellm_example:
            # Load default LiteLLM config from example
            with open(litellm_example_path, "r") as f:
                litellm_config = yaml.safe_load(f)
                print("Loaded default LiteLLM configuration from example file.")
        else:
            # Generate basic LiteLLM config
            litellm_config = {
                "model_list": [],
                "server": {"port": 4000, "host": "0.0.0.0"},
                "litellm_settings": {
                    "drop_params": True,
                    "modify_params": True,
                    "num_retries": 3,
                },
            }
            print("Created basic LiteLLM configuration.")

        # Ask user if they want to customize LiteLLM config
        customize_litellm = (
            input(
                "\nDo you want to customize the LiteLLM configuration? [y/N]: "
            )
            .strip()
            .lower()
            == "y"
        )

        if customize_litellm:
            # Show current models
            print("\nCurrent models in configuration:")
            for idx, model_entry in enumerate(litellm_config.get("model_list", [])):
                model_name = model_entry.get("model_name")
                provider = model_entry.get("litellm_params", {}).get("model", "").split("/")[0] if "/" in model_entry.get("litellm_params", {}).get("model", "") else "unknown"
                print(f"{idx+1}. {model_name} ({provider})")

            # Add models option
            add_models = (
                input("\nWould you like to add a new model? [y/N]: ").strip().lower()
                == "y"
            )

            while add_models:
                # Show provider options
                provider_options = [
                    ("openai", "OpenAI (requires API key)"),
                    ("anthropic", "Anthropic (requires API key)"),
                    ("azure", "Azure OpenAI (requires API key, endpoint, and deployment)"),
                    ("bedrock", "AWS Bedrock (requires AWS credentials)"),
                ]

                print("\nSelect API provider:")
                for idx, (provider_id, provider_name) in enumerate(provider_options):
                    print(f"{idx+1}. {provider_name}")

                # Get provider selection
                while True:
                    provider_selection = input("Provider [1]: ").strip() or "1"
                    if provider_selection.isdigit():
                        option = int(provider_selection)
                        if 1 <= option <= len(provider_options):
                            selected_provider = provider_options[option - 1][0]
                            break
                        print("Invalid selection. Please try again.")

                # Get model name
                model_name = input(f"\nEnter model name (e.g., gpt-4o for OpenAI): ").strip()
                if not model_name:
                    print("No model name provided, skipping model addition.")
                else:
                    # Create model config based on provider
                    new_model = {"model_name": model_name, "litellm_params": {}}

                    if selected_provider == "openai":
                        new_model["litellm_params"]["model"] = f"openai/{model_name}"
                        api_key = input("Enter OpenAI API key (leave empty to set later): ").strip()
                        new_model["litellm_params"]["api_key"] = api_key or "api_key"

                    elif selected_provider == "anthropic":
                        new_model["litellm_params"]["model"] = f"anthropic/{model_name}"
                        api_key = input("Enter Anthropic API key (leave empty to set later): ").strip()
                        new_model["litellm_params"]["api_key"] = api_key or "api_key"

                    elif selected_provider == "azure":
                        deployment_name = input("Enter Azure deployment name (leave empty to use model name): ").strip() or model_name
                        new_model["litellm_params"]["model"] = f"azure/{deployment_name}"

                        api_base = input("Enter Azure endpoint URL (leave empty to set later): ").strip()
                        new_model["litellm_params"]["api_base"] = api_base or "api_base"

                        api_key = input("Enter Azure API key (leave empty to set later): ").strip()
                        new_model["litellm_params"]["api_key"] = api_key or "api_key"

                        api_version = input("Enter Azure API version (leave empty for default): ").strip()
                        if api_version:
                            new_model["litellm_params"]["api_version"] = api_version

                    elif selected_provider == "bedrock":
                        new_model["litellm_params"]["model"] = f"bedrock/{model_name}"

                        aws_access_key = input("Enter AWS access key ID (leave empty to set later): ").strip()
                        new_model["litellm_params"]["aws_access_key_id"] = aws_access_key or "aws_access_key_id"

                        aws_secret_key = input("Enter AWS secret access key (leave empty to set later): ").strip()
                        new_model["litellm_params"]["aws_secret_access_key"] = aws_secret_key or "aws_secret_access_key"

                        aws_region = input("Enter AWS region (leave empty to set later): ").strip()
                        new_model["litellm_params"]["aws_region_name"] = aws_region or "aws_region"

                    # Add the model to the config
                    if "model_list" not in litellm_config:
                        litellm_config["model_list"] = []

                    litellm_config["model_list"].append(new_model)
                    print(f"✓ Added {model_name} ({selected_provider}) to configuration")

                # Ask if user wants to add another model
                add_models = input("\nAdd another model? [y/N]: ").strip().lower() == "y"

            # Remove models option
            remove_models = (
                input("\nRemove any models? [y/N]: ").strip().lower()
                == "y"
            )
            if remove_models and litellm_config.get("model_list"):
                # Only allow removal if there would be at least one model left
                if len(litellm_config["model_list"]) > 1:
                    print("\nSelect models to remove:")
                    models_to_remove = []

                    for idx, model_entry in enumerate(litellm_config["model_list"]):
                        model_name = model_entry.get("model_name")
                        remove = (
                            input(f"Remove {model_name}? [y/N]: ").strip().lower()
                            == "y"
                        )
                        if remove:
                            models_to_remove.append(idx)

                    # Remove models in reverse order to avoid index issues
                    for idx in sorted(models_to_remove, reverse=True):
                        if (
                            len(litellm_config["model_list"]) > 1
                        ):  # Ensure at least one model remains
                            removed_model = litellm_config["model_list"].pop(idx)
                            print(f"✓ Removed {removed_model.get('model_name')}")

        # Write LiteLLM config
        with open("config/litellm_config.yaml", "w") as f:
            yaml.dump(litellm_config, f, default_flow_style=False)
        print("✓ Updated config/litellm_config.yaml")

        # Now we have litellm_config.yaml, continue with main config

    # Create config.yaml if needed
    if setup_all or config:
        print("\n===== MAIN CONFIGURATION =====")

        # Load existing config or create new one
        if os.path.exists("config/config.yaml"):
            print("Found existing config.yaml, using as default...")
            with open("config/config.yaml", "r") as f:
                config_data = yaml.safe_load(f)
        elif config_example:
            with open(config_example_path, "r") as f:
                config_data = yaml.safe_load(f)
                print("Loaded default configuration from example file.")
        else:
            # Start with minimal config
            config_data = {
                "llm": {
                    "model": None,  # Will be set based on user selection
                    "temperature": 0.7,
                },
                "logging": {
                    "level": "INFO",
                    "file": None,
                },
                "monitoring": {
                    "langfuse": {
                        "enabled": False,
                        "host": "https://cloud.langfuse.com",
                        "public_key": "",
                        "secret_key": "",
                    }
                },
                "tools_config": "config/tools.yaml",
            }

        # Select model
        print("\nSelect model:")
        for idx, model in enumerate(available_models):
            print(f"{idx + 1}. {model}")

        default_idx = 0

        # Check if there's already a model set
        current_model = config_data.get("llm", {}).get("model")
        if current_model and current_model in available_models:
            default_idx = available_models.index(current_model)

        selected_idx = input(f"\nSelect model [default={default_idx+1}]: ").strip()

        # Handle model selection
        if selected_idx and selected_idx.isdigit():
            selected_idx = int(selected_idx) - 1
            if 0 <= selected_idx < len(available_models):
                selected_model = available_models[selected_idx]
            else:
                print(f"Invalid selection, using default model.")
                selected_model = available_models[default_idx]
        else:
            selected_model = available_models[default_idx]

        print(f"✓ Using {selected_model} as model")

        # Update config with the selected model
        if "llm" not in config_data:
            config_data["llm"] = {}
        config_data["llm"]["model"] = selected_model

        # Write config
        with open("config/config.yaml", "w") as f:
            yaml.dump(config_data, f, default_flow_style=False)
        print("✓ Updated config/config.yaml")

    # Interactive setup - Step 2: Configure tools
    if setup_all or tools:
        print("\n===== TOOL CONFIGURATION =====")

        # Check if tools config already exists and use it as base
        if os.path.exists("config/tools.yaml"):
            print("Found existing tools.yaml, using as default...")
            with open("config/tools.yaml", "r") as f:
                tools_yaml = yaml.safe_load(f)
        else:
            # Load default tools config from example
            with open(tools_example_path, "r") as f:
                tools_yaml = yaml.safe_load(f)

        print("\nFound the following tools in the configuration:")
        for tool_id, tool_config in tools_yaml.get("tools", {}).items():
            enabled = tool_config.get("enabled", True)
            status = "enabled" if enabled else "disabled"
            print(f"- {tool_config.get('name', tool_id)} ({status})")

        customize_tools = (
            input("\nDo you want to customize tool configuration? [y/N]: ")
            .strip()
            .lower()
            == "y"
        )

        if customize_tools:
            for tool_id, tool_config in tools_yaml.get("tools", {}).items():
                current_state = (
                    "enabled" if tool_config.get("enabled", True) else "disabled"
                )
                tool_name = tool_config.get("name", tool_id)

                # Ask user if they want to change the default state
                change_state = (
                    input(f"  Change {tool_name} (currently {current_state})? [y/N]: ")
                    .strip()
                    .lower()
                    == "y"
                )

                if change_state:
                    if current_state == "enabled":
                        enable_tool = (
                            input(f"  Disable {tool_name}? [y/N]: ").strip().lower()
                            != "y"
                        )
                    else:
                        enable_tool = (
                            input(f"  Enable {tool_name}? [y/N]: ").strip().lower()
                            == "y"
                        )

                    tools_yaml["tools"][tool_id]["enabled"] = enable_tool

                    # If enabled, ask for customization of URL
                    if enable_tool and "url" in tool_config:
                        current_url = tool_config["url"]
                        custom_url = input(
                            f"  Custom URL for this tool [default: {current_url}]: "
                        ).strip()
                        if custom_url:
                            tools_yaml["tools"][tool_id]["url"] = custom_url

        # Write tools config
        with open("config/tools.yaml", "w") as f:
            yaml.dump(tools_yaml, f, default_flow_style=False)
        print("✓ Updated config/tools.yaml")

    # Create storage directories
    if setup_all or tools:
        print("\n===== CREATING STORAGE DIRECTORIES =====")

        # Load tools configuration if it exists
        if os.path.exists("config/tools.yaml"):
            with open("config/tools.yaml", "r") as f:
                tools_yaml = yaml.safe_load(f)

            # Extract storage paths from tools.yaml and create them
            for tool_id, tool_config in tools_yaml.get("tools", {}).items():
                if tool_config.get("enabled", True) and "storage_path" in tool_config:
                    storage_path = tool_config["storage_path"]

                    # Convert relative paths to absolute paths
                    if not os.path.isabs(storage_path):
                        # Use a storage directory in the current working directory
                        abs_storage_path = os.path.abspath(
                            os.path.join(os.getcwd(), storage_path)
                        )
                        print(
                            f"⚠️ Converting relative path to absolute: {storage_path} -> {abs_storage_path}"
                        )

                        # Update the file with absolute path
                        tools_yaml["tools"][tool_id]["storage_path"] = abs_storage_path
                        storage_path = abs_storage_path

                        # Save the updated tools.yaml
                        with open("config/tools.yaml", "w") as f:
                            yaml.dump(tools_yaml, f, default_flow_style=False)

                    if not os.path.exists(storage_path):
                        os.makedirs(storage_path, exist_ok=True)
                        print(f"✓ Created storage directory: {storage_path}")

    print("\n===== SETUP COMPLETE =====")
    print("You can now run Smart Agent using:")
    print("  smart-agent chat                 # Start chat session")
    print("  smart-agent start                # Start all services")


def print_version(ctx, param, value):
    """Print the version and exit."""
    if not value or ctx.resilient_parsing:
        return
    print(f"Smart Agent version {__version__}")
    ctx.exit()


@click.group()
@click.option('--version', is_flag=True, callback=print_version,
              expose_value=False, is_eager=True,
              help='Show the version and exit.')
def cli():
    """Smart Agent CLI - AI agent with reasoning and tool use capabilities."""
    pass


cli.add_command(chat)
cli.add_command(start)
cli.add_command(stop)
cli.add_command(setup)

@click.command()
@click.option(
    "--config",
    default=None,
    help="Path to configuration file",
)
@click.option("--tools", is_flag=True, help="Restart tool services")
@click.option("--proxy", is_flag=True, help="Restart LiteLLM proxy service")
@click.option("--all", is_flag=True, help="Restart all services (tools and proxy)")
def restart(config, tools, proxy, all):
    """Restart tool and proxy services."""
    # Use the existing stop and start commands
    stop.callback(config=config)
    start.callback(config=config, tools=tools, proxy=proxy, all=all, foreground=False)
    print("Restart complete.")

cli.add_command(restart)


@click.command()
@click.option(
    "--config",
    default=None,
    help="Path to configuration file",
)
def status(config):
    """
    Show the status of all running services.

    Args:
        config: Path to config file
    """
    print("Smart Agent Status")
    print("====================")

    # Load the configuration to find all registered tools
    if config:
        config_manager = ConfigManager(config_file=config)
    else:
        config_manager = ConfigManager()

    # Find all running processes
    running_processes = []
    try:
        if platform.system() != "Windows":
            # Use ps on Unix-like systems to get all processes
            result = subprocess.run(
                ["ps", "-ef"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            for line in result.stdout.strip().split('\n'):
                # Check for Python, UV, or supergateway processes
                if "uvx" in line or "supergateway" in line:
                    parts = line.split()
                    if len(parts) > 1:
                        try:
                            pid = int(parts[1])
                            cmd = ' '.join(parts[8:])
                            running_processes.append((pid, cmd))
                        except (ValueError, IndexError):
                            pass

            # Also check using ps command to get a more complete picture
            ps_cmd = subprocess.run(
                ["ps", "aux"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if ps_cmd.returncode == 0:
                for line in ps_cmd.stdout.strip().split('\n'):
                    if "uvx --from" in line or "supergateway" in line or "docker run" in line:
                        parts = line.strip().split()
                        try:
                            pid = int(parts[1])
                            # Skip if we already found this PID
                            if pid in [p[0] for p in running_processes]:
                                continue
                            cmd = ' '.join(parts[10:])
                            running_processes.append((pid, cmd))
                        except (ValueError, IndexError):
                            pass

            # Specifically look for supergateway processes running Docker commands
            docker_cmd = subprocess.run(
                ["ps", "-eo", "pid,command"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if docker_cmd.returncode == 0:
                for line in docker_cmd.stdout.strip().split('\n'):
                    if "supergateway" in line and "docker run" in line:
                        # This is a Docker-based tool running through supergateway
                        parts = line.strip().split()
                        if len(parts) > 1:
                            try:
                                pid = int(parts[0])
                                # Skip if we already found this PID
                                if pid in [p[0] for p in running_processes]:
                                    continue
                                cmd = line.strip()[len(str(pid)):].strip()
                                running_processes.append((pid, cmd))
                            except (ValueError, IndexError):
                                pass
        else:
            # Windows would need a different approach with tasklist
            print("Process tracking on Windows is limited. Some processes may remain.")

        # Group processes by service
        service_groups = {}
        for pid, cmd in running_processes:
            service_name = None

            # Try to extract service name from command
            # First check for supergateway processes running Docker commands
            if "supergateway" in cmd and "docker run" in cmd:
                # This is a Docker-based tool running through supergateway
                # Try to match with tool configurations
                for tool_id, tool_config in config_manager.get_tools_config().items():
                    if tool_config.get("enabled", False) and tool_config.get("type") == "docker":
                        container_image = tool_config.get("container_image")
                        if container_image:
                            # Extract just the image name without the registry and tag
                            image_parts = container_image.split("/")
                            if len(image_parts) > 0:
                                image_name = image_parts[-1].split(":")[0]  # Get the name without the tag
                                if image_name in cmd:
                                    service_name = tool_id
                                    break
            else:
                # For non-Docker tools, try to match with tool configurations
                for tool_id, tool_config in config_manager.get_tools_config().items():
                    if tool_config.get("enabled", False) and tool_config.get("type") == "uvx":
                        # Get the repository URL
                        repo = tool_config.get("repository", "")
                        if repo:
                            # Extract the tool name from the repository URL
                            tool_name = repo.split("/")[-1]
                            # Remove git+ prefix if present
                            if tool_name.startswith("git+"):
                                tool_name = tool_name[4:]
                            # Remove .git suffix if present
                            if tool_name.endswith(".git"):
                                tool_name = tool_name[:-4]

                            if tool_name in cmd:
                                service_name = tool_id
                                break
            # Add more mappings as needed

            if service_name:
                if service_name not in service_groups:
                    service_groups[service_name] = []
                service_groups[service_name].append(pid)

        # Display running processes grouped by service
        if service_groups:
            print("\nRunning Tool Services:")
            print("-----------------")
            for service, pids in service_groups.items():
                print(f"Tool: {service} (PID {pids[0]})")
        else:
            print("\nNo Smart Agent processes found.")

        # Check Docker containers
        docker_containers = []
        try:
            # First look for containers with the standard smart-agent- prefix
            result = subprocess.run(
                ["docker", "ps", "--filter", "name=smart-agent-", "--format", "{{.Names}} - {{.Status}}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            if result.returncode == 0 and result.stdout.strip():
                for line in result.stdout.strip().split('\n'):
                    if line.strip():
                        docker_containers.append(line.strip())

            # Also look for tool-specific containers like mcp-py-repl
            # Get the list of tool IDs from the configuration
            tools_config = config_manager.get_tools_config()
            for tool_id, tool_config in tools_config.items():
                if tool_config.get("enabled", False) and tool_config.get("type") == "docker":
                    container_image = tool_config.get("container_image", "") or tool_config.get("image", "")
                    if container_image:
                        # Extract the image name without the tag
                        image_name = container_image.split("/")[-1].split(":")[0]

                        # Look for containers using this image
                        try:
                            result = subprocess.run(
                                ["docker", "ps", "--filter", f"ancestor={container_image}", "--format", "{{.ID}} - {{.Names}} - {{.Status}}"],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True,
                                check=False,
                            )

                            if result.returncode == 0 and result.stdout.strip():
                                for line in result.stdout.strip().split('\n'):
                                    if line.strip():
                                        docker_containers.append(f"{tool_id} ({image_name}) - {line.strip()}")
                        except Exception as e:
                            print(f"Error searching for container with image {container_image}: {e}")

                        # Also try to find containers by image name without registry
                        try:
                            result = subprocess.run(
                                ["docker", "ps", "--filter", f"ancestor={image_name}", "--format", "{{.ID}} - {{.Names}} - {{.Status}}"],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True,
                                check=False,
                            )

                            if result.returncode == 0 and result.stdout.strip():
                                for line in result.stdout.strip().split('\n'):
                                    if line.strip():
                                        docker_containers.append(f"{tool_id} ({image_name}) - {line.strip()}")
                        except Exception as e:
                            print(f"Error searching for container with image name {image_name}: {e}")
        except Exception as e:
            print(f"Error checking Docker containers: {e}")

        # Display Docker containers
        if docker_containers:
            print("\nRunning Docker Containers:")
            print("-------------------------")
            for container in docker_containers:
                print(container)
        else:
            print("\nNo Smart Agent Docker containers found.")

        # Count tool-specific Docker containers
        tool_containers = 0
        litellm_containers = 0
        docker_pids = set()  # Track PIDs that are already counted as Docker containers

        for container in docker_containers:
            if "smart-agent-litellm-proxy" in container:
                litellm_containers += 1
            else:
                # Extract PID if this is a supergateway process
                pid_match = None
                if "Running via supergateway (PID " in container:
                    pid_str = container.split("Running via supergateway (PID ")[1].split(")")[0]
                    try:
                        pid_match = int(pid_str)
                        docker_pids.add(pid_match)
                    except ValueError:
                        pass
                tool_containers += 1

        # Count unique services (not individual processes)
        # We only want to count each service once, not every process
        unique_services = len(service_groups)

        # Get a list of all Docker-based tool PIDs
        docker_tool_pids = set()
        docker_tool_ids = set()
        for container in docker_containers:
            if "Running via supergateway (PID " in container:
                try:
                    # Extract the tool ID from the container string
                    tool_id = container.split(" (")[0]
                    docker_tool_ids.add(tool_id)

                    # Extract the PID from the container string
                    pid_str = container.split("Running via supergateway (PID ")[1].split(")")[0]
                    docker_tool_pids.add(int(pid_str))
                except (ValueError, IndexError):
                    pass

        # Count total processes (for informational purposes)
        # But exclude Docker-based tool PIDs that are already counted as containers
        total_processes = 0
        for service, pids in service_groups.items():
            # Skip services that are already counted as Docker containers
            if service in docker_tool_ids:
                continue

            # Count the processes for this service
            for pid in pids:
                if pid not in docker_tool_pids:
                    total_processes += 1

        # Show summary
        if service_groups or docker_containers:
            # Calculate the actual number of tool services (excluding Docker tools counted twice)
            actual_tool_services = unique_services - len(docker_tool_ids)

            print(f"\nStatus: Smart Agent is RUNNING with {total_processes} processes and {len(docker_containers)} containers")
            print(f"({actual_tool_services} tool services, {tool_containers} tool containers, {litellm_containers} LiteLLM proxy).")
        else:
            print("\nStatus: No Smart Agent services are currently running.")

    except Exception as e:
        print(f"Error checking services: {e}")

    # Make sure we don't have duplicate containers with the same name prefix
    unique_containers = {}
    for container in docker_containers:
        name = container.split(" - ")[0]
        # Only keep the most recently started container for each name
        if name not in unique_containers:
            unique_containers[name] = container

    docker_containers = list(unique_containers.values())

cli.add_command(status)


def launch_litellm_proxy(config_manager: ConfigManager) -> Optional[subprocess.Popen]:
    """
    Launch LiteLLM proxy using Docker.

    Args:
        config_manager: Configuration manager

    Returns:
        Subprocess object or None if launch failed
    """
    print("Launching LiteLLM proxy using Docker...")

    # Check if container already exists and is running
    container_name = "smart-agent-litellm-proxy"
    try:
        result = subprocess.run(
            ["docker", "ps", "-q", "-f", f"name={container_name}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

        if result.stdout.strip():
            print(f"LiteLLM proxy container '{container_name}' is already running.")
            # Return an empty process to indicate success
            return subprocess.Popen(["echo", "Reusing existing container"], stdout=subprocess.PIPE)
    except Exception as e:
        print(f"Warning: Error checking for existing LiteLLM proxy container: {str(e)}")

    # Get LiteLLM config path
    try:
        litellm_config_path = config_manager.get_litellm_config_path()
    except Exception as e:
        litellm_config_path = None

    # Get API settings
    api_base_url = config_manager.get_config("api", "base_url") or "http://localhost:4000"
    api_port = 4000

    try:
        from urllib.parse import urlparse
        parsed_url = urlparse(api_base_url)
        if parsed_url.port:
            api_port = parsed_url.port
    except Exception:
        pass  # Use default port

    # Create command
    cmd = [
        "docker",
        "run",
        "-d",  # Run as daemon
        "-p",
        f"{api_port}:{api_port}",
        "--name",
        container_name,
    ]

    # Add volume if we have a config file
    if litellm_config_path:
        # Mount the config file directly to /app/config.yaml as in docker-compose
        cmd.extend([
            "-v",
            f"{litellm_config_path}:/app/config.yaml",
        ])

        # Add image
        cmd.append("ghcr.io/berriai/litellm:litellm_stable_release_branch-stable")

        # Add command line arguments as in docker-compose
        cmd.extend([
            "--config", "/app/config.yaml",
            "--port", str(api_port),
            "--num_workers", "8"
        ])
    else:
        # Add image only if no config file
        cmd.append("ghcr.io/berriai/litellm:litellm_stable_release_branch-stable")

    # Print the command for debugging
    print(f"Launching LiteLLM proxy with command: {' '.join(cmd)}")

    # Run command
    try:
        process = subprocess.Popen(cmd)
        # Save the PID
        if process and process.pid:
            pid_file = os.path.join(os.path.expanduser("~"), ".litellm_proxy_pid")
            with open(pid_file, "w") as f:
                f.write(str(process.pid))
        return process
    except Exception as e:
        print(f"Error launching LiteLLM proxy: {str(e)}")
        return None


def launch_docker_tool(tool_id: str, container_name: str, image: str, port: int) -> subprocess.Popen:
    """
    Launch a Docker tool.

    Args:
        tool_id: The tool ID
        container_name: The container name
        image: The Docker image
        port: The port to use

    Returns:
        The process object for the container
    """
    # Check if a container with this name already exists and remove it
    try:
        # Check if the container exists (both running and stopped containers)
        result = subprocess.run(
            ["docker", "ps", "-a", "-q", "-f", f"name={container_name}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

        if result.stdout.strip():
            # Container exists, stop and remove it first
            container_id = result.stdout.strip()
            print(f"Removing existing Docker container: {container_name}")

            # Stop the container if it's running
            subprocess.run(
                ["docker", "stop", container_id],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            # Remove the container
            subprocess.run(
                ["docker", "rm", "-f", container_id],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
    except Exception as e:
        print(f"Warning: Failed to clean up existing container {container_name}: {e}")

    # Set up port mapping and container name
    container_args = [
        "docker", "run", "-d",
        "--name", container_name,
        "-p", f"{port}:8080",
    ]

    # Add any needed environment variables
    # container_args.extend(["-e", f"KEY=VALUE"])

    # Add the image name
    container_args.append(image)

    # Launch the container
    process = subprocess.Popen(
        container_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Wait a moment for the container to start
    time.sleep(2)

    print(f"Launching Docker container via supergateway: {tool_id}")

    # Use supergateway to run the container
    supergateway_url = f"http://localhost:{port}/sse"
    print(f"{tool_id} available at {supergateway_url}")

    return process


def main():
    """Main entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()


def check_port_in_use(port: int) -> bool:
    """
    Check if a port is already in use.

    Args:
        port: The port number to check

    Returns:
        True if the port is in use, False otherwise
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def find_free_port(start_port: int = 8000) -> int:
    """
    Find a free port starting from start_port.

    Args:
        start_port: The port to start searching from

    Returns:
        A free port number
    """
    port = start_port
    while check_port_in_use(port):
        port += 1
    return port

def is_tool_running(tool_id: str) -> Tuple[bool, List[int]]:
    """
    Check if a tool is already running.

    Args:
        tool_id: The tool ID to check

    Returns:
        Tuple of (is_running, list_of_pids)
    """
    pids = []

    # Check for Docker container
    container_name = f"smart-agent-{tool_id}"
    try:
        result = subprocess.run(
            ["docker", "ps", "-q", "-f", f"name={container_name}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

        if result.stdout.strip():
            # Container is running
            return True, pids
    except Exception:
        pass

    # Check for processes with the tool name
    try:
        if platform.system() != "Windows":
            # Use ps on Unix-like systems
            result = subprocess.run(
                ["ps", "-ef"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            for line in result.stdout.strip().split('\n'):
                # Look for the tool ID in the process command
                if tool_id.replace("_", "-") in line and "supergateway" in line:
                    parts = line.split()
                    if len(parts) > 1:
                        try:
                            pid = int(parts[1])
                            pids.append(pid)
                        except ValueError:
                            continue

            # Also check using ps command to get a more complete picture
            ps_cmd = subprocess.run(
                ["ps", "aux"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if ps_cmd.returncode == 0:
                for line in ps_cmd.stdout.strip().split('\n'):
                    if tool_id.replace("_", "-") in line and ("uvx --from" in line or "supergateway" in line or "Python" in line):
                        parts = line.split()
                        try:
                            pid = int(parts[1])
                            # Skip if we already found this PID
                            if pid in pids:
                                continue
                            pids.append(pid)
                        except (ValueError, IndexError):
                            pass

            # Also check using ps command to get a more complete picture
            ps_cmd = subprocess.run(
                ["ps", "aux"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if ps_cmd.returncode == 0:
                for line in ps_cmd.stdout.strip().split('\n'):
                    if tool_id.replace("_", "-") in line and ("uvx --from" in line or "supergateway" in line or "Python" in line):
                        parts = line.split()
                        try:
                            pid = int(parts[1])
                            # Skip if we already found this PID
                            if pid in pids:
                                continue
                            pids.append(pid)
                        except (ValueError, IndexError):
                            pass
        else:
            # Use tasklist and findstr on Windows
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq node.exe", "/FO", "CSV"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            for line in result.stdout.strip().split('\n')[1:]:  # Skip header
                if tool_id.replace("_", "-") in line:
                    parts = line.split(',')
                    try:
                        pids.append(int(parts[1].strip('"')))
                    except ValueError:
                        continue

            # Also use another approach to find processes by command line
            try:
                find_cmd = subprocess.run(
                    ["wmic", "process", "get", "processid,commandline"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                if find_cmd.returncode == 0:
                    for line in find_cmd.stdout.strip().split('\n')[1:]:
                        tool_name = tool_id.replace("_", "-")
                        if tool_name in line and ("uvx" in line or "supergateway" in line or "Python" in line):
                            # Extract the PID at the end of the line
                            parts = line.strip().split()
                            if parts:
                                try:
                                    pid = int(parts[-1])
                                    if pid not in pids:
                                        pids.append(pid)
                                except ValueError:
                                    pass
            except Exception:
                # WMIC may not be available on all Windows versions
                pass
    except Exception:
        pass

    return len(pids) > 0, pids

def cleanup_existing_tool_processes() -> int:
    """
    Cleanup any existing tool processes that might be running.

    Returns:
        Number of processes cleaned up
    """
    cleaned_count = 0

    # Clean up Docker containers
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", "name=smart-agent-", "--format", "{{.Names}}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

        container_names = []
        if result.stdout.strip():
            container_names = [name for name in result.stdout.strip().split('\n') if name]

        if container_names:
            print(f"Found {len(container_names)} existing Docker containers.")
            for container_name in container_names:
                try:
                    # Remove the container
                    subprocess.run(
                        ["docker", "rm", "-f", container_name],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        check=False,
                    )
                    print(f"Removed Docker container: {container_name}")
                    cleaned_count += 1
                except Exception:
                    pass
    except Exception:
        pass

    # Clean up supergateway processes
    try:
        if platform.system() != "Windows":
            # Use ps and grep on Unix-like systems
            result = subprocess.run(
                ["ps", "-ef"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            pids = []
            for line in result.stdout.strip().split('\n'):
                if "supergateway" in line:
                    parts = line.split()
                    if len(parts) > 1:
                        try:
                            pids.append(int(parts[1]))  # PID is usually the second field
                        except ValueError:
                            continue

            if pids:
                for pid in pids:
                    try:
                        os.kill(pid, signal.SIGTERM)
                        cleaned_count += 1
                    except OSError:
                        pass
        else:
            # Use tasklist and findstr on Windows
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq node.exe", "/FO", "CSV"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            pids = []
            for line in result.stdout.strip().split('\n')[1:]:  # Skip header
                if "supergateway" in line:
                    parts = line.split(',')
                    try:
                        pids.append(int(parts[1].strip('"')))
                    except ValueError:
                        continue

            if pids:
                for pid in pids:
                    try:
                        subprocess.run(
                            ["taskkill", "/F", "/PID", str(pid)],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            check=False
                        )
                        cleaned_count += 1
                    except Exception:
                        pass
    except Exception:
        pass

    return cleaned_count
