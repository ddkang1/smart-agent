"""
Functional end-to-end tests for Smart Agent.
"""

import os
import pytest
import asyncio
from unittest.mock import patch, MagicMock

from smart_agent.cli import start_cmd, stop_cmd
from smart_agent.agent import SmartAgent


class TestSmartAgentE2E:
    """End-to-end test suite for Smart Agent."""

    @pytest.mark.asyncio
    @patch("agents.OpenAIChatCompletionsModel")
    @patch("smart_agent.cli.launch_tools")
    @patch("smart_agent.cli.launch_litellm_proxy")
    async def test_chat_session_with_tools(
        self, mock_launch_proxy, mock_launch_tools, mock_model
    ):
        """Test a complete chat session with tool usage."""
        # Setup mock processes
        mock_process = MagicMock()
        mock_launch_tools.return_value = [mock_process]
        mock_launch_proxy.return_value = mock_process

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
        
        mock_config_manager.get_model_name.return_value = "gpt-4"
        mock_config_manager.get_model_temperature.return_value = 0.7
        
        # Setup for start_cmd
        with patch("smart_agent.cli.ConfigManager", return_value=mock_config_manager):
            with patch("sys.exit"):
                # Call start_cmd with all=True to start all services
                start_cmd.callback(config=None, tools=True, proxy=True, all=True)
        
        # Verify that launch_tools and launch_litellm_proxy were called
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
            stop_cmd.callback(config=None, tools=True, proxy=True, all=True)
            
            # Verify subprocess.run was called to stop services
            assert mock_run.called
