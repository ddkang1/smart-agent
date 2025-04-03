"""
Unit tests for the CLI module.
"""

from unittest.mock import patch, MagicMock, call
import sys

from smart_agent.cli import launch_litellm_proxy


class TestCliCommands:
    """Test suite for Smart Agent CLI commands."""

    @patch("smart_agent.cli.launch_tools")
    @patch("smart_agent.cli.launch_litellm_proxy")
    def test_start_cmd_functionality(self, mock_launch_proxy, mock_launch_tools):
        """Test the functionality of start command without calling the Click command."""
        # Import here to avoid circular imports
        from smart_agent.cli import start

        # Create a mock config manager
        mock_config_manager = MagicMock()

        # Mock get_config to return a localhost URL for api.base_url to ensure litellm_proxy is called
        def get_config_side_effect(section=None, key=None, default=None):
            if section == "api" and key == "base_url":
                return "http://localhost:8000"
            return default

        mock_config_manager.get_config.side_effect = get_config_side_effect

        # Call the internal functionality directly
        with patch("smart_agent.cli.ConfigManager", return_value=mock_config_manager):
            # We need to patch sys.exit to prevent the test from exiting
            with patch("sys.exit"):
                # We're testing the functionality, not the Click command itself
                start.callback(config=None, tools=True, proxy=True, all=True)
                # Verify that launch_tools was called
                assert mock_launch_tools.called
                # Verify that launch_litellm_proxy was called
                assert mock_launch_proxy.called

    @patch("subprocess.run")
    def test_stop_cmd_functionality(self, mock_run):
        """Test the functionality of stop command without calling the Click command."""
        # Import here to avoid circular imports
        from smart_agent.cli import stop

        # Call the internal functionality directly
        stop.callback(config=None, tools=True, proxy=True, all=True)

        # Verify subprocess.run was called to stop services
        assert mock_run.called

    @patch("builtins.input", return_value="y")
    @patch("os.path.exists")
    @patch("os.makedirs")
    @patch("builtins.open", new_callable=MagicMock)
    @patch("shutil.copy")
    def test_setup_cmd_functionality(
        self, mock_copy, mock_open, mock_makedirs, mock_exists, mock_input
    ):
        """Test the functionality of setup command without calling the Click command."""
        # Import here to avoid circular imports
        from smart_agent.cli import setup

        # Configure mock_exists to return True for example files
        def exists_side_effect(path):
            if "example" in str(path):
                return True
            return False

        mock_exists.side_effect = exists_side_effect

        # Mock the yaml.safe_load to return a simple dict
        with patch("yaml.safe_load", return_value={}):
            # We need to patch sys.exit to prevent the test from exiting
            with patch("sys.exit"):
                # Call the internal functionality directly with quick setup
                setup.callback(quick=True, config=True, tools=True, litellm=True, all=True)

        # Verify that files were checked and copied
        assert mock_exists.called
        assert mock_copy.called

    @patch("subprocess.Popen")
    @patch("os.environ")
    def test_launch_tools_functionality(self, mock_environ, mock_popen):
        """Test the functionality of launch_tools without directly calling it."""
        # Import here to avoid circular imports
        from smart_agent.cli import launch_tools

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
                    "type": "stdio",
                    "launch_cmd": "npx",
                    "repository": "search-tool",
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
            "type": "stdio",
            "launch_cmd": "npx",
            "repository": "search-tool",
        }

        # Mock get_env_prefix to return a valid string
        mock_config_manager.get_env_prefix.return_value = "SEARCH_TOOL"

        # Mock os.path.exists and shutil.which to return True
        with patch("os.path.exists", return_value=True):
            with patch("shutil.which", return_value="/usr/bin/npx"):
                # Call the function with our mock
                processes = launch_tools(mock_config_manager)

                # Verify subprocess.Popen was called to launch tools
                assert mock_popen.called

    @patch("subprocess.Popen")
    @patch("os.path.exists", return_value=True)
    def test_launch_litellm_proxy(self, mock_exists, mock_popen):
        """Test launch_litellm_proxy function."""
        # Create a mock config manager with required methods
        mock_config_manager = MagicMock()
        
        # Mock the litellm_config used for server settings
        mock_config_manager.get_litellm_config.return_value = {
            'server': {'port': 4000, 'host': '0.0.0.0'},
            'model_list': [{'model_name': 'test-model'}]
        }
        
        # Mock the config path
        mock_config_manager.get_litellm_config_path.return_value = "/path/to/litellm_config.yaml"

        # Call the function
        process = launch_litellm_proxy(mock_config_manager)

        # Verify subprocess.Popen was called to launch the proxy
        assert mock_popen.called
