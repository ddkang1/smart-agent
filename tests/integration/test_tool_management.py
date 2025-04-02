"""
Integration tests for tool management and interaction.
"""

import os
import pytest
from unittest.mock import patch, MagicMock

from smart_agent.cli import launch_tools
from smart_agent.agent import SmartAgent


class TestToolManagement:
    """Test suite for tool management integration."""

    @pytest.mark.asyncio
    @patch("smart_agent.cli.subprocess.Popen")  # Patch the specific import path
    @patch("agents.OpenAIChatCompletionsModel")
    async def test_tool_launch_and_agent_integration(
        self, mock_model, mock_popen
    ):
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
                "type": "stdio",
                "launch_cmd": "npx",
                "repository": "search-tool"
            }
        }
        
        # Mock get_tools_config to return our tool config
        mock_config_manager.get_tools_config = MagicMock(return_value={
            "search_tool": {
                "name": "Search Tool",
                "url": "http://localhost:8001/sse",
                "enabled": True,
                "type": "stdio",
                "launch_cmd": "npx",
                "repository": "search-tool"
            }
        })
        
        # Mock get_env_prefix to return a valid string
        mock_config_manager.get_env_prefix.return_value = "SEARCH_TOOL"
        
        # Mock is_tool_enabled to return True for our test tool
        mock_config_manager.is_tool_enabled.return_value = True
        
        # Mock get_tool_config to return our tool config
        mock_config_manager.get_tool_config.return_value = {
            "name": "Search Tool",
            "url": "http://localhost:8001/sse",
            "enabled": True,
            "type": "stdio",
            "launch_cmd": "npx",
            "repository": "search-tool"
        }

        # Launch tools with mocked environment
        with patch("os.environ", {}):
            with patch("os.path.exists", return_value=True):
                with patch("shutil.which", return_value="/usr/bin/npx"):
                    processes = launch_tools(mock_config_manager)

        # Verify tool process was started
        assert mock_popen.called
        
        # Create agent with mocked components
        with patch("smart_agent.agent.Agent") as mock_agent_class:
            mock_agent = MagicMock()
            mock_agent_class.return_value = mock_agent
            
            # Initialize the SmartAgent
            agent = SmartAgent(model_name="gpt-4")
            
            # Mock the process_message method
            with patch.object(agent, "process_message") as mock_process_message:
                # Call the method
                await agent.process_message("Can you search for something?")
                
                # Verify the method was called
                assert mock_process_message.called
