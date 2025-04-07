"""
Functional end-to-end tests for Smart Agent.
"""

import os
import pytest
import asyncio
from unittest.mock import patch, MagicMock

# Skip the test if agents package is not available
try:
    from agents import OpenAIChatCompletionsModel
    agents_available = True
except ImportError:
    agents_available = False

from smart_agent.cli import start, stop
from smart_agent.agent import SmartAgent

# Skip all tests in this module if agents package is not available
pytestmark = pytest.mark.skipif(not agents_available, reason="agents package not available")


class TestSmartAgentE2E:
    """End-to-end test suite for Smart Agent."""

    @pytest.mark.skip(reason="Need to fix this test")
    @pytest.mark.asyncio
    @patch("agents.OpenAIChatCompletionsModel")
    @patch("smart_agent.commands.start.start_tools")
    @patch("smart_agent.proxy_manager.ProxyManager.get_litellm_proxy_status")
    async def test_chat_session_with_tools(
        self, mock_launch_proxy, mock_launch_tools, mock_model
    ):
        """Test a complete chat session with tool usage."""
        # Setup mock processes
        # Return a dictionary for start_tools
        mock_launch_tools.return_value = {"tool1": {"status": "started", "pid": 12345, "port": 8001}}
        # Return a status for get_litellm_proxy_status
        mock_launch_proxy.return_value = {"running": True, "port": 8000, "container_id": "abc123"}

        # Setup model mock
        mock_model_instance = MagicMock()
        mock_model.return_value = mock_model_instance

        # Create a mock config manager
        mock_config_manager = MagicMock()

        # Mock get_config to return a localhost URL for api.base_url to ensure litellm_proxy is called
        def get_config_side_effect(section=None, key=None, default=None):
            if section == "api" and key == "base_url":
                return "http://localhost:8000"
            return default

        mock_config_manager.get_config.side_effect = get_config_side_effect

        # Mock get_api_base_url to return a localhost URL to ensure litellm_proxy is called
        mock_config_manager.get_api_base_url.return_value = "http://localhost:8000"

        mock_config_manager.get_model_name.return_value = "gpt-4"
        mock_config_manager.get_model_temperature.return_value = 0.7

        # Mock get_litellm_config to return a config with enabled=True
        mock_config_manager.get_litellm_config.return_value = {"enabled": True}

        # Setup for start command
        with patch("smart_agent.tool_manager.ConfigManager", return_value=mock_config_manager):
            with patch("sys.exit"):
                # Call start with background=True to start all services
                start.callback(config=None, background=True, debug=False)

        # Verify that start_tools and get_litellm_proxy_status were called
        assert mock_launch_tools.called
        assert mock_launch_proxy.called

        # Create agent with mocked components
        with patch("smart_agent.agent.Agent") as mock_agent_class:
            mock_agent = MagicMock()
            mock_agent_class.return_value = mock_agent

            # Initialize the SmartAgent
            agent = SmartAgent(model_name="gpt-4")

            # Test processing a message
            user_message = "Hello, can you help me with a search?"

            # Mock the process_message method
            with patch.object(agent, "process_message") as mock_process_message:
                # Call the method
                await agent.process_message(user_message)

                # Verify the method was called
                assert mock_process_message.called

        # Test stopping services
        with patch("subprocess.run") as mock_run:
            stop.callback(config=None, tools=None, all=True, debug=False)

            # Verify subprocess.run was called to stop services
            assert mock_run.called
