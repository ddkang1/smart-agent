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
from urllib.parse import urlparse
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
        from agent import Agent, OpenAIChatCompletionsModel

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

        # Create the agent
        agent = Agent(
            name="Assistant",
            instructions=PromptGenerator.create_system_prompt(),
            model=OpenAIChatCompletionsModel(
                model=model_name,
                openai_client=client,
            ),
            mcp_servers=mcp_servers,
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
            # Reset the agent
            agent = Agent(
                name="Assistant",
                instructions=PromptGenerator.create_system_prompt(),
                model=OpenAIChatCompletionsModel(
                    model=model_name,
                    openai_client=client,
                ),
                mcp_servers=mcp_servers,
            )
            print("Conversation history cleared")
            continue

        # Get assistant response
        print("\nAssistant: ", end="", flush=True)

        try:
            # Use the agent for streaming response
            async def run_agent():
                async for chunk in agent.chat(user_input=user_input):
                    if chunk.content:
                        print(chunk.content, end="", flush=True)
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
    Launch tool services.

    Args:
        config_manager: Configuration manager

    Returns:
        List of subprocess objects
    """
    print("Launching tool services...")

    # Get tools configuration
    tool_configs = config_manager.get_tools_config()

    # Launch enabled tools
    processes = []
    for tool_id, tool_config in tool_configs.items():
        # Skip disabled tools
        if not tool_config.get("enabled", True):
            print(f"Tool '{tool_id}' is disabled. Skipping.")
            continue

        # Get configuration values
        tool_name = tool_config.get("name", tool_id)
        tool_url = tool_config.get("url", "")
        launch_cmd = tool_config.get("launch_cmd", "")
        tool_repo = tool_config.get("repository", "")

        # Skip tools with remote URLs (non-localhost)
        if (
            tool_url
            and "localhost" not in tool_url
            and "127.0.0.1" not in tool_url
            and "0.0.0.0" not in tool_url
        ):
            print(f"Tool '{tool_id}' uses a remote URL. No need to launch locally.")
            continue

        # Only launch if we have a launch command
        if not launch_cmd:
            print(f"Tool '{tool_id}' has no launch command. Skipping.")
            continue

        # Create tool storage directory if specified
        storage_path = tool_config.get("storage_path", "")
        storage_dir = storage_path if storage_path else f"{tool_id}_storage"
        os.makedirs(storage_dir, exist_ok=True)

        # Launch tool
        if launch_cmd == "docker":
            # Docker container-based tool
            print(f"Launching Docker tool: {tool_name}")

            # Use supergateway to convert stdio to SSE
            tool_cmd = [
                "npx",
                "-y",
                "supergateway",
                "--stdio",
                f"docker run -i --rm --pull=always -v {os.path.abspath(storage_dir)}:/app/data {tool_repo}",
                "--port",
                str(tool_url.split(":")[-1]),
                "--baseUrl",
                f"http://localhost:{tool_url.split(':')[-1]}",
                "--ssePath",
                "/sse",
                "--messagePath",
                "/message",
            ]

            tool_process = subprocess.Popen(tool_cmd)
            processes.append(tool_process)

            # Set environment variable for URL
            os.environ[f"{config_manager.get_env_prefix(tool_id)}_URL"] = tool_url
            print(f"{tool_name} available at {tool_url}")
        elif launch_cmd == "npx":
            # NPX-based tool
            module_name = tool_config.get("module", tool_id)

            print(f"Launching NPX tool: {tool_name}")

            # Use supergateway to convert stdio to SSE
            tool_cmd = [
                "npx",
                "-y",
                "supergateway",
                "--stdio",
                f"npx {module_name}",
                "--port",
                str(tool_url.split(":")[-1]),
                "--baseUrl",
                f"http://localhost:{tool_url.split(':')[-1]}",
                "--ssePath",
                "/sse",
                "--messagePath",
                "/message",
            ]

            tool_process = subprocess.Popen(tool_cmd)
            processes.append(tool_process)

            # Set environment variable for URL
            os.environ[f"{config_manager.get_env_prefix(tool_id)}_URL"] = tool_url
            print(f"{tool_name} available at {tool_url}")
        elif launch_cmd == "uvx":
            # UVX-based tool (Python package)
            module_name = tool_config.get("module", tool_id.replace("-", "_"))

            print(f"Launching UVX tool: {tool_name}")

            # Use supergateway to convert stdio to SSE
            tool_cmd = [
                "npx",
                "-y",
                "supergateway",
                "--stdio",
                f"uvx --from {tool_repo} {module_name}",
                "--port",
                str(tool_url.split(":")[-1]),
                "--baseUrl",
                f"http://localhost:{tool_url.split(':')[-1]}",
                "--ssePath",
                "/sse",
                "--messagePath",
                "/message",
            ]

            tool_process = subprocess.Popen(tool_cmd)
            processes.append(tool_process)

            # Set environment variable for URL
            os.environ[f"{config_manager.get_env_prefix(tool_id)}_URL"] = tool_url
            print(f"{tool_name} available at {tool_url}")
        else:
            print(f"Unknown launch command '{launch_cmd}' for {tool_name}. Skipping.")
            continue

    print("\nAll enabled tools are now running.")
    return processes


@click.command()
@click.option("--config", help="Path to configuration file")
@click.option("--tools", is_flag=True, help="Start tool services")
@click.option("--proxy", is_flag=True, help="Start LiteLLM proxy service")
@click.option("--all", is_flag=True, help="Start all services (tools and proxy)")
def start(config, tools, proxy, all):
    """Start tool and proxy services."""
    config_manager = ConfigManager(config)
    processes = []

    # If --all is specified, enable both tools and proxy
    if all:
        tools = True
        proxy = True

    # If neither flag is specified, default to starting all services
    if not tools and not proxy:
        tools = True
        proxy = True

    try:
        # Launch tools if requested
        if tools:
            tool_processes = launch_tools(config_manager)
            processes.extend(tool_processes)
            print("Tool services started successfully.")

        # Launch LiteLLM proxy if requested and needed
        if proxy:
            base_url = config_manager.get_config("api", "base_url")
            # Only start proxy if we're using a local URL
            if (
                "localhost" in base_url
                or "127.0.0.1" in base_url
                or "0.0.0.0" in base_url
            ):
                proxy_process = launch_litellm_proxy(config_manager)
                if proxy_process:
                    processes.append(proxy_process)
                    print("LiteLLM proxy started successfully.")
                else:
                    print("Failed to start LiteLLM proxy.")
            else:
                print(f"Skipping LiteLLM proxy - using remote API at {base_url}")

        # Keep the process running until interrupted
        print("\nPress Ctrl+C to stop all services.")
        for process in processes:
            process.wait()

    except KeyboardInterrupt:
        print("\nStopping all services...")
    finally:
        # Clean up processes
        for process in processes:
            try:
                process.terminate()
                process.wait(timeout=5)
            except:
                process.kill()

        # Clean up Docker containers
        for tool_id, tool_config in config_manager.get_tools_config().items():
            if tool_config.get("launch_cmd") == "docker":
                try:
                    subprocess.run(
                        ["docker", "stop", f"smart-agent-{tool_id}"], check=False
                    )
                except:
                    pass

        print("All services stopped.")


@click.command()
@click.option("--config", help="Path to configuration file")
@click.option("--tools", is_flag=True, help="Stop tool services")
@click.option("--proxy", is_flag=True, help="Stop LiteLLM proxy service")
@click.option("--all", is_flag=True, help="Stop all services (tools and proxy)")
def stop(config, tools, proxy, all):
    """Stop running services."""
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


@click.command()
@click.option("--config", help="Path to configuration file")
@click.option("--tools", is_flag=True, help="Restart tool services")
@click.option("--proxy", is_flag=True, help="Restart LiteLLM proxy service")
@click.option("--all", is_flag=True, help="Restart all services (tools and proxy)")
def restart(config, tools, proxy, all):
    """Restart tool and proxy services."""
    # Use the existing stop and start commands
    stop_cmd.callback(config=config, tools=tools, proxy=proxy, all=all)
    start_cmd.callback(config=config, tools=tools, proxy=proxy, all=all)
    print("Restart complete.")


def launch_litellm_proxy(config_manager):
    """Launch the LiteLLM proxy using Docker."""
    try:
        config_path = os.path.join(os.path.abspath("config"), "litellm_config.yaml")
        if not os.path.exists(config_path):
            print(f"Error: LiteLLM configuration file not found at {config_path}")
            return None

        # Check if Docker is available
        try:
            subprocess.run(
                ["docker", "--version"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except (subprocess.SubprocessError, FileNotFoundError):
            print("Error: Docker is not available. Cannot launch LiteLLM proxy.")
            return None

        # First, ensure old containers are removed
        try:
            subprocess.run(
                ["docker", "rm", "-f", "smart-agent-litellm-proxy"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception:
            pass  # Ignore errors if container doesn't exist

        # Launch LiteLLM proxy using Docker
        print("Launching LiteLLM proxy using Docker...")

        docker_cmd = [
            "docker",
            "run",
            "--name",
            "smart-agent-litellm-proxy",
            "-d",  # Run in detached mode
            "-p",
            "4000:4000",  # Map port
            "-v",
            f"{os.path.abspath('config')}/litellm_config.yaml:/app/config.yaml",
            "-e",
            "PORT=4000",
            "-e",
            "HOST=0.0.0.0",
            "ghcr.io/berriai/litellm:litellm_stable_release_branch-stable",
            "--config",
            "/app/config.yaml",
            "--port",
            "4000",
            "--host",
            "0.0.0.0",
        ]

        # Start the Docker container
        process = subprocess.Popen(
            docker_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )

        # Create a background monitoring process
        monitor_cmd = ["docker", "logs", "-f", "smart-agent-litellm-proxy"]
        monitor_process = subprocess.Popen(
            monitor_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        # Return the monitoring process so we can terminate it later
        return monitor_process
    except Exception as e:
        print(f"Error launching LiteLLM proxy: {e}")
        return None


@click.command()
@click.option("--config", help="Path to configuration file")
def chat(config):
    """Start a chat session with Smart Agent."""
    config_manager = ConfigManager(config)

    processes = []
    try:
        # Automatically launch tools based on configuration
        # Tools will only be launched if they are enabled in the YAML config
        processes = launch_tools(config_manager)

        # Start chat session
        chat(config_manager)
    finally:
        # Clean up processes
        for process in processes:
            try:
                process.terminate()
                process.wait(timeout=5)
            except:
                process.kill()

        # Clean up Docker containers
        for tool_id, tool_config in config_manager.get_tools_config().items():
            if tool_config.get("launch_cmd") == "docker":
                try:
                    subprocess.run(
                        ["docker", "stop", f"smart-agent-{tool_id}"], check=False
                    )
                except:
                    pass

        if processes:
            print("All tools stopped.")


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
                        abs_storage_path = os.path.abspath(
                            os.path.join(os.getcwd(), "storage", storage_path)
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
        print("  smart-agent chat                 # Start chat session")
        print("  smart-agent start                # Start all services")
        return

    # Interactive setup - Step 1: Configure main settings
    if setup_all or config:
        print("\n===== MAIN CONFIGURATION =====")

        # Check if config already exists and use it as base
        if os.path.exists("config/config.yaml"):
            print("Found existing config.yaml, using as default...")
            with open("config/config.yaml", "r") as f:
                config_yaml = yaml.safe_load(f)
        else:
            # Load default config from example
            with open(config_example_path, "r") as f:
                config_yaml = yaml.safe_load(f)

        # Get model name from config
        model_name = config_yaml.get("model", {}).get("name")

        print(f"\nUsing configuration with model: {model_name}")
        change_model = (
            input("Do you want to change the model? [y/N]: ").strip().lower() == "y"
        )

        if change_model:
            model_name = (
                input(f"Enter model name [{model_name}]: ").strip() or model_name
            )
            config_yaml["model"]["name"] = model_name

        # Get API key
        api_key = getpass.getpass(
            f"Enter API Key [{config_yaml.get('api', {}).get('api_key', '*****')}]: "
        ).strip()
        if api_key:  # Only update if user entered something
            config_yaml["api"]["api_key"] = api_key

        # Write main config
        with open("config/config.yaml", "w") as f:
            yaml.dump(config_yaml, f, default_flow_style=False)
        print("✓ Updated config/config.yaml")

    # Step 2: Configure tools
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

    # Step 3: Configure LiteLLM if using proxy
    if setup_all or litellm:
        # Determine if we're using LiteLLM proxy
        if setup_all:
            # Read from config.yaml to check if we're using proxy
            if os.path.exists("config/config.yaml"):
                with open("config/config.yaml", "r") as f:
                    config_data = yaml.safe_load(f)
                    base_url = config_data.get("api", {}).get("base_url", "")
                    use_litellm = (
                        "localhost:4000" in base_url or "127.0.0.1:4000" in base_url
                    )
            else:
                # Default to assuming we use proxy if setting up everything
                use_litellm = True
        else:
            # If explicitly asked to set up LiteLLM, don't ask again
            use_litellm = True

        if use_litellm:
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
                # Generate basic LiteLLM config with the model
                # Get model name from config.yaml if it exists
                if os.path.exists("config/config.yaml"):
                    with open("config/config.yaml", "r") as f:
                        config_data = yaml.safe_load(f)
                        model_name = config_data.get("model", {}).get(
                            "name", "claude-3-sonnet-20240229"
                        )
                else:
                    model_name = "claude-3-sonnet-20240229"  # Default if no config.yaml

                provider_prefix = (
                    "anthropic" if "claude" in model_name.lower() else "openai"
                )
                env_var = f"${provider_prefix.upper()}_API_KEY"

                litellm_config = {
                    "model_list": [
                        {
                            "model_name": model_name,
                            "litellm_params": {
                                "model": f"{provider_prefix}/{model_name}",
                                "api_key": env_var,
                            },
                        }
                    ],
                    "server": {"port": 4000, "host": "0.0.0.0"},
                    "router": {"timeout": 30, "routing_strategy": "simple-shuffle"},
                }
                print(
                    "Generated basic LiteLLM configuration based on the selected model."
                )

            # Ask user if they want to customize LiteLLM config
            customize_litellm = (
                input(
                    "\nDo you want to add or remove models from LiteLLM configuration? [y/N]: "
                )
                .strip()
                .lower()
                == "y"
            )

            if customize_litellm:
                # Show current models
                print("\nCurrent models in configuration:")
                for idx, model_entry in enumerate(litellm_config.get("model_list", [])):
                    print(f"{idx+1}. {model_entry.get('model_name')}")

                # Add models option
                add_models = (
                    input("\nAdd fallback models? [y/N]: ").strip().lower() == "y"
                )
                if add_models:
                    # Check if there are other models in the example file
                    if litellm_example:
                        with open(litellm_example_path, "r") as f:
                            example_config = yaml.safe_load(f)

                            # Find models in example that aren't in current config
                            current_models = [
                                m.get("model_name")
                                for m in litellm_config.get("model_list", [])
                            ]
                            example_models = []

                            for model_entry in example_config.get("model_list", []):
                                model_name = model_entry.get("model_name")
                                if model_name and model_name not in current_models:
                                    example_models.append(model_entry)

                            # Offer these as options to add
                            if example_models:
                                print(
                                    "\nAdditional models available from example config:"
                                )
                                for idx, model_entry in enumerate(example_models):
                                    print(f"{idx+1}. {model_entry.get('model_name')}")

                                for model_entry in example_models:
                                    model_name = model_entry.get("model_name")
                                    add_model = (
                                        input(f"Add {model_name}? [y/N]: ")
                                        .strip()
                                        .lower()
                                        == "y"
                                    )
                                    if add_model:
                                        litellm_config["model_list"].append(model_entry)
                                        print(f"✓ Added {model_name}")

                    # Generic fallback model options
                    current_models = [
                        m.get("model_name")
                        for m in litellm_config.get("model_list", [])
                    ]

                    if (
                        "gpt-4" not in current_models
                        and "claude" in " ".join(current_models).lower()
                    ):
                        add_gpt4 = (
                            input("Add GPT-4 as a fallback model? [y/N]: ")
                            .strip()
                            .lower()
                            == "y"
                        )
                        if add_gpt4:
                            litellm_config["model_list"].append(
                                {
                                    "model_name": "gpt-4",
                                    "litellm_params": {
                                        "model": "openai/gpt-4",
                                        "api_key": "${OPENAI_API_KEY}",
                                    },
                                }
                            )
                            print("✓ Added GPT-4 (requires OPENAI_API_KEY)")

                    if (
                        "gpt-3.5-turbo" not in current_models
                        and "claude" in " ".join(current_models).lower()
                    ):
                        add_gpt35 = (
                            input("Add GPT-3.5 Turbo as a fallback model? [y/N]: ")
                            .strip()
                            .lower()
                            == "y"
                        )
                        if add_gpt35:
                            litellm_config["model_list"].append(
                                {
                                    "model_name": "gpt-3.5-turbo",
                                    "litellm_params": {
                                        "model": "openai/gpt-3.5-turbo",
                                        "api_key": "${OPENAI_API_KEY}",
                                    },
                                }
                            )
                            print("✓ Added GPT-3.5 Turbo (requires OPENAI_API_KEY)")

                    if (
                        "claude-3-sonnet-20240229" not in current_models
                        and "gpt" in " ".join(current_models).lower()
                    ):
                        add_claude = (
                            input("Add Claude as a fallback model? [y/N]: ")
                            .strip()
                            .lower()
                            == "y"
                        )
                        if add_claude:
                            litellm_config["model_list"].append(
                                {
                                    "model_name": "claude-3-sonnet-20240229",
                                    "litellm_params": {
                                        "model": "anthropic/claude-3-sonnet-20240229",
                                        "api_key": "${ANTHROPIC_API_KEY}",
                                    },
                                }
                            )
                            print("✓ Added Claude (requires ANTHROPIC_API_KEY)")

                # Remove models option
                remove_models = (
                    input("\nRemove any models? [y/N]: ").strip().lower() == "y"
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
                    else:
                        print("Cannot remove the only model in configuration.")

            # Write LiteLLM config
            with open("config/litellm_config.yaml", "w") as f:
                yaml.dump(litellm_config, f, default_flow_style=False)
            print("✓ Updated config/litellm_config.yaml")

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
                            os.path.join(os.getcwd(), "storage", storage_path)
                        )
                        tools_yaml["tools"][tool_id]["storage_path"] = abs_storage_path
                        storage_path = abs_storage_path
                        print(f"⚠️ Converting relative path to absolute: {storage_path}")

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
    print("  smart-agent start --tools        # Start only tool services")
    print("  smart-agent start --proxy        # Start only the LiteLLM proxy")


@click.group()
def cli():
    """Smart Agent CLI - AI agent with reasoning and tool use capabilities."""
    pass


cli.add_command(chat)
cli.add_command(start)
cli.add_command(stop)
cli.add_command(restart)
cli.add_command(setup)


def main():
    """Main entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
