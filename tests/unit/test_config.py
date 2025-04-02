"""
Unit tests for the Config module.
"""

import os
import pytest
import yaml
from unittest.mock import patch, mock_open

from smart_agent.config import Config


class TestConfig:
    """Test suite for the Config class."""

    def test_load_config(self, mock_config_dir):
        """Test loading configuration from YAML files."""
        with patch("smart_agent.config.CONFIG_DIR", mock_config_dir):
            config = Config()
            config.load()

            # Verify model config
            assert config.get_model_name() == "gpt-4"
            assert config.get_model_temperature() == 1.0
            assert config.get_model_max_tokens() == 4000

            # Verify tools config
            tools = config.get_tools()
            assert "search_tool" in tools
            assert "python_repl" in tools
            assert tools["search_tool"]["url"] == "http://localhost:8001/sse"

            # Verify LiteLLM config
            litellm_config = config.get_litellm_config()
            assert len(litellm_config.get("model_list", [])) > 0
            assert litellm_config.get("server", {}).get("port") == 4000

    def test_save_config(self, temp_dir):
        """Test saving configuration to YAML files."""
        config_dir = os.path.join(temp_dir, "config")
        os.makedirs(config_dir, exist_ok=True)

        with patch("smart_agent.config.CONFIG_DIR", config_dir):
            config = Config()

            # Set config values
            config.set_model_config(
                {"name": "test-model", "temperature": 0.5, "max_tokens": 2000}
            )

            config.set_tools_config(
                {
                    "test_tool": {
                        "name": "test_tool",
                        "type": "test",
                        "enabled": True,
                        "url": "http://localhost:9000/sse",
                    }
                }
            )

            config.set_litellm_config(
                {
                    "model_list": [
                        {
                            "model_name": "test-model",
                            "litellm_params": {
                                "model": "test/test-model",
                                "api_key": "${TEST_API_KEY}",
                            },
                        }
                    ]
                }
            )

            # Save config
            config.save()

            # Verify files were created
            assert os.path.exists(os.path.join(config_dir, "config.yaml"))
            assert os.path.exists(os.path.join(config_dir, "tools.yaml"))
            assert os.path.exists(os.path.join(config_dir, "litellm_config.yaml"))

            # Verify content
            with open(os.path.join(config_dir, "config.yaml"), "r") as f:
                config_data = yaml.safe_load(f)
                assert config_data["model"]["name"] == "test-model"

            with open(os.path.join(config_dir, "tools.yaml"), "r") as f:
                tools_data = yaml.safe_load(f)
                assert "test_tool" in tools_data["tools"]

    def test_get_enabled_tools(self, mock_config_dir):
        """Test getting only enabled tools."""
        with patch("smart_agent.config.CONFIG_DIR", mock_config_dir):
            config = Config()
            config.load()

            # Get all tools including disabled ones
            all_tools = config.get_tools()

            # Disable one tool
            all_tools["search_tool"]["enabled"] = False
            config.set_tools_config(all_tools)

            # Get only enabled tools
            enabled_tools = config.get_enabled_tools()

            # Verify only enabled tools are returned
            assert "python_repl" in enabled_tools
            assert "search_tool" not in enabled_tools

    def test_missing_config_files(self):
        """Test behavior with missing config files."""
        with patch("smart_agent.config.CONFIG_DIR", "/nonexistent/path"):
            with patch("os.path.exists", return_value=False):
                config = Config()
                config.load()

                # Should use defaults
                assert config.get_model_name() is not None
                assert isinstance(config.get_tools(), dict)
