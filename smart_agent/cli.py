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
from typing import Optional, List, Dict, Any
from pathlib import Path
import re
from urllib.parse import urlparse
import locale

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
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
                host=langfuse_config.get("host", "https://cloud.langfuse.com")
            )
            print("Langfuse monitoring enabled")
        except ImportError:
            print("Langfuse package not installed. Run 'pip install langfuse' to enable monitoring.")
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
        print("Required packages not installed. Run 'pip install openai agent' to use the agent.")
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
                    metadata={"model": model_name, "temperature": temperature}
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


def chat(config_manager: ConfigManager, disable_tools: bool = False):
    """
    Start a chat session with Smart Agent.
    
    Args:
        config_manager: Configuration manager
        disable_tools: Whether to disable all tools
    """
    # Start chat loop
    chat_loop(config_manager)


def launch_tools(config_manager: ConfigManager, disable_tools: bool = False) -> List[subprocess.Popen]:
    """
    Launch tool services.
    
    Args:
        config_manager: Configuration manager
        disable_tools: Whether to disable all tools
        
    Returns:
        List of tool processes
    """
    if disable_tools:
        print("All tools are disabled")
        return []
    
    processes = []
    
    # Get all enabled tools
    enabled_tools = []
    for tool_id, tool_config in config_manager.get_tools_config().items():
        if config_manager.is_tool_enabled(tool_id):
            enabled_tools.append((tool_id, tool_config))
    
    if not enabled_tools:
        print("No enabled tools found.")
        return processes
    
    print(f"Launching {len(enabled_tools)} enabled tools...")
    
    for tool_id, tool_config in enabled_tools:
        tool_name = tool_config.get("name", tool_id)
        tool_repo = config_manager.get_tool_repository(tool_id)
        tool_url = config_manager.get_tool_url(tool_id)
        
        # Extract port from URL
        url_parts = urlparse(tool_url)
        port = None
        if url_parts.port:
            port = url_parts.port
        
        print(f"Launching {tool_name}...")
        
        # Get launch command type
        launch_cmd = tool_config.get("launch_cmd", "uvx")
        
        # Check if this is a remote SSE tool (no need to launch locally)
        if not url_parts.hostname in ["localhost", "127.0.0.1"]:
            print(f"Tool {tool_name} is a remote SSE tool at {tool_url}, no need to launch locally")
            continue
        
        # All local tools are treated as stdio tools that need conversion to SSE
        if launch_cmd == "docker":
            # Docker container-based tool
            storage_path = tool_config.get("storage_path", "tool_storage")
            storage_dir = os.path.join(os.getcwd(), storage_path)
            os.makedirs(storage_dir, exist_ok=True)
            
            print(f"Converting stdio Docker tool to SSE using supergateway: {tool_name}")
            
            # Use supergateway to convert stdio to SSE
            tool_cmd = [
                "npx", "-y", "supergateway",
                "--stdio", f"docker run -i --rm --pull=always -v {os.path.abspath(storage_dir)}:/app/data {tool_repo}",
                "--port", str(port),
                "--baseUrl", f"http://localhost:{port}",
                "--ssePath", "/sse",
                "--messagePath", "/message"
            ]
            
            tool_process = subprocess.Popen(tool_cmd)
            processes.append(tool_process)
            
            # Set environment variable for URL
            os.environ[f"{config_manager.get_env_prefix(tool_id)}_URL"] = tool_url
            print(f"{tool_name} available at {tool_url}")
        elif launch_cmd == "npx":
            # NPX-based tool
            module_name = tool_config.get("module", tool_id)
            
            print(f"Converting stdio NPX tool to SSE using supergateway: {tool_name}")
            
            # Use supergateway to convert stdio to SSE
            tool_cmd = [
                "npx", "-y", "supergateway",
                "--stdio", f"npx {module_name}",
                "--port", str(port),
                "--baseUrl", f"http://localhost:{port}",
                "--ssePath", "/sse",
                "--messagePath", "/message"
            ]
            
            tool_process = subprocess.Popen(tool_cmd)
            processes.append(tool_process)
            
            # Set environment variable for URL
            os.environ[f"{config_manager.get_env_prefix(tool_id)}_URL"] = tool_url
            print(f"{tool_name} available at {tool_url}")
        elif launch_cmd == "uvx":
            # UVX-based tool (Python package)
            module_name = tool_config.get("module", tool_id.replace("-", "_"))
            
            print(f"Converting stdio UVX tool to SSE using supergateway: {tool_name}")
            
            # Use supergateway to convert stdio to SSE
            tool_cmd = [
                "npx", "-y", "supergateway",
                "--stdio", f"uvx --from {tool_repo} {module_name}",
                "--port", str(port),
                "--baseUrl", f"http://localhost:{port}",
                "--ssePath", "/sse",
                "--messagePath", "/message"
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
@click.option('--config', help='Path to configuration file')
def chat_cmd(config):
    """Start a chat session with Smart Agent."""
    config_manager = ConfigManager(config)
    
    processes = []
    try:
        # Automatically launch tools based on configuration
        processes = launch_tools(config_manager, disable_tools=False)
        
        # Start chat session
        chat(config_manager, disable_tools=False)
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
                    subprocess.run(["docker", "stop", f"smart-agent-{tool_id}"], check=False)
                except:
                    pass
        
        print("All tools stopped.")


@click.command()
@click.option('--config', help='Path to configuration file')
def launch_tools_cmd(config):
    """Launch tool services."""
    config_manager = ConfigManager(config)
    
    try:
        # Launch all enabled tools
        processes = launch_tools(config_manager, disable_tools=False)
        
        # Keep the process running until interrupted
        print("\nPress Ctrl+C to stop all tools.")
        for process in processes:
            process.wait()
    except KeyboardInterrupt:
        print("\nStopping all tools...")
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
                    subprocess.run(["docker", "stop", f"smart-agent-{tool_id}"], check=False)
                except:
                    pass
        
        print("All tools stopped.")


@click.command()
def setup_cmd():
    """Set up the environment for Smart Agent."""
    # Get the directory where the script is located
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    setup_script = os.path.join(script_dir, "setup-env.sh")
    
    print("Setting up Smart Agent environment...")
    
    # Run the setup script directly
    try:
        subprocess.run(["bash", setup_script], check=True)
    except subprocess.CalledProcessError:
        print("Error running setup script. Please check the output for details.")
        sys.exit(1)


@click.group()
def cli():
    """Smart Agent CLI - AI agent with reasoning and tool use capabilities."""
    pass


cli.add_command(chat_cmd)
cli.add_command(launch_tools_cmd, name="launch-tools")
cli.add_command(setup_cmd)


def main():
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
