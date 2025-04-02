"""
Global pytest fixtures and configuration for Smart Agent tests.
"""

import os
import pytest
import yaml
import tempfile
import shutil
from unittest.mock import Mock, patch

from smart_agent.config import Config


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def mock_config_dir(temp_dir):
    """Create a mock configuration directory with example configs."""
    config_dir = os.path.join(temp_dir, "config")
    os.makedirs(config_dir, exist_ok=True)

    # Create example config files
    with open(os.path.join(config_dir, "config.yaml"), "w") as f:
        yaml.dump(
            {
                "model": {"name": "gpt-4", "temperature": 1.0, "max_tokens": 4000},
                "logging": {"level": "INFO"},
            },
            f,
        )

    with open(os.path.join(config_dir, "tools.yaml"), "w") as f:
        yaml.dump(
            {
                "tools": {
                    "search_tool": {
                        "name": "search_tool",
                        "type": "search",
                        "enabled": True,
                        "url": "http://localhost:8001/sse",
                        "description": "A tool for web search",
                        "launch_cmd": "uvx",
                    },
                    "python_repl": {
                        "name": "python_repl",
                        "type": "repl",
                        "enabled": True,
                        "url": "http://localhost:8002/sse",
                        "description": "Python REPL for code execution",
                        "launch_cmd": "docker",
                        "repository": "python-repl-image",
                    },
                }
            },
            f,
        )

    with open(os.path.join(config_dir, "litellm_config.yaml"), "w") as f:
        yaml.dump(
            {
                "model_list": [
                    {
                        "model_name": "gpt-4",
                        "litellm_params": {
                            "model": "openai/gpt-4",
                            "api_key": "${OPENAI_API_KEY}",
                        },
                    }
                ],
                "server": {"port": 4000, "host": "0.0.0.0"},
            },
            f,
        )

    return config_dir


@pytest.fixture
def mock_config(mock_config_dir):
    """Create a mock Config object with test configuration."""
    with patch("smart_agent.config.CONFIG_DIR", mock_config_dir):
        config = Config()
        config.load()
        return config


@pytest.fixture
def mock_process():
    """Mock subprocess for tool processes."""
    process_mock = Mock()
    process_mock.pid = 12345
    process_mock.returncode = None
    process_mock.poll.return_value = None  # Process still running
    return process_mock


@pytest.fixture
def mock_tool_process(mock_process):
    """Mock tool process management."""
    with patch("subprocess.Popen", return_value=mock_process):
        yield mock_process


@pytest.fixture
def mock_docker():
    """Mock Docker CLI commands."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        yield mock_run
