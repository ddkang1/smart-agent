#!/usr/bin/env python
"""
CLI interface for Smart Agent.
"""

import os
import json
import asyncio
import subprocess
import time
import signal
import click
from typing import Dict, Any, Optional, List
import openai
from dotenv import load_dotenv

from agents import (
    set_tracing_disabled,
    MCPServerSse,
)

from .agent import SmartAgent
from .tool_manager import ToolManager


# Load environment variables from .env file if it exists
load_dotenv()


class PromptGenerator:
    @staticmethod
    def create_system_prompt() -> str:
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


async def chat_loop(
    api_provider: str,
    claude_api_key: str,
    base_url: str,
    langfuse_public_key: Optional[str] = None,
    langfuse_secret_key: Optional[str] = None,
    langfuse_host: Optional[str] = None,
    mcp_config: Optional[Dict[str, Any]] = None,
    tools_config_path: Optional[str] = None,
):
    """
    Run the chat loop.
    """
    # Disable tracing
    set_tracing_disabled(disabled=True)
    
    # Initialize an async OpenAI client
    client = openai.AsyncOpenAI(
        base_url=base_url,
        api_key=claude_api_key,
    )

    # Configure AWS credentials if using Bedrock
    if api_provider == "bedrock":
        # Set AWS environment variables for Bedrock
        os.environ["AWS_ACCESS_KEY_ID"] = os.getenv("AWS_ACCESS_KEY_ID", "")
        os.environ["AWS_SECRET_ACCESS_KEY"] = os.getenv("AWS_SECRET_ACCESS_KEY", "")
        os.environ["AWS_REGION"] = os.getenv("AWS_REGION", "us-west-2")

    # Initialize tool manager and MCP servers
    tool_manager = ToolManager(config_path=tools_config_path)
    mcp_servers = tool_manager.initialize_tools()
    
    # Create context manager for all MCP servers
    class MCPServersManager:
        def __init__(self, servers):
            self.servers = servers
        
        async def __aenter__(self):
            for server in self.servers:
                await server.__aenter__()
            return self.servers
        
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            for server in self.servers:
                await server.__aexit__(exc_type, exc_val, exc_tb)
    
    # Initialize the agent with MCP servers
    async with MCPServersManager(mcp_servers) as servers:
        agent = SmartAgent(
            openai_client=client,
            mcp_servers=servers,
        )
        
        # Start the chat loop
        print("\nSmart Agent initialized. Type 'exit' to quit.\n")
        
        while True:
            # Get user input
            user_input = input("You: ")
            
            # Check if the user wants to exit
            if user_input.lower() in ["exit", "quit", "q"]:
                break
            
            # Process the user input and get a response
            response = await agent.process_message(user_input)
            
            # Print the response
            print(f"\nAI: {response}\n")


@click.command()
@click.option(
    "--tools-config",
    type=click.Path(exists=False),
    help="Path to tools YAML configuration file",
)
@click.option(
    "--disable-tools",
    is_flag=True,
    help="Disable all tool services",
)
def launch_tools(
    tools_config,
    disable_tools,
):
    """Launch the tool services required by Smart Agent."""
    # Initialize tool manager
    tool_manager = ToolManager(config_path=tools_config)
    
    # If disable_tools is set, exit early
    if disable_tools:
        print("All tools disabled. Exiting.")
        return
    
    # Store process objects
    processes = []
    
    try:
        # Get all enabled tools from the config
        all_tools = tool_manager.get_all_tools()
        
        for tool_id, tool_config in all_tools.items():
            if tool_manager.is_tool_enabled(tool_id):
                tool_url = tool_manager.get_tool_url(tool_id)
                tool_repo = tool_manager.get_tool_repository(tool_id)
                tool_type = tool_config.get("type", "sse")
                tool_name = tool_config.get("name", tool_id)
                
                # Extract port from URL
                import re
                port_match = re.search(r":(\d+)/", tool_url)
                port = int(port_match.group(1)) if port_match else None
                
                print(f"Starting {tool_name} on {tool_url}")
                
                if tool_config.get("container", False):
                    # Handle Docker container-based tools
                    python_repl_data = "python_repl_storage"
                    os.makedirs(python_repl_data, exist_ok=True)
                    
                    # Run Docker container
                    docker_cmd = [
                        "docker", "run", "-d", "--rm", "--name", f"mcp-{tool_id}",
                        "-p", f"{port}:8000",
                        "-v", f"{os.path.abspath(python_repl_data)}:/app/data",
                        tool_repo
                    ]
                    subprocess.run(docker_cmd, check=True)
                    
                    # Set environment variable for URL
                    os.environ[f"{tool_config.get('env_prefix', 'MCP_' + tool_id.upper())}_URL"] = tool_url
                    print(f"{tool_name} available at {tool_url}")
                else:
                    # Generic tool handling
                    module_name = tool_config.get("module", tool_id.replace("-", "_"))
                    
                    # Install tool if needed
                    try:
                        subprocess.run(["pip", "show", module_name], check=True, capture_output=True)
                    except subprocess.CalledProcessError:
                        print(f"Installing {tool_name} from {tool_repo}")
                        subprocess.run(["pip", "install", tool_repo], check=True)
                    
                    # Start tool server
                    server_module = tool_config.get("server_module", f"{module_name}.server")
                    tool_cmd = ["python", "-m", server_module]
                    
                    if port:
                        tool_cmd.extend(["--port", str(port)])
                    
                    tool_process = subprocess.Popen(tool_cmd)
                    processes.append(tool_process)
                    
                    # Set environment variable for URL
                    os.environ[f"{tool_config.get('env_prefix', 'MCP_' + tool_id.upper())}_URL"] = tool_url
                    print(f"{tool_name} available at {tool_url}")
        
        print("\nAll enabled tools are now running.")
        print("Press Ctrl+C to stop all tools and exit.")
        
        # Keep the process running until interrupted
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nStopping all tools...")
    finally:
        # Clean up processes
        for process in processes:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        
        # Stop Docker containers
        for tool_id, tool_config in all_tools.items():
            if tool_manager.is_tool_enabled(tool_id) and tool_config.get("container", False):
                try:
                    subprocess.run(["docker", "stop", f"mcp-{tool_id}"], check=False)
                except:
                    pass
        
        print("All tools stopped.")


@click.command()
@click.option(
    "--api-key",
    envvar="CLAUDE_API_KEY",
    help="Claude API key",
)
@click.option(
    "--api-base-url",
    envvar="CLAUDE_BASE_URL",
    default="http://0.0.0.0:4000",
    help="Base URL for Claude API",
)
@click.option(
    "--api-provider",
    envvar="API_PROVIDER",
    type=click.Choice(["anthropic", "bedrock", "proxy"]),
    default="proxy",
    help="API provider to use",
)
@click.option(
    "--langfuse-public-key",
    envvar="LANGFUSE_PUBLIC_KEY",
    help="Langfuse public key",
)
@click.option(
    "--langfuse-secret-key",
    envvar="LANGFUSE_SECRET_KEY",
    help="Langfuse secret key",
)
@click.option(
    "--langfuse-host",
    envvar="LANGFUSE_HOST",
    default="https://cloud.langfuse.com",
    help="Langfuse host",
)
@click.option(
    "--mcp-config",
    type=click.Path(exists=False),
    help="Path to MCP configuration file",
)
@click.option(
    "--tools-config",
    type=click.Path(exists=False),
    help="Path to tools YAML configuration file",
)
@click.option(
    "--launch-tools",
    is_flag=True,
    help="Launch required tool services before starting the chat",
)
@click.option(
    "--disable-tools",
    is_flag=True,
    help="Disable all tool services",
)
def chat(
    api_key,
    api_base_url,
    api_provider,
    langfuse_public_key,
    langfuse_secret_key,
    langfuse_host,
    mcp_config,
    tools_config,
    launch_tools,
    disable_tools,
):
    """Start a chat session with the Smart Agent."""
    # Load MCP config if provided
    mcp_config_dict = None
    if mcp_config:
        with open(mcp_config, "r") as f:
            mcp_config_dict = json.load(f)
    
    # Launch tools if requested
    tool_processes = []
    if launch_tools and not disable_tools:
        try:
            # Initialize tool manager
            tool_manager = ToolManager(config_path=tools_config)
            python_repl_data = "python_repl_storage"
            
            # Get all enabled tools from the config
            all_tools = tool_manager.get_all_tools()
            
            for tool_id, tool_config in all_tools.items():
                if tool_manager.is_tool_enabled(tool_id):
                    tool_url = tool_manager.get_tool_url(tool_id)
                    tool_repo = tool_manager.get_tool_repository(tool_id)
                    tool_type = tool_config.get("type", "sse")
                    tool_name = tool_config.get("name", tool_id)
                    
                    # Extract port from URL
                    import re
                    port_match = re.search(r":(\d+)/", tool_url)
                    port = int(port_match.group(1)) if port_match else None
                    
                    print(f"Starting {tool_name} on {tool_url}")
                    
                    if tool_config.get("container", False):
                        # Handle Docker container-based tools
                        os.makedirs(python_repl_data, exist_ok=True)
                        
                        # Run Docker container
                        docker_cmd = [
                            "docker", "run", "-d", "--rm", "--name", f"mcp-{tool_id}",
                            "-p", f"{port}:8000",
                            "-v", f"{os.path.abspath(python_repl_data)}:/app/data",
                            tool_repo
                        ]
                        subprocess.run(docker_cmd, check=True)
                        
                        # Set environment variable for URL
                        os.environ[f"{tool_config.get('env_prefix', 'MCP_' + tool_id.upper())}_URL"] = tool_url
                        print(f"{tool_name} available at {tool_url}")
                    else:
                        # Generic tool handling
                        module_name = tool_config.get("module", tool_id.replace("-", "_"))
                        
                        # Install tool if needed
                        try:
                            subprocess.run(["pip", "show", module_name], check=True, capture_output=True)
                        except subprocess.CalledProcessError:
                            print(f"Installing {tool_name} from {tool_repo}")
                            subprocess.run(["pip", "install", tool_repo], check=True)
                        
                        # Start tool server
                        server_module = tool_config.get("server_module", f"{module_name}.server")
                        tool_cmd = ["python", "-m", server_module]
                        
                        if port:
                            tool_cmd.extend(["--port", str(port)])
                        
                        tool_process = subprocess.Popen(tool_cmd)
                        tool_processes.append(tool_process)
                        
                        # Set environment variable for URL
                        os.environ[f"{tool_config.get('env_prefix', 'MCP_' + tool_id.upper())}_URL"] = tool_url
                        print(f"{tool_name} available at {tool_url}")
            
            print("\nAll enabled tools are now running.")
            
        except Exception as e:
            print(f"Error launching tools: {e}")
            # Clean up any started processes
            for process in tool_processes:
                process.terminate()
            
            # Stop Docker containers
            for tool_id, tool_config in all_tools.items():
                if tool_manager.is_tool_enabled(tool_id) and tool_config.get("container", False):
                    try:
                        subprocess.run(["docker", "stop", f"mcp-{tool_id}"], check=False)
                    except:
                        pass
            
            return
    
    try:
        # Run the chat loop
        asyncio.run(
            chat_loop(
                api_provider=api_provider,
                claude_api_key=api_key,
                base_url=api_base_url,
                langfuse_public_key=langfuse_public_key,
                langfuse_secret_key=langfuse_secret_key,
                langfuse_host=langfuse_host,
                mcp_config=mcp_config_dict,
                tools_config_path=tools_config,
            )
        )
    finally:
        # Clean up processes if tools were launched
        if launch_tools and not disable_tools and tool_processes:
            print("\nStopping all tools...")
            for process in tool_processes:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
            
            # Stop Docker containers
            for tool_id, tool_config in all_tools.items():
                if tool_manager.is_tool_enabled(tool_id) and tool_config.get("container", False):
                    try:
                        subprocess.run(["docker", "stop", f"mcp-{tool_id}"], check=False)
                    except:
                        pass
            
            print("All tools stopped.")


@click.group()
def cli():
    """Smart Agent CLI - AI agent with reasoning and tool use capabilities."""
    pass


def main():
    """Entry point for the CLI."""
    cli.add_command(chat)
    cli.add_command(launch_tools)
    cli()


if __name__ == "__main__":
    main()
