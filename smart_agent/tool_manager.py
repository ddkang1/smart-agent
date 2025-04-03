"""
Configuration management for Smart Agent.
Handles loading, configuration, and initialization of tools from YAML configuration.
"""

import os
import yaml
from typing import Dict, List, Optional, Any
import importlib
import subprocess
import sys
from pathlib import Path


class ConfigManager:
    """
    Manages configuration for Smart Agent based on YAML configuration.
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize the ConfigManager.

        Args:
            config_path: Path to the YAML configuration file. If None, will look in default locations.
        """
        self.config = {}
        self.config_path = config_path
        self.tools_config = {}
        self.litellm_config = {}
        self._load_config()

    def _load_config(self):
        """
        Load configuration from YAML file.
        """
        # Default config paths to check
        default_paths = [
            self.config_path,
            os.path.join(os.getcwd(), "config", "config.yaml"),
            os.path.join(os.getcwd(), "config.yaml"),
            os.path.expanduser("~/.config/smart-agent/config.yaml"),
        ]

        # Filter out None values
        default_paths = [p for p in default_paths if p is not None]

        # Try to load from each path
        for path in default_paths:
            if os.path.exists(path):
                try:
                    with open(path, "r") as f:
                        self.config = yaml.safe_load(f) or {}
                    print(f"Loaded configuration from {path}")

                    # Load tools configuration
                    tools_config_path = self.config.get("tools_config")
                    if tools_config_path:
                        if not os.path.isabs(tools_config_path):
                            # Make path relative to the config file
                            config_dir = os.path.dirname(path)
                            tools_config_path = os.path.join(
                                config_dir, tools_config_path
                            )

                        if os.path.exists(tools_config_path):
                            with open(tools_config_path, "r") as f:
                                self.tools_config = yaml.safe_load(f).get("tools", {})
                            print(
                                f"Loaded tools configuration from {tools_config_path}"
                            )
                        else:
                            print(
                                f"Warning: Tools configuration file not found: {tools_config_path}"
                            )
                            
                    # Load LiteLLM configuration if available
                    self.litellm_config = self._load_litellm_config()

                    return
                except Exception as e:
                    print(f"Error loading configuration from {path}: {e}")

        print("Warning: No configuration file found. Using default settings.")
        self.config = {}

    def _load_litellm_config(self):
        """
        Load LiteLLM configuration from the path specified in the config.
        
        Returns:
            Dictionary containing LiteLLM configuration
        """
        litellm_config_path = self.config.get("llm", {}).get("config_file")
        if not litellm_config_path:
            return {}
            
        # Handle relative paths
        if not os.path.isabs(litellm_config_path):
            litellm_config_path = os.path.join(os.path.dirname(self.config_path), litellm_config_path)
            
        if not os.path.exists(litellm_config_path):
            print(f"Warning: LiteLLM config file not found at {litellm_config_path}")
            return {}
            
        try:
            with open(litellm_config_path, "r") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"Error loading LiteLLM config: {e}")
            return {}

    def get_config(
        self,
        section: Optional[str] = None,
        key: Optional[str] = None,
        default: Any = None,
    ) -> Any:
        """
        Get configuration value.

        Args:
            section: Configuration section (e.g., 'api', 'model')
            key: Configuration key within section
            default: Default value if not found

        Returns:
            Configuration value or default
        """
        if section is None:
            return self.config

        section_data = self.config.get(section, {})

        if key is None:
            return section_data

        return section_data.get(key, default)

    def get_tool_config(self, tool_id: str) -> Dict:
        """
        Get configuration for a specific tool.

        Args:
            tool_id: The ID of the tool to get configuration for

        Returns:
            Tool configuration dictionary
        """
        return self.tools_config.get(tool_id, {})

    def get_all_tools(self) -> Dict:
        """
        Get configuration for all tools.

        Returns:
            Dictionary of all tool configurations
        """
        return self.tools_config

    def is_tool_enabled(self, tool_id: str) -> bool:
        """
        Check if a tool is enabled.

        Args:
            tool_id: The ID of the tool to check

        Returns:
            True if the tool is enabled, False otherwise
        """
        tool_config = self.get_tool_config(tool_id)

        # Check environment variable override
        env_enabled = os.getenv(f"ENABLE_{tool_id.upper()}")
        if env_enabled is not None:
            return env_enabled.lower() == "true"

        # Fall back to configuration
        return tool_config.get("enabled", False)

    def get_env_prefix(self, tool_id: str) -> str:
        """
        Get the environment variable prefix for a tool.

        Args:
            tool_id: The ID of the tool

        Returns:
            Environment variable prefix
        """
        tool_config = self.get_tool_config(tool_id)
        # Use env_prefix if provided, otherwise generate from tool_id
        return tool_config.get("env_prefix", f"SMART_AGENT_TOOL_{tool_id.upper()}")

    def get_tool_url(self, tool_id: str) -> str:
        """
        Get the URL for a tool.

        Args:
            tool_id: The ID of the tool to get the URL for

        Returns:
            Tool URL
        """
        tool_config = self.get_tool_config(tool_id)
        env_prefix = self.get_env_prefix(tool_id)

        # Check environment variable override
        env_url = os.getenv(f"{env_prefix}_URL")
        if env_url:
            return env_url

        # Fall back to configuration
        return tool_config.get("url", "")

    def get_tool_repository(self, tool_id: str) -> str:
        """
        Get the repository for a tool.

        Args:
            tool_id: The ID of the tool to get the repository for

        Returns:
            Tool repository
        """
        tool_config = self.get_tool_config(tool_id)
        env_prefix = self.get_env_prefix(tool_id)

        # Check environment variable override
        env_repo = os.getenv(f"{env_prefix}_REPO")
        if env_repo:
            return env_repo

        # Fall back to configuration
        return tool_config.get("repository", "")

    def initialize_tools(self) -> List:
        """
        Initialize all enabled tools.

        Returns:
            List of initialized server objects
        """
        servers = []

        for tool_id, tool_config in self.tools_config.items():
            if not self.is_tool_enabled(tool_id):
                continue

            tool_name = tool_config.get("name", tool_id)
            print(f"Initializing {tool_name}...")

            # TODO: Implement tool initialization

        return servers

    def get_api_key(self) -> str:
        """
        Get API key.

        Returns:
            API key
        """
        # Check environment variables first
        env_key = os.getenv("OPENAI_API_KEY")
        if env_key:
            return env_key

        # Fall back to configuration
        return self.get_config("api", "api_key", "")

    def get_api_base_url(self, provider=None) -> str:
        """
        Get API base URL.

        Args:
            provider: API provider

        Returns:
            API base URL
        """
        # Check environment variables first
        env_url = os.getenv("OPENAI_API_BASE")
        if env_url:
            return env_url

        # Fall back to configuration
        return self.get_config("api", "base_url", "http://0.0.0.0:4000")

    def get_model_name(self) -> str:
        """
        Get the model name to use.

        Returns:
            Model name
        """
        # Check environment variables first
        env_model = os.environ.get("SMART_AGENT_MODEL")
        if env_model:
            return env_model

        # Fall back to configuration
        return self.get_config("model", "name", "claude-3-7-sonnet-20240229")

    def get_model_temperature(self) -> float:
        """
        Get the model temperature to use.

        Returns:
            Model temperature
        """
        # Check environment variables first
        env_temp = os.environ.get("SMART_AGENT_TEMPERATURE")
        if env_temp:
            try:
                return float(env_temp)
            except (ValueError, TypeError):
                pass

        # Fall back to configuration
        return self.get_config("model", "temperature", 0.0)

    def get_log_level(self) -> str:
        """
        Get the log level to use.

        Returns:
            Log level
        """
        # Check environment variable first
        env_level = os.getenv("SMART_AGENT_LOG_LEVEL")
        if env_level:
            return env_level

        # Fall back to configuration
        return self.get_config("logging", "level", "INFO")

    def get_log_file(self) -> Optional[str]:
        """
        Get the log file path to use.

        Returns:
            Log file path or None
        """
        # Check environment variable first
        env_file = os.getenv("SMART_AGENT_LOG_FILE")
        if env_file:
            return env_file

        # Fall back to configuration
        return self.get_config("logging", "file", None)

    def get_langfuse_config(self) -> Dict:
        """
        Get the Langfuse configuration.

        Returns:
            Langfuse configuration dictionary
        """
        config = self.get_config("monitoring", "langfuse", {})

        # Check environment variables
        env_public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
        env_secret_key = os.getenv("LANGFUSE_SECRET_KEY")
        env_host = os.getenv("LANGFUSE_HOST")

        if env_public_key:
            config["public_key"] = env_public_key
        if env_secret_key:
            config["secret_key"] = env_secret_key
        if env_host:
            config["host"] = env_host

        # Set enabled flag if keys are present
        if "public_key" in config and "secret_key" in config:
            config["enabled"] = True

        return config

    def get_llm_config(self) -> Dict:
        """
        Get the LLM configuration combining info from both config.yaml and litellm_config.yaml.
        
        Returns:
            Dictionary with complete LLM configuration
        """
        # First check for legacy model configuration
        if "model" in self.config and "name" in self.config.get("model", {}):
            return {
                "name": self.config.get("model", {}).get("name"),
                "temperature": self.config.get("model", {}).get("temperature", 1.0),
                "base_url": self.config.get("api", {}).get("base_url"),
                "api_key": self.config.get("api", {}).get("api_key"),
            }
            
        # Handle new style configuration referencing litellm_config.yaml
        llm_config = self.config.get("llm", {})
        preferred_model = llm_config.get("preferred_model")
        temperature = llm_config.get("temperature", 1.0)
        
        # Get all unique model names from the model_list
        all_models = set()
        for model in self.litellm_config.get("model_list", []):
            if model.get("model_name"):
                all_models.add(model.get("model_name"))
        
        # Find the model in litellm_config.yaml
        model_config = {}
        model_variant_configs = []
        
        # Find all variants of the preferred model
        for model in self.litellm_config.get("model_list", []):
            if model.get("model_name") == preferred_model:
                model_variant_configs.append(model)
                
        # Pick the first variant as the default
        if model_variant_configs:
            model_config = model_variant_configs[0]
                
        # If preferred model not found but we have models, use the first one
        if not model_config and self.litellm_config.get("model_list"):
            model_config = self.litellm_config.get("model_list")[0]
            
        # Get server config for base_url
        server_config = self.litellm_config.get("server", {})
        host = server_config.get("host", "0.0.0.0") 
        port = server_config.get("port", 4000)
        base_url = f"http://{host if host != '0.0.0.0' else 'localhost'}:{port}"
            
        return {
            "name": model_config.get("model_name"),
            "temperature": temperature,
            "base_url": base_url,
            "api_key": "sk-any-key",  # Default for local LiteLLM proxy
            "model_config": model_config,
            "all_models": list(all_models),
            "model_variants": model_variant_configs,
        }
        
    # Compatibility methods for existing code
    def get_api_key(self) -> str:
        """Get the API key for the LLM provider."""
        # Legacy method
        legacy_api_key = self.config.get("api", {}).get("api_key")
        if legacy_api_key:
            return legacy_api_key
            
        # New method using get_llm_config()
        return self.get_llm_config().get("api_key")
        
    def get_api_base_url(self) -> str:
        """Get the base URL for the LLM API."""
        # Legacy method
        legacy_base_url = self.config.get("api", {}).get("base_url")
        if legacy_base_url:
            return legacy_base_url
            
        # New method using get_llm_config()
        return self.get_llm_config().get("base_url")
        
    def get_model_name(self) -> str:
        """Get the name of the LLM model."""
        # Legacy method
        legacy_model_name = self.config.get("model", {}).get("name")
        if legacy_model_name:
            return legacy_model_name
            
        # New method using get_llm_config()
        return self.get_llm_config().get("name")
        
    def get_model_temperature(self) -> float:
        """Get the temperature setting for the LLM model."""
        # Legacy method
        legacy_temperature = self.config.get("model", {}).get("temperature")
        if legacy_temperature is not None:
            return legacy_temperature
            
        # New method using get_llm_config()
        return self.get_llm_config().get("temperature", 1.0)

    def get_litellm_config(self):
        """
        Get the full LiteLLM configuration.
        
        Returns:
            Dictionary containing LiteLLM configuration
        """
        return self.litellm_config
        
    def get_litellm_config_path(self):
        """
        Get the path to the LiteLLM configuration file.
        
        Returns:
            String path to the LiteLLM configuration file
        """
        litellm_config_path = self.config.get("llm", {}).get("config_file")
        if not litellm_config_path:
            # Default fallback path
            return os.path.join(os.getcwd(), "config", "litellm_config.yaml")
            
        # Handle relative paths
        if not os.path.isabs(litellm_config_path):
            # If the main config path is known, make path relative to it
            if self.config_path:
                config_dir = os.path.dirname(self.config_path)
                return os.path.join(config_dir, litellm_config_path)
            else:
                # Otherwise relative to current directory
                return os.path.join(os.getcwd(), litellm_config_path)
                
        return litellm_config_path


# For backward compatibility
class ToolManager(ConfigManager):
    """
    Legacy class for backward compatibility.
    """

    def __init__(self, config_path: Optional[str] = None):
        super().__init__(config_path)

    def get_mcp_servers(self) -> List:
        """
        Get all initialized MCP servers.

        Returns:
            List of MCP server objects
        """
        return []
