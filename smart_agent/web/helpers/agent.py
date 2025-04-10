"""Helper functions for agent creation and management."""

import logging
import chainlit as cl

logger = logging.getLogger(__name__)

async def create_agent(conversation_history, config_manager, mcp_servers):
    """Create an agent with the given configuration.
    
    Args:
        conversation_history: The conversation history
        config_manager: The configuration manager instance
        mcp_servers: The list of MCP servers to use
        
    Returns:
        The created agent or None if creation failed
    """
    from openai import AsyncOpenAI
    from agents import Agent, OpenAIChatCompletionsModel
    
    try:
        # Debug: Log what we're about to do
        logger.info(f"About to create agent with {len(mcp_servers)} MCP servers")
        for i, server in enumerate(mcp_servers):
            logger.info(f"Server {i+1}: {server.name}")
        
        # Initialize OpenAI client
        client = AsyncOpenAI(
            base_url=config_manager.get_api_base_url(), 
            api_key=config_manager.get_api_key()
        )
        
        # Create the model
        model = OpenAIChatCompletionsModel(
            model=config_manager.get_model_name(),
            openai_client=client,
        )
        logger.info("Model created successfully")
        
        # Create the agent with MCP servers
        logger.info("Creating agent...")
        agent = Agent(
            name="Assistant",
            instructions=conversation_history[0]["content"],
            model=model,
            mcp_servers=mcp_servers,
        )
        
        logger.info("Agent created successfully")
        return agent
    except Exception as e:
        logger.error(f"Error creating agent: {e}")
        await cl.Message(
            content=f"Error initializing agent: {e}",
            author="System"
        ).send()
        return None
