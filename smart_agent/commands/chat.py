"""
Chat command implementation for the Smart Agent CLI.
"""

import asyncio
import logging
import click
import uuid
import datetime

# Set up logging
logger = logging.getLogger(__name__)

# Import Smart Agent components
from ..tool_manager import ConfigManager
from ..core.cli_agent import CLISmartAgent

# Re-export the CLISmartAgent as SmartAgent for backward compatibility
SmartAgent = CLISmartAgent

def generate_session_id():
    """
    Generate a unique session ID for the chat session.
    
    Returns:
        A string containing a unique session ID with timestamp
    """
    # Generate a UUID
    unique_id = str(uuid.uuid4())
    
    # Add timestamp for better traceability
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    
    # Combine timestamp and UUID to create a unique session ID
    return f"{timestamp}-{unique_id[:8]}"


@click.command()
@click.option(
    "--config",
    default=None,
    help="Path to configuration file",
)
@click.option(
    "--debug",
    is_flag=True,
    help="Enable debug logging",
)
@click.option(
    "--session-id",
    default=None,
    help="Reuse a specific session ID for memory continuity",
)
def chat(config, debug, session_id):
    """
    Start a chat session with the agent.

    Args:
        config: Path to configuration file
        debug: Enable debug logging
        session_id: Optional session ID to reuse for memory continuity
    """
    # Create configuration manager
    config_manager = ConfigManager(config_path=config)
    
    # Configure logging
    from ..cli import configure_logging
    configure_logging(config_manager, debug)
    
    # Use provided session ID or generate a new one
    if session_id:
        logger.info(f"Reusing existing session ID: {session_id}")
    else:
        session_id = generate_session_id()
        logger.info(f"Starting new chat session with ID: {session_id}")
    
    # Create and run the chat using the CLI-specific agent with the session ID
    chat_agent = CLISmartAgent(config_manager, session_id=session_id)
    asyncio.run(chat_agent.run_chat_loop())


if __name__ == "__main__":
    chat()