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
    "--python-repl-data",
    default="python_repl_storage",
    help="Directory to store Python REPL data",
)
@click.option(
    "--python-repl-port",
    default=8000,
    type=int,
    help="Port for Python REPL tool",
)
@click.option(
    "--think-tool-port",
    default=8001,
    type=int,
    help="Port for Think tool",
)
@click.option(
    "--search-tool-port",
    default=8002,
    type=int,
    help="Port for Search tool",
)
@click.option(
    "--no-python-repl",
    is_flag=True,
    help="Disable Python REPL tool",
)
@click.option(
    "--no-think-tool",
    is_flag=True,
    help="Disable Think tool",
)
@click.option(
    "--no-search-tool",
    is_flag=True,
    help="Disable Search tool",
)
def launch_tools(
    tools_config,
    python_repl_data,
    python_repl_port,
    think_tool_port,
    search_tool_port,
    no_python_repl,
    no_think_tool,
    no_search_tool,
):
    """Launch the tool services required by Smart Agent."""
    # Initialize tool manager
    tool_manager = ToolManager(config_path=tools_config)
    
    # Process override flags
    enable_python_repl = not no_python_repl
    enable_think_tool = not no_think_tool
    enable_search_tool = not no_search_tool
    
    # Get tool configurations
    python_tool_config = tool_manager.get_tool_config("python_tool")
    think_tool_config = tool_manager.get_tool_config("think_tool")
    search_tool_config = tool_manager.get_tool_config("search_tool")
    
    # Override enabled status from command line flags
    if no_python_repl:
        os.environ["ENABLE_PYTHON_TOOL"] = "false"
    if no_think_tool:
        os.environ["ENABLE_THINK_TOOL"] = "false"
    if no_search_tool:
        os.environ["ENABLE_SEARCH_TOOL"] = "false"
    
    # Create data directory for Python REPL
    if enable_python_repl and tool_manager.is_tool_enabled("python_tool"):
        os.makedirs(python_repl_data, exist_ok=True)
    
    # Store process objects
    processes = []
    
    try:
        # Launch Python REPL tool
        if enable_python_repl and tool_manager.is_tool_enabled("python_tool"):
            python_tool_repo = tool_manager.get_tool_repository("python_tool")
            print(f"Starting Python REPL tool on port {python_repl_port}")
            
            # Run Docker container
            docker_cmd = [
                "docker", "run", "-d", "--rm", "--name", "mcp-python-repl",
                "-p", f"{python_repl_port}:8000",
                "-v", f"{os.path.abspath(python_repl_data)}:/app/data",
                python_tool_repo
            ]
            subprocess.run(docker_cmd, check=True)
            
            # Set environment variable for URL
            os.environ["MCP_PYTHON_TOOL_URL"] = f"http://localhost:{python_repl_port}/sse"
            print(f"Python REPL tool available at {os.environ['MCP_PYTHON_TOOL_URL']}")
        
        # Launch Think tool
        if enable_think_tool and tool_manager.is_tool_enabled("think_tool"):
            think_tool_repo = tool_manager.get_tool_repository("think_tool")
            print(f"Starting Think tool on port {think_tool_port}")
            
            # Install Think tool if needed
            try:
                subprocess.run(["pip", "show", "mcp-think-tool"], check=True, capture_output=True)
            except subprocess.CalledProcessError:
                print(f"Installing Think tool from {think_tool_repo}")
                subprocess.run(["pip", "install", think_tool_repo], check=True)
            
            # Start Think tool server
            think_cmd = ["python", "-m", "mcp_think_tool.server", "--port", str(think_tool_port)]
            think_process = subprocess.Popen(think_cmd)
            processes.append(think_process)
            
            # Set environment variable for URL
            os.environ["MCP_THINK_TOOL_URL"] = f"http://localhost:{think_tool_port}/sse"
            print(f"Think tool available at {os.environ['MCP_THINK_TOOL_URL']}")
        
        # Launch Search tool
        if enable_search_tool and tool_manager.is_tool_enabled("search_tool"):
            search_tool_repo = tool_manager.get_tool_repository("search_tool")
            print(f"Starting Search tool on port {search_tool_port}")
            
            # Install Search tool if needed
            try:
                subprocess.run(["pip", "show", "ddg-mcp"], check=True, capture_output=True)
            except subprocess.CalledProcessError:
                print(f"Installing Search tool from {search_tool_repo}")
                subprocess.run(["pip", "install", search_tool_repo], check=True)
            
            # Start Search tool server
            search_cmd = ["python", "-m", "ddg_mcp.server", "--port", str(search_tool_port)]
            search_process = subprocess.Popen(search_cmd)
            processes.append(search_process)
            
            # Set environment variable for URL
            os.environ["MCP_SEARCH_TOOL_URL"] = f"http://localhost:{search_tool_port}/sse"
            print(f"Search tool available at {os.environ['MCP_SEARCH_TOOL_URL']}")
        
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
        
        # Stop Docker container
        if enable_python_repl and tool_manager.is_tool_enabled("python_tool"):
            try:
                subprocess.run(["docker", "stop", "mcp-python-repl"], check=False)
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
    "--python-repl-port",
    default=8000,
    type=int,
    help="Port for Python REPL tool (when using --launch-tools)",
)
@click.option(
    "--think-tool-port",
    default=8001,
    type=int,
    help="Port for Think tool (when using --launch-tools)",
)
@click.option(
    "--search-tool-port",
    default=8002,
    type=int,
    help="Port for Search tool (when using --launch-tools)",
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
    python_repl_port,
    think_tool_port,
    search_tool_port,
):
    """Start a chat session with the Smart Agent."""
    # Load MCP config if provided
    mcp_config_dict = None
    if mcp_config:
        with open(mcp_config, "r") as f:
            mcp_config_dict = json.load(f)
    
    # Launch tools if requested
    tool_processes = []
    if launch_tools:
        try:
            # Initialize tool manager
            tool_manager = ToolManager(config_path=tools_config)
            python_repl_data = "python_repl_storage"
            
            # Create data directory for Python REPL
            if tool_manager.is_tool_enabled("python_tool"):
                os.makedirs(python_repl_data, exist_ok=True)
            
            # Launch Python REPL tool
            if tool_manager.is_tool_enabled("python_tool"):
                python_tool_repo = tool_manager.get_tool_repository("python_tool")
                print(f"Starting Python REPL tool on port {python_repl_port}")
                
                # Run Docker container
                docker_cmd = [
                    "docker", "run", "-d", "--rm", "--name", "mcp-python-repl",
                    "-p", f"{python_repl_port}:8000",
                    "-v", f"{os.path.abspath(python_repl_data)}:/app/data",
                    python_tool_repo
                ]
                subprocess.run(docker_cmd, check=True)
                
                # Set environment variable for URL
                os.environ["MCP_PYTHON_TOOL_URL"] = f"http://localhost:{python_repl_port}/sse"
                print(f"Python REPL tool available at {os.environ['MCP_PYTHON_TOOL_URL']}")
            
            # Launch Think tool
            if tool_manager.is_tool_enabled("think_tool"):
                think_tool_repo = tool_manager.get_tool_repository("think_tool")
                print(f"Starting Think tool on port {think_tool_port}")
                
                # Install Think tool if needed
                try:
                    subprocess.run(["pip", "show", "mcp-think-tool"], check=True, capture_output=True)
                except subprocess.CalledProcessError:
                    print(f"Installing Think tool from {think_tool_repo}")
                    subprocess.run(["pip", "install", think_tool_repo], check=True)
                
                # Start Think tool server
                think_cmd = ["python", "-m", "mcp_think_tool.server", "--port", str(think_tool_port)]
                think_process = subprocess.Popen(think_cmd)
                tool_processes.append(think_process)
                
                # Set environment variable for URL
                os.environ["MCP_THINK_TOOL_URL"] = f"http://localhost:{think_tool_port}/sse"
                print(f"Think tool available at {os.environ['MCP_THINK_TOOL_URL']}")
            
            # Launch Search tool
            if tool_manager.is_tool_enabled("search_tool"):
                search_tool_repo = tool_manager.get_tool_repository("search_tool")
                print(f"Starting Search tool on port {search_tool_port}")
                
                # Install Search tool if needed
                try:
                    subprocess.run(["pip", "show", "ddg-mcp"], check=True, capture_output=True)
                except subprocess.CalledProcessError:
                    print(f"Installing Search tool from {search_tool_repo}")
                    subprocess.run(["pip", "install", search_tool_repo], check=True)
                
                # Start Search tool server
                search_cmd = ["python", "-m", "ddg_mcp.server", "--port", str(search_tool_port)]
                search_process = subprocess.Popen(search_cmd)
                tool_processes.append(search_process)
                
                # Set environment variable for URL
                os.environ["MCP_SEARCH_TOOL_URL"] = f"http://localhost:{search_tool_port}/sse"
                print(f"Search tool available at {os.environ['MCP_SEARCH_TOOL_URL']}")
            
            print("\nAll enabled tools are now running.")
            
        except Exception as e:
            print(f"Error launching tools: {e}")
            # Clean up any started processes
            for process in tool_processes:
                process.terminate()
            
            # Stop Docker container
            try:
                subprocess.run(["docker", "stop", "mcp-python-repl"], check=False)
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
        if launch_tools:
            print("\nStopping all tools...")
            for process in tool_processes:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
            
            # Stop Docker container
            try:
                subprocess.run(["docker", "stop", "mcp-python-repl"], check=False)
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
