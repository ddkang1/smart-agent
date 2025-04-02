"""
Functional end-to-end tests for Smart Agent.
"""
import os
import pytest
import asyncio
from unittest.mock import patch, MagicMock

from smart_agent.cli import start_cmd, stop_cmd
from smart_agent.agent import SmartAgent, run_chat


class TestSmartAgentE2E:
    """End-to-end test suite for Smart Agent."""
    
    @pytest.mark.asyncio
    @patch("smart_agent.agent.AsyncOpenAI")
    @patch("smart_agent.cli.subprocess.Popen")
    @patch("smart_agent.agent.get_tool_client")
    async def test_chat_session_with_tools(self, mock_get_tool_client, mock_popen, 
                                         mock_openai, mock_config, mock_process):
        """Test a complete chat session with tool usage."""
        # Setup process mock
        mock_popen.return_value = mock_process
        
        # Setup OpenAI client mock
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        
        # Setup tool client mock
        mock_tool_client = MagicMock()
        mock_tool_client.call_function.return_value = {"result": "This is a search result for quantum computing."}
        mock_get_tool_client.return_value = mock_tool_client
        
        # Mock user input and output
        user_inputs = ["Tell me about quantum computing", "Thank you", "exit"]
        
        # Simulate model responses
        def simulate_completion(messages, **kwargs):
            """Simulate model completions based on conversation context."""
            user_message = messages[-1]["content"]
            
            # First message: respond with a tool call
            if "quantum computing" in user_message.lower():
                tool_call = MagicMock()
                tool_call.id = "call_123"
                tool_call.type = "function"
                tool_call.function.name = "search_tool"
                tool_call.function.arguments = '{"query": "quantum computing"}'
                
                message = MagicMock()
                message.role = "assistant"
                message.content = None
                message.tool_calls = [tool_call]
                
                completion = MagicMock()
                completion.choices = [MagicMock()]
                completion.choices[0].message = message
                return completion
            
            # Second message: normal response
            elif "thank you" in user_message.lower():
                message = MagicMock()
                message.role = "assistant"
                message.content = "You're welcome! Let me know if you have more questions."
                message.tool_calls = []
                
                completion = MagicMock()
                completion.choices = [MagicMock()]
                completion.choices[0].message = message
                return completion
            
            # Default response
            message = MagicMock()
            message.role = "assistant"
            message.content = "I don't understand. Please try again."
            message.tool_calls = []
            
            completion = MagicMock()
            completion.choices = [MagicMock()]
            completion.choices[0].message = message
            return completion
            
        mock_client.chat.completions.create.side_effect = simulate_completion
        
        # Start services
        with patch("builtins.input", side_effect=user_inputs):
            with patch("builtins.print") as mock_print:
                # Launch required services
                start_cmd(all=True)
                
                # Create agent and run chat
                agent = SmartAgent(mock_config)
                agent.load_tools()
                
                # Mock the asyncio.run to directly execute the coroutine
                with patch("asyncio.run", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)):
                    # Run chat session
                    await run_chat(agent)
                
                # Stop services
                stop_cmd(all=True)
        
        # Verify the interactions
        assert mock_client.chat.completions.create.call_count >= 2
        assert mock_tool_client.call_function.call_count >= 1
        
        # Check that output contains tool results
        prints = [call[0][0] for call in mock_print.call_args_list]
        assert any("search result" in str(p) for p in prints)
