"""
Unit tests for the ConfigManager module.
"""

import os
import yaml
from unittest.mock import patch, mock_open

from smart_agent.tool_manager import ConfigManager


class TestConfigManager:
    """Test suite for the ConfigManager class."""

    def test_load_config(self, mock_config_dir):
        """Test loading configuration from YAML files."""
        config_path = os.path.join(mock_config_dir, "config.yaml")
        config_manager = ConfigManager(config_path)

        # Verify that config was loaded
        assert config_manager.config is not None
        assert isinstance(config_manager.config, dict)

        # Test accessing configuration values
        # Note: These assertions will need to be adjusted based on your actual config structure
        if "model" in config_manager.config:
            assert "name" in config_manager.config["model"]

        # Verify tools config was loaded
        assert config_manager.tools_config is not None
        assert isinstance(config_manager.tools_config, dict)

    def test_default_config_path(self):
        """Test that the default config path is used when none is provided."""
        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data="{}")):
                config_manager = ConfigManager()
                # Verify that config was loaded
                assert config_manager.config is not None
                assert isinstance(config_manager.config, dict)

    def test_get_config(self, temp_dir):
        """Test getting configuration values."""
        config_path = os.path.join(temp_dir, "test_config.yaml")

        # Create a ConfigManager with mock config
        config_manager = ConfigManager(config_path)
        config_manager.config = {
            "model": {"name": "gpt-4", "temperature": 0.7},
            "api": {"provider": "openai"},
        }

        # Test getting config values
        assert config_manager.get_config("model", "name") == "gpt-4"
        assert config_manager.get_config("model", "temperature") == 0.7
        assert config_manager.get_config("api", "provider") == "openai"

        # Test getting default value for non-existent key
        assert (
            config_manager.get_config("model", "non_existent", "default") == "default"
        )

        # Test getting entire section
        assert config_manager.get_config("model") == {
            "name": "gpt-4",
            "temperature": 0.7,
        }

        # Test getting entire config
        assert config_manager.get_config() == config_manager.config

    def test_get_tool_config(self, mock_config_dir):
        """Test getting tool configuration."""
        config_path = os.path.join(mock_config_dir, "config.yaml")

        # Create a ConfigManager with mock tools config
        config_manager = ConfigManager(config_path)
        config_manager.tools_config = {
            "search_tool": {
                "name": "Search Tool",
                "url": "http://localhost:8001/sse",
                "enabled": True,
            },
            "python_repl": {
                "name": "Python REPL",
                "url": "http://localhost:8002/sse",
                "enabled": False,
            },
        }

        # Test getting specific tool config
        search_tool = config_manager.get_tool_config("search_tool")
        assert search_tool["name"] == "Search Tool"
        assert search_tool["url"] == "http://localhost:8001/sse"
        assert search_tool["enabled"] is True

        # Test getting all tools
        all_tools = config_manager.get_all_tools()
        assert "search_tool" in all_tools
        assert "python_repl" in all_tools

    def test_tool_status_methods(self, mock_config_dir):
        """Test methods for checking tool status."""
        config_path = os.path.join(mock_config_dir, "config.yaml")

        # Create a ConfigManager with mock tools config
        config_manager = ConfigManager(config_path)
        config_manager.tools_config = {
            "search_tool": {
                "name": "Search Tool",
                "url": "http://localhost:8001/sse",
                "enabled": True,
            },
            "python_repl": {
                "name": "Python REPL",
                "url": "http://localhost:8002/sse",
                "enabled": False,
            },
        }

        # Test is_tool_enabled method
        assert config_manager.is_tool_enabled("search_tool") is True
        assert config_manager.is_tool_enabled("python_repl") is False

        # Test get_tool_url method
        assert config_manager.get_tool_url("search_tool") == "http://localhost:8001/sse"
        assert config_manager.get_tool_url("python_repl") == "http://localhost:8002/sse"

    def test_model_config_methods(self, mock_config_dir):
        """Test methods for getting model configuration."""
        config_path = os.path.join(mock_config_dir, "config.yaml")

        # Create a ConfigManager with mock config
        config_manager = ConfigManager(config_path)
        config_manager.config = {"model": {"name": "gpt-4", "temperature": 0.7}}

        # Test getting model config
        assert config_manager.get_model_name() == "gpt-4"
        assert config_manager.get_model_temperature() == 0.7
