"""
Unit tests for the Agent module.
"""

from unittest.mock import patch, MagicMock

from smart_agent.agent import SmartAgent


class TestSmartAgent:
    """Test suite for the SmartAgent class."""

    def test_agent_initialization(self):
        """Test agent initialization with basic parameters."""
        # Create mock objects
        mock_openai_client = MagicMock()
        mock_mcp_servers = [MagicMock()]
        model_name = "gpt-4"
        system_prompt = "You are a helpful assistant."

        # Initialize the agent
        agent = SmartAgent(
            model_name=model_name,
            openai_client=mock_openai_client,
            mcp_servers=mock_mcp_servers,
            system_prompt=system_prompt,
        )

        # Verify that the agent was initialized correctly
        assert agent.model_name == model_name
        assert agent.openai_client == mock_openai_client
        assert agent.mcp_servers == mock_mcp_servers
        assert agent.system_prompt == system_prompt
        assert agent.agent is not None

    def test_agent_without_initialization(self):
        """Test agent creation without initialization parameters."""
        # Initialize the agent without required parameters
        agent = SmartAgent()

        # Verify that the agent properties are set correctly but agent is not initialized
        assert agent.model_name is None
        assert agent.openai_client is None
        assert agent.mcp_servers == []
        assert agent.system_prompt is None
        assert agent.agent is None

    @patch("smart_agent.agent.Agent")
    @patch("smart_agent.agent.OpenAIChatCompletionsModel")
    def test_initialize_agent(self, mock_model_class, mock_agent_class):
        """Test the _initialize_agent method."""
        # Create mock objects
        mock_openai_client = MagicMock()
        mock_mcp_servers = [MagicMock()]
        model_name = "gpt-4"
        system_prompt = "You are a helpful assistant."

        # Initialize the agent
        agent = SmartAgent(
            model_name=model_name,
            openai_client=mock_openai_client,
            mcp_servers=mock_mcp_servers,
            system_prompt=system_prompt,
        )

        # Verify that the agent methods were called correctly
        mock_model_class.assert_called_once_with(
            model=model_name, openai_client=mock_openai_client
        )
        mock_agent_class.assert_called_once_with(
            name="Assistant",
            instructions=system_prompt,
            model=mock_model_class.return_value,
            mcp_servers=mock_mcp_servers,
        )

    @patch("smart_agent.agent.Runner")
    def test_process_message(self, mock_runner):
        """Test the process_message method."""
        # Setup
        mock_openai_client = MagicMock()
        mock_mcp_servers = [MagicMock()]
        agent = SmartAgent(
            model_name="gpt-4",
            openai_client=mock_openai_client,
            mcp_servers=mock_mcp_servers,
        )

        # Create test data
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]

        # Call the method (need to use async test framework)
        # For now, we'll just test that the method exists and has the right signature
        assert hasattr(agent, "process_message")

    def test_process_message_without_agent(self):
        """Test process_message raises error when agent is not initialized."""
        # Setup
        agent = SmartAgent()  # No initialization parameters

        # Create test data
        history = [{"role": "user", "content": "Hello"}]

        # Test that calling process_message raises ValueError
        try:
            import asyncio

            asyncio.run(agent.process_message(history))
            assert False, "Expected ValueError was not raised"
        except ValueError:
            pass  # Expected behavior

    def test_process_stream_events_method_exists(self):
        """Test that the process_stream_events method exists."""
        # Just verify the method exists and is a static method
        assert hasattr(SmartAgent, "process_stream_events")
        # We can't easily test the async functionality here without a more complex setup
