#!/usr/bin/env python
"""
CLI interface for Smart Agent.
"""

import os
import sys
import time
import signal
import subprocess
import click
import datetime
import logging
import yaml
import getpass
from typing import Optional, List, Dict, Any
from pathlib import Path
import re
import urllib.parse
import locale
import shutil

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("smart_agent")

# Try to import dotenv for environment variable loading
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from smart_agent.tool_manager import ConfigManager


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

    # Get model configuration
    model_name = config_manager.get_model_name()
    temperature = config_manager.get_model_temperature()

    # Get Langfuse configuration
    langfuse_config = config_manager.get_langfuse_config()
    langfuse_enabled = langfuse_config.get("enabled", False)

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
        from smart_agent.agent import SmartAgent, Agent, OpenAIChatCompletionsModel

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
            # Reset the agent - using SmartAgent wrapper class
            smart_agent = SmartAgent(
                model_name=model_name,
                openai_client=client,
                mcp_servers=mcp_servers,
                system_prompt=PromptGenerator.create_system_prompt(),
            )
            print("Conversation history cleared")
            continue

        # Get assistant response
        print("\nAssistant: ", end="", flush=True)

        try:
            # Use the agent for streaming response
            async def run_agent():
                history = [{"role": "user", "content": user_input}]
                result = await smart_agent.process_message(history)
                async for chunk in result.stream():
                    if chunk.delta and chunk.delta.content:
                        print(chunk.delta.content, end="", flush=True)
                print()  # Add a newline at the end

            # Run the agent in an event loop
            import asyncio

            asyncio.run(run_agent())

            # Log to Langfuse if enabled
            if langfuse_enabled:
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
            print(f"Error: {e}")

    print("\nChat session ended")


def chat(config_manager: ConfigManager):
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

    # Launch each enabled tool
    for tool_id, tool_config in tools_config.items():
        if tool_config.get("enabled", False):
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
                # We'll use tool index to determine port
                tools_list = list(tools_config.keys())
                tool_index = tools_list.index(tool_id)
                port = 8000 + tool_index

            # Launch based on tool type
            tool_type = tool_config.get("type", "").lower()
            
            if tool_type == "uvx":
                print(f"Launching UVX tool: {tool_id}")
                try:
                    # For UVX tools, we need to convert underscores to hyphens
                    # in the executable name (e.g., ddg_mcp -> ddg-mcp)
                    executable_name = tool_id.replace("_", "-")
                    
                    # Get the repository
                    repo = tool_config.get("repository", "")
                    
                    # Construct the launch command
                    tool_cmd = [
                        "npx",
                        "-y",
                        "supergateway",
                        "--port",
                        str(port),
                        "--stdio",
                        f"uvx --from {repo} {executable_name}"
                    ]
                    
                    # Initialize environment variables
                    env = os.environ.copy()
                    
                    # Get the tool environment variables prefix
                    # E.g., DDGMCP_ for ddg_mcp
                    env_prefix = config_manager.get_env_prefix(tool_id)
                    
                    # Set the URL environment variable
                    # E.g., DDGMCP_URL for ddg_mcp
                    env[f"{env_prefix}URL"] = url
                    
                    # Launch the process with nohup to keep it running after parent exits
                    # This approach works better for background mode
                    if os.name != 'nt':  # Not on Windows
                        process = subprocess.Popen(
                            ["nohup"] + tool_cmd,
                            env=env,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            preexec_fn=os.setpgrp  # Creates a new process group, detaching from parent
                        )
                    else:
                        # Windows doesn't have nohup or os.setpgrp
                        process = subprocess.Popen(
                            tool_cmd,
                            env=env,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if hasattr(subprocess, 'CREATE_NEW_PROCESS_GROUP') else 0
                        )
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
                            print(f"Docker container '{container_name}' is already running.")
                            # Return an empty process to indicate success
                            dummy_process = subprocess.Popen(["echo", "Reusing existing container"], stdout=subprocess.PIPE)
                            processes.append(dummy_process)
                            print(f"{tool_id} available at {url}")
                            continue
                    except Exception as e:
                        print(f"Warning: Error checking for existing container: {str(e)}")
                        
                    # Create data directory if it doesn't exist
                    # Use the storage_path from the tool configuration if available,
                    # otherwise use a default path
                    data_dir = tool_config.get("storage_path", os.path.join(os.getcwd(), "storage"))
                    os.makedirs(data_dir, exist_ok=True)
                    
                    # Construct the Docker command
                    # For background mode, we use nohup to ensure the process continues
                    # after the parent exits
                    docker_cmd = [
                        "npx",
                        "-y",
                        "supergateway",
                        "--port",
                        str(port),
                        "--stdio",
                        f"docker run -i --name {container_name} --pull=always -v {data_dir}:/app/data {container_image}"
                    ]
                    
                    print(f"Launching Docker container via supergateway: {tool_id}")
                    
                    # Launch the process with nohup to keep it running after parent exits
                    if os.name != 'nt':  # Not on Windows
                        process = subprocess.Popen(
                            ["nohup"] + docker_cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            preexec_fn=os.setpgrp  # Creates a new process group, detaching from parent
                        )
                    else:
                        # Windows doesn't have nohup or os.setpgrp
                        process = subprocess.Popen(
                            docker_cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if hasattr(subprocess, 'CREATE_NEW_PROCESS_GROUP') else 0
                        )
                    processes.append(process)
                    
                    # Give the container a moment to start and verify it's running
                    time.sleep(2)
                    verify_result = subprocess.run(
                        ["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Names}}"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        check=False,
                    )
                    
                    if verify_result.stdout.strip():
                        print(f"Docker container {container_name} is running successfully.")
                    else:
                        # Check if it exited with an error
                        error_check = subprocess.run(
                            ["docker", "ps", "-a", "--filter", f"name={container_name}", "--format", "{{.Status}}"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            check=False,
                        )
                        if error_check.stdout.strip():
                            print(f"Warning: Docker container {container_name} may have exited: {error_check.stdout.strip()}")
                    
                    print(f"{tool_id} available at {url}")
                except Exception as e:
                    print(f"Failed to launch Docker tool {tool_id}: {str(e)}")
            else:
                print(f"Unknown tool type '{tool_type}' for {tool_id}")

    if processes:
        print("\nAll enabled tools are now running.")
    else:
        print("No tools were launched.")

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
    
    try:
        print("\033[2J\033[H", end="")  # Clear screen
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
            api_port = 4000
            
            try:
                from urllib.parse import urlparse
                parsed_url = urlparse(base_url)
                if parsed_url.port:
                    api_port = parsed_url.port
            except Exception:
                pass  # Use default port
                
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
                terminate_processes(all_processes)
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
            return
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        # Clean up on error
        all_processes = tool_processes or []
        if proxy_process:
            all_processes.append(proxy_process)
        terminate_processes(all_processes)


@click.command()
@click.option(
    "--config",
    default=None,
    help="Path to configuration file",
)
@click.option("--tools", is_flag=True, help="Stop tool services")
@click.option("--proxy", is_flag=True, help="Stop LiteLLM proxy service")
@click.option("--all", is_flag=True, help="Stop all services (tools and proxy)")
@click.option("--background", "-b", is_flag=True, help="Stop background services")
def stop(config, tools, proxy, all, background):
    """
    Stop running services.
    """
    # Check for background services first if requested
    if background:
        stop_background_services()
        return
        
    # If --all is specified, enable both tools and proxy
    if all:
        tools = True
        proxy = True

    # If neither flag is specified, default to stopping all services
    if not tools and not proxy:
        tools = True
        proxy = True

    # Stop tool services
    if tools:
        print("Stopping tool services...")
        # Find and kill tool processes
        try:
            # Find processes with 'supergateway' in command line (our tool wrapper)
            tool_pids = (
                subprocess.check_output(
                    ["pgrep", "-f", "supergateway"], universal_newlines=True
                )
                .strip()
                .split("\n")
            )

            for pid in tool_pids:
                if pid:
                    os.kill(int(pid), signal.SIGTERM)
                    print(f"Stopped tool process with PID {pid}")
        except subprocess.CalledProcessError:
            print("No tool processes found.")

    # Stop LiteLLM proxy
    if proxy:
        print("Stopping LiteLLM proxy service...")
        try:
            # Stop and remove the Docker container
            subprocess.run(
                ["docker", "stop", "smart-agent-litellm-proxy"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            subprocess.run(
                ["docker", "rm", "-f", "smart-agent-litellm-proxy"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            print("Stopped LiteLLM proxy Docker container")

            # Also find any local litellm processes (in case we're not using Docker)
            proxy_pids = (
                subprocess.check_output(
                    ["pgrep", "-f", "litellm"], universal_newlines=True
                )
                .strip()
                .split("\n")
            )

            for pid in proxy_pids:
                if pid:
                    os.kill(int(pid), signal.SIGTERM)
                    print(f"Stopped LiteLLM proxy process with PID {pid}")
        except subprocess.CalledProcessError:
            print("No LiteLLM proxy process found.")
        except Exception as e:
            print(f"Error stopping LiteLLM proxy: {e}")

    print("All requested services stopped.")
    
    # Also check for background services
    pid_file = os.path.join(os.path.expanduser("~"), ".smart_agent_pids")
    if os.path.exists(pid_file):
        print("Also stopping background services...")
        stop_background_services()


def stop_background_services():
    """Helper function to stop services running in the background."""
    # Check for PID file
    pid_file = os.path.join(os.path.expanduser("~"), ".smart_agent_pids")
    pids = []
    
    # First, try to kill any processes listed in the PID file
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r") as f:
                pids = [int(line.strip()) for line in f if line.strip()]
            
            if not pids:
                print("No process IDs found in PID file.")
        except Exception as e:
            print(f"Error reading PID file: {str(e)}")
    
    # Find any additional background processes
    background_pids = []
    try:
        if os.name != 'nt':  # Unix-like systems
            # Check for UVX processes
            uvx_cmd = subprocess.run(
                ["pgrep", "-f", "uvx --from"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if uvx_cmd.returncode == 0:
                background_pids.extend([int(pid) for pid in uvx_cmd.stdout.strip().split('\n') if pid.strip()])
            
            # Check for supergateway processes
            supergateway_cmd = subprocess.run(
                ["pgrep", "-f", "supergateway"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if supergateway_cmd.returncode == 0:
                background_pids.extend([int(pid) for pid in supergateway_cmd.stdout.strip().split('\n') if pid.strip()])
            
            # Use ps to find any missed processes
            ps_cmd = subprocess.run(
                ["ps", "aux"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if ps_cmd.returncode == 0:
                for line in ps_cmd.stdout.strip().split('\n'):
                    if any(tool_id in line for tool_id in ["ddg_mcp", "mcp_think_tool", "python_repl"]):
                        parts = line.split()
                        try:
                            pid = int(parts[1])
                            if pid not in background_pids:
                                background_pids.append(pid)
                        except (ValueError, IndexError):
                            pass
        else:  # Windows
            # On Windows, use tasklist with filtering
            tasklist_cmd = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq python*", "/FO", "CSV"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if tasklist_cmd.returncode == 0:
                for line in tasklist_cmd.stdout.strip().split('\n')[1:]:  # Skip header
                    if any(tool_id in line for tool_id in ["uvx", "supergateway", "ddg_mcp", "mcp_think_tool", "python_repl"]):
                        parts = line.split(',')
                        try:
                            pid = int(parts[1].strip('"'))
                            background_pids.append(pid)
                        except (ValueError, IndexError):
                            pass
    except Exception as e:
        print(f"Error finding background processes: {str(e)}")
    
    # Combine PID lists and remove duplicates
    all_pids = list(set(pids + background_pids))
    
    if not all_pids:
        print("No background services found.")
    else:
        print(f"Stopping {len(all_pids)} background services...")
        
        # Stop each process
        for pid in all_pids:
            try:
                # Check if process exists
                os.kill(pid, 0)  # This will raise an error if process doesn't exist
                # Send terminate signal
                os.kill(pid, signal.SIGTERM)
                print(f"Sent SIGTERM to process {pid}")
            except OSError:
                print(f"Process {pid} not found, may have already terminated.")
    
    # Also stop Docker containers for all tools we might have started
    try:
        # Get list of all containers with 'smart-agent-' prefix
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", "name=smart-agent-", "--format", "{{.Names}}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        
        containers_to_stop = []
        if result.stdout.strip():
            container_names = result.stdout.strip().split('\n')
            for container_name in container_names:
                if container_name:  # Skip empty lines
                    containers_to_stop.append(container_name)
        
        # Also check for tool-specific containers that might not have the standard prefix
        config_manager = ConfigManager()
        all_tools = config_manager.get_all_tools()
        docker_tools = []
        
        # Find all docker-type tools from configuration
        for tool_id, tool_config in all_tools.items():
            if tool_config.get("type") == "docker":
                docker_tools.append(tool_id)
                
        # Search for containers matching each docker tool
        for tool_id in docker_tools:
            tool_result = subprocess.run(
                ["docker", "ps", "-a", "--filter", f"name=smart-agent-{tool_id}", "--format", "{{.Names}}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            if tool_result.stdout.strip():
                for line in tool_result.stdout.split('\n'):
                    if line.strip() and line.strip() not in containers_to_stop:
                        containers_to_stop.append(line.strip())
        
        # Stop all found containers
        if containers_to_stop:
            for container_name in containers_to_stop:
                subprocess.run(
                    ["docker", "stop", container_name],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                print(f"Stopped Docker container: {container_name}")
            print("Stopped Docker containers.")
        else:
            print("No Docker containers found to stop.")
    except Exception as e:
        print(f"Error stopping Docker containers: {str(e)}")
    
    # Remove PID file if it exists
    if os.path.exists(pid_file):
        try:
            os.remove(pid_file)
        except Exception as e:
            print(f"Error removing PID file: {str(e)}")
    
    print("All background services stopped.")


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
        litellm_config_dir = os.path.dirname(os.path.abspath(litellm_config_path))
        litellm_config_filename = os.path.basename(litellm_config_path)
        cmd.extend([
            "-v",
            f"{litellm_config_dir}:/app/config",
            "-e",
            f"CONFIG_FILE=/app/config/{litellm_config_filename}",
        ])
        
    # Add image
    cmd.append("ghcr.io/berriai/litellm:litellm_stable_release_branch-stable")
    
    # Run command
    try:
        process = subprocess.Popen(cmd)
        return process
    except Exception as e:
        print(f"Error launching LiteLLM proxy: {str(e)}")
        return None


@click.command()
@click.option("--config", help="Path to configuration file")
def chat(config):
    """Start a chat session with Smart Agent."""
    config_manager = ConfigManager(config)
    
    # Check if services need to be started
    print("Starting chat session. Make sure you've already run 'smart-agent start' to launch required services.")
    
    # Start chat session
    chat(config_manager)


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


@click.group()
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
    stop.callback(config=config, tools=tools, proxy=proxy, all=all, background=False)
    start.callback(config=config, tools=tools, proxy=proxy, all=all, foreground=False)
    print("Restart complete.")

cli.add_command(restart)


@click.command()
def status():
    """
    Show the status of all Smart Agent services.
    Displays which services are currently running, including tools and the LiteLLM proxy.
    """
    print("Smart Agent Status\n" + "=" * 20)
    
    # Check running processes with pid file first
    pid_file = os.path.join(os.path.expanduser("~"), ".smart_agent_pids")
    running_processes = []
    
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r") as f:
                pids = [int(line.strip()) for line in f if line.strip()]
            for pid in pids:
                try:
                    # Check if process exists by sending signal 0
                    # This doesn't actually send a signal, just checks if process exists
                    os.kill(pid, 0)  # This will raise an error if process doesn't exist
                    # Get process command
                    try:
                        if os.name != 'nt':  # Unix-like systems
                            cmd = subprocess.check_output(
                                ["ps", "-p", str(pid), "-o", "command="],
                                stderr=subprocess.PIPE,
                                text=True
                            ).strip()
                        else:  # Windows
                            cmd = subprocess.check_output(
                                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV"],
                                stderr=subprocess.PIPE,
                                text=True
                            ).split("\n")[1].split(",")[0].strip('"')
                        
                        running_processes.append((pid, cmd))
                    except:
                        running_processes.append((pid, "Unknown"))
                except OSError:
                    # Process doesn't exist
                    pass
        except Exception as e:
            print(f"Error checking processes: {str(e)}")
    
    # Also check for supergateway processes (for detached processes)
    try:
        if os.name != 'nt':  # Unix-like
            # Check for supergateway processes
            supergateway_cmd = subprocess.run(
                ["pgrep", "-f", "supergateway"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if supergateway_cmd.returncode == 0:
                pids = [int(pid) for pid in supergateway_cmd.stdout.strip().split('\n') if pid.strip()]
                
                for pid in pids:
                    # Skip if we already found this PID
                    if any(pid == p[0] for p in running_processes):
                        continue
                        
                    try:
                        cmd = subprocess.check_output(
                            ["ps", "-p", str(pid), "-o", "command="],
                            stderr=subprocess.PIPE,
                            text=True
                        ).strip()
                        running_processes.append((pid, cmd))
                    except:
                        pass
            
            # Also check for uvx processes directly
            uvx_cmd = subprocess.run(
                ["pgrep", "-f", "uvx --from"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if uvx_cmd.returncode == 0:
                pids = [int(pid) for pid in uvx_cmd.stdout.strip().split('\n') if pid.strip()]
                
                for pid in pids:
                    # Skip if we already found this PID
                    if any(pid == p[0] for p in running_processes):
                        continue
                        
                    try:
                        cmd = subprocess.check_output(
                            ["ps", "-p", str(pid), "-o", "command="],
                            stderr=subprocess.PIPE,
                            text=True
                        ).strip()
                        running_processes.append((pid, cmd))
                    except:
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
                    if "uvx --from" in line or "supergateway" in line:
                        parts = line.split()
                        try:
                            pid = int(parts[1])
                            # Skip if we already found this PID
                            if any(pid == p[0] for p in running_processes):
                                continue
                            cmd = ' '.join(parts[10:])
                            running_processes.append((pid, cmd))
                        except (ValueError, IndexError):
                            pass
    except Exception as e:
        print(f"Error checking for tool processes: {str(e)}")
    
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
        
        if result.stdout.strip():
            docker_containers = [line.strip() for line in result.stdout.split('\n') if line.strip()]
            
        # Also check for any specific tool containers that might not have the standard prefix
        config_manager = ConfigManager()
        all_tools = config_manager.get_all_tools()
        docker_tools = []
        
        # Find all docker-type tools from configuration
        for tool_id, tool_config in all_tools.items():
            if tool_config.get("type") == "docker":
                docker_tools.append(tool_id)
                
        # Search for containers matching each docker tool
        for tool_id in docker_tools:
            # Try multiple container name patterns
            container_patterns = [
                f"name=smart-agent-{tool_id}",  # Exact prefixed match
                f"name={tool_id}",              # Exact match of tool_id
                f"name=supergateway-{tool_id}", # Possible supergateway prefix
                f"name=*{tool_id}*"             # Contains tool_id anywhere in name
            ]
            
            for pattern in container_patterns:
                tool_result = subprocess.run(
                    ["docker", "ps", "--filter", pattern, "--format", "{{.Names}} - {{.Status}}"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False,
                )
                
                if tool_result.stdout.strip():
                    for line in tool_result.stdout.split('\n'):
                        if line.strip() and line.strip() not in docker_containers:
                            docker_containers.append(line.strip())
    except Exception as e:
        print(f"Error checking Docker containers: {str(e)}")
    
    # Group processes by service
    service_groups = {}
    for pid, cmd in running_processes:
        # Extract service name from command
        service_name = "Unknown"
        
        # Try to extract tool name from command
        if "uvx --from" in cmd:
            # Extract repository or tool name
            match = re.search(r"uvx --from (\S+) (\S+)", cmd)
            if match:
                repo = match.group(1)
                tool_name = match.group(2)
                if tool_name:
                    service_name = f"Tool: {tool_name}"
                elif repo:
                    # Extract tool name from repository
                    repo_parts = repo.split('/')
                    if len(repo_parts) > 0:
                        tool_name = repo_parts[-1]
                        service_name = f"Tool: {tool_name}"
        elif "supergateway" in cmd:
            # For supergateway processes, try to extract tool info
            if "--stdio" in cmd:
                parts = cmd.split("--stdio")
                if len(parts) > 1:
                    tool_cmd = parts[1].strip()
                    if "uvx" in tool_cmd:
                        # Extract UVX tool name
                        match = re.search(r"uvx --from .+ ([\w-]+)", tool_cmd)
                        if match:
                            service_name = f"Tool: {match.group(1)}"
                    elif "docker" in tool_cmd:
                        # Extract Docker image name
                        match = re.search(r"docker run .+ ([\w\/\.\-\:]+)", tool_cmd)
                        if match:
                            image = match.group(1)
                            # Extract tool name from image
                            image_parts = image.split('/')
                            if len(image_parts) > 0:
                                tool_name = image_parts[-1].split(':')[0]
                                service_name = f"Docker Tool: {tool_name}"
        elif "docker run" in cmd:
            # Extract Docker image name directly
            match = re.search(r"docker run .+ ([\w\/\.\-\:]+)", cmd)
            if match:
                image = match.group(1)
                # Extract tool name from image
                image_parts = image.split('/')
                if len(image_parts) > 0:
                    tool_name = image_parts[-1].split(':')[0]
                    service_name = f"Docker Tool: {tool_name}"
        
        # If we're running with ps aux, the column may be different
        if service_name == "Unknown" and len(cmd.split()) > 3:
            # Try extracting from ps aux format
            for part in cmd.split():
                if "uvx" in part or "supergateway" in part:
                    # Already tried to extract using other methods
                    pass
                elif any(tool_id in part for tool_id in ["ddg_mcp", "mcp_think_tool", "python_repl"]):
                    tool_id = next((tid for tid in ["ddg_mcp", "mcp_think_tool", "python_repl"] if tid in part), None)
                    if tool_id:
                        service_name = f"Tool: {tool_id}"
                        break
        
        # Add to service groups
        if service_name not in service_groups:
            service_groups[service_name] = []
        service_groups[service_name].append(pid)
    
    # Display results
    if service_groups:
        print("\nRunning Tool Services:")
        print("-----------------")
        for service_name, pids in service_groups.items():
            if service_name == "Unknown" and len(pids) == 1:
                print(f"Unknown Process (PID {pids[0]})")
            elif service_name == "Unknown":
                print(f"Unknown Processes ({len(pids)} instances): PIDs {', '.join(str(pid) for pid in pids)}")
            else:
                if len(pids) == 1:
                    print(f"{service_name} (PID {pids[0]})")
                else:
                    print(f"{service_name} ({len(pids)} instances): PIDs {', '.join(str(pid) for pid in pids)}")
    else:
        print("\nNo Smart Agent processes found.")
    
    if docker_containers:
        print("\nRunning Docker Containers:")
        print("-------------------------")
        for container in docker_containers:
            print(container)
    else:
        print("\nNo Smart Agent Docker containers found.")
    
    # Check if any services are running
    if not running_processes and not docker_containers:
        print("\nStatus: No Smart Agent services are currently running.")
    else:
        print(f"\nStatus: Smart Agent is RUNNING with {len(running_processes)} processes and {len(docker_containers)} containers.")


cli.add_command(status)


def main():
    """Main entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
