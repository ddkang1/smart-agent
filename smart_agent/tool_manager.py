"""
Tool management for Smart Agent.
Handles loading, configuration, and initialization of MCP tools from YAML configuration.
"""

import os
import yaml
from typing import Dict, List, Any, Optional
from pathlib import Path

from agents import MCPServerSse


class ToolManager:
    """
    Manages MCP tools for Smart Agent based on YAML configuration.
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize the ToolManager.
        
        Args:
            config_path: Path to the YAML configuration file. If None, will look in default locations.
        """
        self.tools_config = {}
        self.mcp_servers = []
        self.config_path = config_path
        self._load_config()
    
    def _load_config(self) -> None:
        """Load tool configuration from YAML file."""
        # Default locations to check for config file
        search_paths = [
            self.config_path,
            os.path.join(os.getcwd(), "config", "tools.yaml"),
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "tools.yaml"),
            os.path.expanduser("~/.config/smart-agent/tools.yaml"),
        ]
        
        # Filter out None values
        search_paths = [p for p in search_paths if p]
        
        # Try to load from each path
        for path in search_paths:
            if os.path.exists(path):
                try:
                    with open(path, 'r') as f:
                        self.tools_config = yaml.safe_load(f)
                    print(f"Loaded tool configuration from {path}")
                    return
                except Exception as e:
                    print(f"Error loading configuration from {path}: {e}")
        
        # If we get here, no config file was found
        print("No tool configuration file found. Using default configuration.")
        self.tools_config = {"tools": {}}
    
    def get_tool_config(self, tool_id: str) -> Dict:
        """
        Get configuration for a specific tool.
        
        Args:
            tool_id: The ID of the tool to get configuration for
            
        Returns:
            Tool configuration dictionary
        """
        return self.tools_config.get("tools", {}).get(tool_id, {})
    
    def get_all_tools(self) -> Dict:
        """
        Get configuration for all tools.
        
        Returns:
            Dictionary of all tool configurations
        """
        return self.tools_config.get("tools", {})
    
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
        env_prefix = tool_config.get("env_prefix", f"MCP_{tool_id.upper()}")
        env_enabled = os.getenv(f"ENABLE_{tool_id.upper()}")
        if env_enabled is not None:
            return env_enabled.lower() == "true"
        
        # Fall back to configuration
        return tool_config.get("enabled", False)
    
    def get_tool_url(self, tool_id: str) -> str:
        """
        Get the URL for a tool.
        
        Args:
            tool_id: The ID of the tool to get the URL for
            
        Returns:
            Tool URL
        """
        tool_config = self.get_tool_config(tool_id)
        env_prefix = tool_config.get("env_prefix", f"MCP_{tool_id.upper()}")
        
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
        env_prefix = tool_config.get("env_prefix", f"MCP_{tool_id.upper()}")
        
        # Check environment variable override
        env_repo = os.getenv(f"{env_prefix}_REPO")
        if env_repo:
            return env_repo
        
        # Fall back to configuration
        return tool_config.get("repository", "")
    
    def initialize_tools(self) -> List[Any]:
        """
        Initialize all enabled tools.
        
        Returns:
            List of initialized MCP server objects
        """
        self.mcp_servers = []
        
        for tool_id, tool_config in self.get_all_tools().items():
            if self.is_tool_enabled(tool_id):
                tool_url = self.get_tool_url(tool_id)
                
                if tool_config.get("type") == "sse":
                    tool_server = MCPServerSse(params={"url": tool_url})
                    self.mcp_servers.append(tool_server)
                    print(f"Initialized {tool_config.get('name', tool_id)} at {tool_url}")
                else:
                    print(f"Unsupported tool type for {tool_id}: {tool_config.get('type')}")
        
        return self.mcp_servers
    
    def get_mcp_servers(self) -> List[Any]:
        """
        Get all initialized MCP servers.
        
        Returns:
            List of MCP server objects
        """
        return self.mcp_servers
