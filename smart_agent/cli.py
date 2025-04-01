#!/usr/bin/env python
"""
CLI interface for Smart Agent.
"""

import os
import json
import asyncio
import datetime
import locale
import sys
from pathlib import Path

import colorama
import click
from colorama import Fore, Style
from dotenv import load_dotenv

from langfuse.openai import openai
from langfuse.decorators import observe
from agents.mcp import MCPServerStdio, MCPServerSse
from agents import (
    Agent,
    OpenAIChatCompletionsModel,
    Runner,
    ItemHelpers,
    set_tracing_disabled,
)

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


async def ask(history: list[dict], api_base_url=None, api_key=None, langfuse_config=None, mcp_config=None, provider=None) -> str:
    """
    Processes the conversation history (list of message dicts) and streams the agent's response.
    
    Each dictionary in the history should follow the format, for example:
      {"role": "user", "content": "Hi there"}
    """
    # Initialize colorama for colorful output
    colorama.init(autoreset=True)
    
    # Determine API provider
    api_provider = provider or os.getenv("API_PROVIDER", "proxy")
    
    # Set up API configuration based on provider
    if api_base_url:
        base_url = api_base_url
    else:
        if api_provider == "anthropic":
            base_url = "https://api.anthropic.com/v1"
        elif api_provider == "bedrock":
            # For Bedrock, we'll use the OpenAI compatibility layer
            base_url = os.getenv("CLAUDE_BASE_URL", "https://bedrock-runtime.us-west-2.amazonaws.com")
        elif api_provider == "proxy":
            base_url = os.getenv("CLAUDE_BASE_URL", "http://0.0.0.0:4000")
        else:
            base_url = os.getenv("CLAUDE_BASE_URL", "https://api.anthropic.com/v1")
    
    # Set API key
    if api_key:
        claude_api_key = api_key
    else:
        claude_api_key = os.getenv("CLAUDE_API_KEY")
        if not claude_api_key:
            print(f"{Fore.RED}Error: CLAUDE_API_KEY environment variable not set.{Style.RESET_ALL}")
            sys.exit(1)
    
    # Configure Langfuse if provided
    if langfuse_config:
        os.environ["LANGFUSE_PUBLIC_KEY"] = langfuse_config.get("public_key", "")
        os.environ["LANGFUSE_SECRET_KEY"] = langfuse_config.get("secret_key", "")
        os.environ["LANGFUSE_HOST"] = langfuse_config.get("host", "https://cloud.langfuse.com")
    
    # Get MCP configuration
    mcp_think_tool_repo = mcp_config.get("think_tool_repo") if mcp_config else os.getenv("MCP_THINK_TOOL_REPO", "git+https://github.com/ddkang1/mcp-think-tool")
    mcp_search_tool_repo = mcp_config.get("search_tool_repo") if mcp_config else os.getenv("MCP_SEARCH_TOOL_REPO", "git+https://github.com/ddkang1/ddg-mcp")
    mcp_python_tool_url = mcp_config.get("python_tool_url") if mcp_config else os.getenv("MCP_PYTHON_TOOL_URL", "http://localhost:8000/sse")
    
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

    async with MCPServerStdio(
        cache_tools_list=True,
        params={
            "command": "uvx",
            "args": [
                "--from",
                mcp_think_tool_repo,
                "mcp-think-tool",
            ],
        },
    ) as think_tool, MCPServerStdio(
        cache_tools_list=True,
        params={
            "command": "uvx",
            "args": [
                "--from",
                mcp_search_tool_repo,
                "ddg-mcp",
            ],
        },
    ) as internet_search_tool, MCPServerSse(
        params={
            "url": mcp_python_tool_url,
        },
    ) as python_tool:

        agent = Agent(
            name="Assistant",
            # Optionally, you can include instructions as follows:
            # instructions=PromptGenerator.create_system_prompt(),
            model=OpenAIChatCompletionsModel(
                model="claude-3-7-sonnet",  # or use any other model configuration
                openai_client=client,
            ),
            mcp_servers=[think_tool, internet_search_tool, python_tool],
        )

        # Run the agent with the conversation history.
        result = Runner.run_streamed(agent, history, max_turns=100)
        assistant_reply = ""
        is_thought = False  # Tracks responses from the "thought" tool

        async for event in result.stream_events():
            if event.type == "raw_response_event":
                continue
            elif event.type == "agent_updated_stream_event":
                continue
            elif event.type == "run_item_stream_event":
                if event.item.type == "tool_call_item":
                    arguments_dict = json.loads(event.item.raw_item.arguments)
                    key, value = next(iter(arguments_dict.items()))
                    if key == "thought":
                        is_thought = True
                        print(
                            f"\n{Fore.CYAN}{Style.BRIGHT}thought:\n{value}{Style.RESET_ALL}",
                            flush=True,
                        )
                        assistant_reply += "\n[thought]: " + value
                    else:
                        is_thought = False
                        print(
                            f"\n{Fore.YELLOW}{Style.BRIGHT}{key}:\n{value}{Style.RESET_ALL}",
                            flush=True,
                        )
                elif event.item.type == "tool_call_output_item":
                    if not is_thought:
                        output_text = json.loads(event.item.output).get("text", "")
                        print(
                            f"\n{Fore.GREEN}{Style.BRIGHT}Tool Output:\n{output_text}{Style.RESET_ALL}",
                            flush=True,
                        )
                elif event.item.type == "message_output_item":
                    role = event.item.raw_item.role
                    text_message = ItemHelpers.text_message_output(event.item)
                    if role == "assistant":
                        print(
                            f"\n{Fore.BLUE}{Style.BRIGHT}{role}:\n{text_message}{Style.RESET_ALL}",
                            flush=True,
                        )
                        assistant_reply += "\n[response]: " + text_message
                    else:
                        print(
                            f"\n{Fore.MAGENTA}{Style.BRIGHT}{role}:\n{text_message}{Style.RESET_ALL}",
                            flush=True,
                        )
        return assistant_reply.strip()


async def interactive_session(api_base_url=None, api_key=None, langfuse_config=None, mcp_config=None, provider=None):
    """
    Main interaction loop for the Smart Agent CLI.
    Type 'exit' or 'quit' to end the session.
    """
    print(
        f"{Fore.GREEN}{Style.BRIGHT}=== Smart Agent CLI ==={Style.RESET_ALL}"
    )
    print(
        f"{Fore.GREEN}{Style.BRIGHT}Type 'exit' or 'quit' to terminate the session.{Style.RESET_ALL}\n"
    )

    # Initialize the chat history with a fresh system prompt.
    history = [{"role": "system", "content": PromptGenerator.create_system_prompt()}]

    while True:
        user_input = input(f"{Fore.YELLOW}You: {Style.RESET_ALL}").strip()
        if user_input.lower() in {"exit", "quit"}:
            print(f"{Fore.RED}{Style.BRIGHT}Goodbye!{Style.RESET_ALL}")
            break

        # Replace/update the system prompt (first item) every time before processing the history.
        history[0] = {"role": "system", "content": PromptGenerator.create_system_prompt()}

        # Append the user's message to the history.
        history.append({"role": "user", "content": user_input})
        # Process the complete conversation history.
        assistant_response = await ask(history, api_base_url, api_key, langfuse_config, mcp_config, provider)
        # Append the assistant's response to maintain context.
        history.append({"role": "assistant", "content": assistant_response})


@click.group()
def cli():
    """Smart Agent CLI - AI agent with reasoning and tool use capabilities."""
    pass


@cli.command()
@click.option('--api-base-url', help='OpenAI API base URL')
@click.option('--api-key', help='OpenAI API key')
@click.option('--langfuse-public-key', help='Langfuse public key')
@click.option('--langfuse-secret-key', help='Langfuse secret key')
@click.option('--langfuse-host', default='https://cloud.langfuse.com', help='Langfuse host URL')
@click.option('--mcp-think-tool-repo', help='MCP think tool repository')
@click.option('--mcp-search-tool-repo', help='MCP search tool repository')
@click.option('--mcp-python-tool-url', help='MCP Python tool URL')
@click.option('--provider', type=click.Choice(['anthropic', 'bedrock', 'proxy', 'openai']), default='openai', help='Claude API provider')
def chat(api_base_url, api_key, langfuse_public_key, langfuse_secret_key, langfuse_host, mcp_think_tool_repo, mcp_search_tool_repo, mcp_python_tool_url, provider):
    """Start an interactive chat session with the Smart Agent."""
    langfuse_config = None
    if langfuse_public_key and langfuse_secret_key:
        langfuse_config = {
            "public_key": langfuse_public_key,
            "secret_key": langfuse_secret_key,
            "host": langfuse_host
        }
    
    mcp_config = None
    if mcp_think_tool_repo and mcp_search_tool_repo and mcp_python_tool_url:
        mcp_config = {
            "think_tool_repo": mcp_think_tool_repo,
            "search_tool_repo": mcp_search_tool_repo,
            "python_tool_url": mcp_python_tool_url
        }
    
    asyncio.run(interactive_session(api_base_url, api_key, langfuse_config, mcp_config, provider))


def main():
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
