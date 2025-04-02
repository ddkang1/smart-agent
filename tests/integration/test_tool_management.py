"""
Integration tests for tool management and interaction.
"""
import os
import pytest
from unittest.mock import patch, MagicMock

from smart_agent.cli import launch_tools, stop_tools
from smart_agent.agent import SmartAgent


class TestToolManagement:
    """Test suite for tool management integration."""
    
    @patch("smart_agent.cli.subprocess.Popen")
    @patch("smart_agent.agent.AsyncOpenAI")
    @patch("smart_agent.agent.get_tool_client")
    async def test_tool_launch_and_agent_integration(self, mock_get_tool_client, 
                                                   mock_openai, mock_popen, 
                                                   mock_config, mock_process):
        """Test launching tools and using them with the agent."""
        # Setup mocks
        mock_popen.return_value = mock_process
        
        # Setup mock tool client
        mock_tool_client = MagicMock()
        mock_tool_client.call_function.return_value = {"result": "tool result"}
        mock_get_tool_client.return_value = mock_tool_client
        
        # Launch tools
        tool_processes = launch_tools()
        assert len(tool_processes) > 0
        
        # Initialize agent
        agent = SmartAgent(mock_config)
        agent.load_tools()
        
        # Verify tools were loaded into agent
        assert len(agent.tools) > 0
        
        # Simulate a tool call
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        
        # Mock chat completion with tool call
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_123"
        mock_tool_call.type = "function"
        mock_tool_call.function.name = "search_tool"
        mock_tool_call.function.arguments = '{"query": "test query"}'
        
        mock_message = MagicMock()
        mock_message.role = "assistant"
        mock_message.content = None
        mock_message.tool_calls = [mock_tool_call]
        
        mock_completion = MagicMock()
        mock_completion.choices[0].message = mock_message
        mock_client.chat.completions.create.return_value = mock_completion
        
        # Test agent using tools
        messages = [{"role": "user", "content": "Use the search tool"}]
        response = await agent.process_messages(messages)
        
        # Verify tool was called
        mock_tool_client.call_function.assert_called_once()
        
        # Cleanup
        stop_tools()
    
    @patch("subprocess.run")
    @patch("subprocess.Popen")
    def test_tool_restart(self, mock_popen, mock_run, mock_config, mock_process):
        """Test stopping and restarting tools."""
        # Setup mocks
        mock_popen.return_value = mock_process
        
        # Launch tools
        tool_processes = launch_tools()
        assert len(tool_processes) > 0
        
        # Stop tools
        stop_tools()
        mock_run.assert_called()
        
        # Relaunch tools
        tool_processes = launch_tools()
        assert len(tool_processes) > 0
