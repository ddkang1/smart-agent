"""
Unit tests for the CLI module.
"""
import os
import pytest
from unittest.mock import patch, MagicMock, call

from smart_agent.cli import (
    start_cmd, stop_cmd, chat_cmd, setup_cmd, 
    launch_tools, stop_tools, launch_litellm_proxy
)


class TestCliCommands:
    """Test suite for Smart Agent CLI commands."""

    @patch("smart_agent.cli.launch_tools")
    @patch("smart_agent.cli.launch_litellm_proxy")
    def test_start_cmd_all(self, mock_launch_proxy, mock_launch_tools):
        """Test start_cmd with --all flag."""
        start_cmd(tools=True, proxy=True, all=True)
        mock_launch_tools.assert_called_once()
        mock_launch_proxy.assert_called_once()

    @patch("smart_agent.cli.launch_tools")
    @patch("smart_agent.cli.launch_litellm_proxy")
    def test_start_cmd_tools_only(self, mock_launch_proxy, mock_launch_tools):
        """Test start_cmd with --tools flag only."""
        start_cmd(tools=True, proxy=False, all=False)
        mock_launch_tools.assert_called_once()
        mock_launch_proxy.assert_not_called()

    @patch("smart_agent.cli.launch_tools")
    @patch("smart_agent.cli.launch_litellm_proxy")
    def test_start_cmd_proxy_only(self, mock_launch_proxy, mock_launch_tools):
        """Test start_cmd with --proxy flag only."""
        start_cmd(tools=False, proxy=True, all=False)
        mock_launch_tools.assert_not_called()
        mock_launch_proxy.assert_called_once()
    
    @patch("smart_agent.cli.stop_tools")
    @patch("smart_agent.cli.stop_litellm_proxy")
    def test_stop_cmd_all(self, mock_stop_proxy, mock_stop_tools):
        """Test stop_cmd with --all flag."""
        stop_cmd(tools=True, proxy=True, all=True)
        mock_stop_tools.assert_called_once()
        mock_stop_proxy.assert_called_once()
    
    @patch("smart_agent.cli.os.path.exists")
    @patch("smart_agent.cli.shutil.copyfile")
    @patch("builtins.input", return_value="y")
    def test_setup_cmd_quick(self, mock_input, mock_copyfile, mock_exists):
        """Test setup_cmd with --quick flag."""
        mock_exists.return_value = False
        
        with patch("smart_agent.cli.os.makedirs"):
            setup_cmd(quick=True, config=False, tools=False, litellm=False)
        
        # Should copy example files without prompting
        assert mock_copyfile.call_count == 3
        assert mock_input.call_count == 0
    
    @patch("smart_agent.cli.subprocess.Popen")
    @patch("smart_agent.cli.ToolManager")
    def test_launch_tools(self, mock_tool_manager, mock_popen, mock_config):
        """Test launching tools."""
        mock_tool_instance = MagicMock()
        mock_tool_manager.return_value = mock_tool_instance
        mock_tool_instance.get_enabled_tools.return_value = {
            "tool1": {"name": "tool1", "url": "http://localhost:8000", "launch_cmd": "uvx"},
            "tool2": {"name": "tool2", "url": "http://localhost:8001", "launch_cmd": "docker"}
        }
        
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_popen.return_value = mock_process
        
        launch_tools()
        
        # Should launch both tools
        assert mock_popen.call_count == 2
    
    @patch("smart_agent.cli.subprocess.run")
    def test_stop_tools(self, mock_run, mock_config):
        """Test stopping tools."""
        stop_tools()
        
        # Should attempt to kill processes and stop Docker containers
        assert mock_run.call_count > 0
    
    @patch("smart_agent.cli.subprocess.run")
    @patch("smart_agent.cli.os.path.exists")
    def test_launch_litellm_proxy(self, mock_exists, mock_run, mock_config):
        """Test launching LiteLLM proxy."""
        mock_exists.return_value = True  # Config file exists
        
        launch_litellm_proxy()
        
        # Should check for Docker and launch container
        assert mock_run.call_count >= 2
        
        # Find the docker run command
        docker_calls = [call for call in mock_run.call_args_list 
                       if call[0][0][0] == "docker" and call[0][0][1] == "run"]
        assert len(docker_calls) == 1
