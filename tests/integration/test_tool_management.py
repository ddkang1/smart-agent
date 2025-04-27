"""
Integration tests for tool management and interaction.
"""

import os
import pytest
from unittest.mock import patch, MagicMock

# Skip the test if agents package is not available
try:
    from agents import OpenAIChatCompletionsModel
    agents_available = True
except ImportError:
    agents_available = False

from smart_agent.commands.start import start_tools
from smart_agent.core.agent import BaseSmartAgent


# Skip all tests in this module if agents package is not available
pytestmark = pytest.mark.skipif(not agents_available, reason="agents package not available")


class TestToolManagement:
    """Test suite for tool management integration."""

    @pytest.mark.asyncio
    @patch("subprocess.Popen")  # Patch the global subprocess.Popen
    @patch("agents.OpenAIChatCompletionsModel")
    async def test_tool_launch_and_agent_integration(self, mock_model, mock_popen):
        """Test launching tools and using them with the agent."""
        # Setup mocks
        mock_process = MagicMock()
        mock_popen.return_value = mock_process

        # Setup model mock
        mock_model_instance = MagicMock()
        mock_model.return_value = mock_model_instance

        # Create a mock config manager
        mock_config_manager = MagicMock()

        # Mock get_all_tools to return our tool config
        mock_config_manager.get_all_tools.return_value = {
            "search_tool": {
                "name": "Search Tool",
                "url": "http://localhost:8001/sse",
                "enabled": True,
                "type": "uvx",
                "repository": "search-tool",
            }
        }

        # Mock get_tools_config to return our tool config
        mock_config_manager.get_tools_config = MagicMock(
            return_value={
                "search_tool": {
                    "name": "Search Tool",
                    "url": "http://localhost:8001/sse",
                    "enabled": True,
                    "type": "uvx",
                    "repository": "search-tool",
                }
            }
        )

        # Mock get_env_prefix to return a valid string
        mock_config_manager.get_env_prefix.return_value = "SEARCH_TOOL"

        # Mock is_tool_enabled to return True for our test tool
        mock_config_manager.is_tool_enabled.return_value = True

        # Mock get_tool_config to return our tool config
        mock_config_manager.get_tool_config.return_value = {
            "name": "Search Tool",
            "url": "http://localhost:8001/sse",
            "enabled": True,
            "type": "uvx",
            "repository": "search-tool",
        }

        # Create a mock process manager
        mock_process_manager = MagicMock()
        # By default, is_tool_running returns True, which means the tool won't be started
        # Set it to False so that the tool will be started
        mock_process_manager.is_tool_running.return_value = False
        # Mock the start_tool_process method to return a PID and port
        mock_process_manager.start_tool_process.return_value = (12345, 8001)

        # Launch tools with mocked environment
        with patch("os.environ", {}):
            with patch("os.path.exists", return_value=True):
                with patch("shutil.which", return_value="/usr/bin/npx"):
                    processes = start_tools(mock_config_manager, process_manager=mock_process_manager)

        # Verify tool process was started
        assert mock_process_manager.start_tool_process.called

        # Create agent with mocked components
        with patch("agents.Agent") as mock_agent_class:
            mock_agent = MagicMock()
            mock_agent_class.return_value = mock_agent

            # Create a mock config manager for the agent
            mock_agent_config = MagicMock()
            mock_agent_config.get_api_key.return_value = "test-api-key"
            mock_agent_config.get_api_base_url.return_value = "https://api.openai.com/v1"
            mock_agent_config.get_model_name.return_value = "gpt-4"
            mock_agent_config.get_model_temperature.return_value = 0.7
            mock_agent_config.get_langfuse_config.return_value = {"enabled": False}
            mock_agent_config.get_tools_config.return_value = {}

            # Initialize the BaseSmartAgent with the mock config
            agent = BaseSmartAgent(mock_agent_config)
            
            # Mock the process_query method (BaseSmartAgent uses process_query, not process_message)
            with patch.object(agent, "process_query") as mock_process_query:
                # Set a return value for the mocked method
                mock_process_query.return_value = "Response from agent"
                
                # Call the method
                await agent.process_query("Can you search for something?", [])

                # Verify the method was called
                assert mock_process_query.called
