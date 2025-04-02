"""
Unit tests for the Agent module.
"""

from unittest.mock import patch, MagicMock

from smart_agent.agent import SmartAgent


class TestSmartAgent:
    """Test suite for the SmartAgent class."""

    @patch("smart_agent.agent.AsyncOpenAI")
    def test_agent_initialization(self, mock_openai, mock_config):
        """Test agent initialization with configuration."""
        agent = SmartAgent(mock_config)

        # Verify that the agent was initialized correctly
        assert agent.config == mock_config
        assert agent.client is not None

    @patch("smart_agent.agent.AsyncOpenAI")
    @patch("smart_agent.agent.get_tool_client")
    def test_agent_load_tools(
        self,
        mock_get_tool_client,
        mock_openai,
        mock_config
    ):
        """Test loading tools into the agent."""
        # Setup mock tool client
        mock_tool_client = MagicMock()
        mock_get_tool_client.return_value = mock_tool_client

        # Initialize agent and load tools
        agent = SmartAgent(mock_config)
        agent.load_tools()

        # Verify that tools were loaded
        assert mock_get_tool_client.call_count > 0
        assert len(agent.tools) > 0

    @patch("smart_agent.agent.AsyncOpenAI")
    @patch("smart_agent.agent.get_tool_client")
    async def test_agent_chat_completion(
        self,
        mock_get_tool_client,
        mock_openai,
        mock_config
    ):
        """Test chat completion with the agent."""
        # Setup mock OpenAI client
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        # Mock the chat completion response
        mock_completion = MagicMock()
        mock_completion.choices[0].message.content = "Test response"
        mock_client.chat.completions.create.return_value = mock_completion

        # Initialize agent
        agent = SmartAgent(mock_config)

        # Test chat completion
        response = await agent.get_completion("Test message")

        # Verify that the client was called correctly
        mock_client.chat.completions.create.assert_called_once()
        assert response == "Test response"

    @patch("smart_agent.agent.AsyncOpenAI")
    @patch("smart_agent.agent.get_tool_client")
    async def test_agent_tool_call(
        self,
        mock_get_tool_client,
        mock_openai,
        mock_config
    ):
        """Test tool calling with the agent."""
        # Setup mock OpenAI client
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        # Mock the chat completion with tool call
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

        # Setup mock tool client
        mock_tool_client = MagicMock()
        mock_tool_client.call_function.return_value = {"result": "tool result"}
        mock_get_tool_client.return_value = mock_tool_client

        # Initialize agent
        agent = SmartAgent(mock_config)
        agent.tools = {"search_tool": {"name": "search_tool"}}

        # Test chat completion with tool call
        messages = [{"role": "user", "content": "Use the search tool"}]
        response = await agent.process_messages(messages)

        # Verify that the tool was called
        mock_tool_client.call_function.assert_called_once()

        # Verify that the response was processed correctly
        assert len(response) > len(messages)
        assert any(msg.get("role") == "assistant" for msg in response)
        assert any(msg.get("role") == "tool" for msg in response)
