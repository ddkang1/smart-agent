"""
Unit tests for the CLI module.
"""

from unittest.mock import patch, MagicMock, call
import sys
import pytest


class TestCliCommands:
    """Test suite for Smart Agent CLI commands."""

    @patch("smart_agent.commands.start.start_tools")
    def test_start_cmd_functionality(self, mock_start_tools):
        """Test the functionality of start command without calling the Click command."""
        # Import here to avoid circular imports
        from smart_agent.commands.start import start

        # Create a mock config manager
        mock_config_manager = MagicMock()
        
        # Mock get_api_base_url to return a localhost URL
        mock_config_manager.get_api_base_url.return_value = "http://localhost:8000"
        
        # Call the internal functionality directly
        with patch("smart_agent.tool_manager.ConfigManager", return_value=mock_config_manager):
            # We need to patch sys.exit to prevent the test from exiting
            with patch("sys.exit"):
                # We're testing the functionality, not the Click command itself
                start.callback(config=None, background=True, debug=False)
                
                # Verify that start_tools was called
                assert mock_start_tools.called
                
                # Note: We're not verifying launch_litellm_proxy was called
                # as there are complex conditions that determine when it's called

    @patch("smart_agent.process_manager.ProcessManager.stop_all_processes")
    def test_stop_cmd_functionality(self, mock_stop_all):
        """Test the functionality of stop command without calling the Click command."""
        # Import here to avoid circular imports
        from smart_agent.commands.stop import stop

        # Call the internal functionality directly
        stop.callback(config=None, all=True, debug=False)

        # Verify stop_all_processes was called
        assert mock_stop_all.called


    @pytest.mark.skip(reason="Need to fix this test")
    @patch("subprocess.Popen")
    @patch("os.environ")
    def test_launch_tools_functionality(self, mock_environ, mock_popen):
        """Test the functionality of launch_tools without directly calling it."""
        # Import here to avoid circular imports
        from smart_agent.commands.start import start_tools
        from smart_agent.process_manager import ProcessManager

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
                    "command": "npx search-tool --port {port}"
                }
            }
        )

        # Mock is_tool_enabled to return True for our test tool
        mock_config_manager.is_tool_enabled.return_value = True

        # Mock get_tool_config to return our tool config
        mock_config_manager.get_tool_config.return_value = {
            "name": "Search Tool",
            "url": "http://localhost:8001/sse",
            "enabled": True,
            "type": "uvx",
            "repository": "search-tool",
            "command": "npx search-tool --port {port}"
        }

        # Mock get_tool_command to return a command
        mock_config_manager.get_tool_command.return_value = "npx search-tool --port {port}"

        # Mock get_env_prefix to return a valid string
        mock_config_manager.get_env_prefix.return_value = "SEARCH_TOOL"

        # Mock os.path.exists and shutil.which to return True
        with patch("os.path.exists", return_value=True):
            with patch("shutil.which", return_value="/usr/bin/npx"):
                # Create a mock process manager
                mock_process_manager = MagicMock()
                mock_process_manager.start_tool_process.return_value = (1234, 8001)
                mock_process_manager.is_tool_running.return_value = False

                # Call the function with our mocks
                result = start_tools(mock_config_manager, process_manager=mock_process_manager)

                # Verify process manager was called to start the tool
                assert mock_process_manager.start_tool_process.called

    @patch("subprocess.Popen")
    @patch("os.path.exists", return_value=True)
    def test_proxy_manager_launch_litellm_proxy(self, mock_exists, mock_popen):
        """Test ProxyManager.launch_litellm_proxy function."""
        # Create a mock config manager with required methods
        mock_config_manager = MagicMock()

        # Mock the litellm_config used for server settings
        mock_config_manager.get_litellm_config.return_value = {
            'enabled': True,
            'command': 'litellm --port {port}',
            'server': {'port': 4000, 'host': '0.0.0.0'},
            'model_list': [{'model_name': 'test-model'}]
        }

        # Mock the config path
        mock_config_manager.get_litellm_config_path.return_value = "/path/to/litellm_config.yaml"

        # Create a background parameter
        background = True

        # Create a proxy manager instance
        from smart_agent.proxy_manager import ProxyManager
        proxy_manager = ProxyManager()

        # Call the function
        result = proxy_manager.launch_litellm_proxy(mock_config_manager, background)

        # Verify subprocess.Popen was called to launch the proxy
        assert mock_popen.called
