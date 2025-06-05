#!/usr/bin/env python3
"""
Test script for the new Streamable HTTP transport in smart-agent.

This script demonstrates how to use the smart-agent with the new streamable HTTP transport.
It requires the example server (streamable_http_server.py) to be running.

Usage:
    1. Start the server: python examples/streamable_http_server.py
    2. Run this test: python examples/test_streamable_http.py
"""

import asyncio
import sys
import os
from pathlib import Path

# Add the smart-agent package to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from smart_agent.tool_manager import ConfigManager
from smart_agent.core.agent import BaseSmartAgent


async def test_streamable_http_transport():
    """Test the streamable HTTP transport with the example server."""
    
    print("Testing Streamable HTTP Transport for Smart Agent")
    print("=" * 50)
    
    # Create a test configuration
    test_config = {
        "llm": {
            "base_url": "http://localhost:4001",  # Placeholder - won't be used for this test
            "model": "test-model",
            "api_key": "test-key"
        },
        "tools": {
            "streamable_http_example": {
                "enabled": True,
                "url": "http://localhost:8000/mcp",
                "transport": "streamable-http",
                "timeouts": {
                    "timeout": 30,
                    "sse_read_timeout": 300,
                    "client_session_timeout": 30
                }
            }
        }
    }
    
    # Create a temporary config file
    import tempfile
    import yaml
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(test_config, f)
        config_path = f.name
    
    try:
        # Initialize config manager
        config_manager = ConfigManager(config_path)
        
        # Create the agent
        agent = BaseSmartAgent(config_manager)
        
        print(f"Created agent with {len(agent.mcp_servers)} MCP servers")
        
        # Connect to MCP servers
        print("Connecting to MCP servers...")
        await agent.connect(validate=True)
        
        print("Successfully connected to MCP servers!")
        
        # Test listing tools
        print("\nTesting tool listing...")
        for server in agent.mcp_servers:
            print(f"Server: {server.name}")
            try:
                tools = await server.list_tools()
                print(f"  Available tools: {[tool.name for tool in tools]}")
            except Exception as e:
                print(f"  Error listing tools: {e}")
        
        # Test calling a tool
        print("\nTesting tool calls...")
        for server in agent.mcp_servers:
            try:
                # Test the add_numbers tool
                result = await server.call_tool("add_numbers", {"a": 15, "b": 27})
                print(f"  add_numbers(15, 27) = {result}")
                
                # Test the get_random_fact tool
                result = await server.call_tool("get_random_fact", {})
                print(f"  get_random_fact() = {result}")
                
                # Test the calculate_fibonacci tool
                result = await server.call_tool("calculate_fibonacci", {"n": 10})
                print(f"  calculate_fibonacci(10) = {result}")
                
            except Exception as e:
                print(f"  Error calling tool: {e}")
        
        print("\nStreamable HTTP transport test completed successfully!")
        
    except Exception as e:
        print(f"Error during test: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Cleanup
        try:
            await agent.cleanup()
        except:
            pass
        
        # Remove temporary config file
        try:
            os.unlink(config_path)
        except:
            pass


if __name__ == "__main__":
    print("Make sure the example server is running:")
    print("  python examples/streamable_http_server.py")
    print()
    
    try:
        asyncio.run(test_streamable_http_transport())
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()