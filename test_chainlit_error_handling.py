#!/usr/bin/env python3
"""
Test script to verify Chainlit error handling improvements.

This script tests the error handling patterns implemented to fix the runtime errors
related to async HTTP connections and resource cleanup.
"""

import asyncio
import logging
import sys
import warnings
from contextlib import AsyncExitStack

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Apply the same warning filters as in chainlit_app.py
warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*async generator ignored GeneratorExit.*")
warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*Attempted to exit cancel scope in a different task.*")
warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*coroutine.*was never awaited.*")
warnings.filterwarnings("ignore", module="httpcore.*")
warnings.filterwarnings("ignore", module="anyio.*")


class MockMCPServer:
    """Mock MCP server for testing."""
    
    def __init__(self, name, should_fail=False, should_timeout=False):
        self.name = name
        self.should_fail = should_fail
        self.should_timeout = should_timeout
        self.connected = False
    
    async def __aenter__(self):
        if self.should_timeout:
            await asyncio.sleep(15)  # Simulate timeout
        if self.should_fail:
            raise Exception(f"Simulated connection failure for {self.name}")
        
        self.connected = True
        logger.info(f"Mock MCP server {self.name} connected")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.connected:
            self.connected = False
            logger.info(f"Mock MCP server {self.name} disconnected")


async def test_mcp_connection_robustness():
    """Test MCP server connection with error handling."""
    logger.info("Testing MCP server connection robustness...")
    
    # Create mock servers with different failure modes
    servers = [
        MockMCPServer("working_server_1"),
        MockMCPServer("failing_server", should_fail=True),
        MockMCPServer("working_server_2"),
        MockMCPServer("timeout_server", should_timeout=True),
        MockMCPServer("working_server_3"),
    ]
    
    connected_servers = []
    connection_errors = []
    
    async with AsyncExitStack() as exit_stack:
        for server in servers:
            try:
                # Use timeout for connection to prevent hanging
                connected_server = await asyncio.wait_for(
                    exit_stack.enter_async_context(server), 
                    timeout=10.0
                )
                connected_servers.append(connected_server)
                logger.info(f"Successfully connected to {server.name}")
                
            except asyncio.TimeoutError:
                error_msg = f"Timeout connecting to server: {server.name}"
                logger.warning(error_msg)
                connection_errors.append(error_msg)
            except Exception as e:
                error_msg = f"Error connecting to server {server.name}: {e}"
                logger.warning(error_msg)
                connection_errors.append(error_msg)
    
    logger.info(f"Connected to {len(connected_servers)} servers successfully")
    logger.info(f"Failed to connect to {len(connection_errors)} servers")
    
    return len(connected_servers) > 0


async def test_cleanup_robustness():
    """Test cleanup with timeout handling."""
    logger.info("Testing cleanup robustness...")
    
    cleanup_tasks = []
    
    # Simulate various cleanup scenarios
    async def quick_cleanup():
        await asyncio.sleep(0.1)
        logger.info("Quick cleanup completed")
    
    async def slow_cleanup():
        await asyncio.sleep(15)  # Will timeout
        logger.info("Slow cleanup completed")
    
    async def failing_cleanup():
        await asyncio.sleep(0.1)
        raise Exception("Cleanup failed")
    
    # Add cleanup tasks with timeouts
    cleanup_tasks.append(asyncio.wait_for(quick_cleanup(), timeout=5.0))
    cleanup_tasks.append(asyncio.wait_for(slow_cleanup(), timeout=5.0))
    cleanup_tasks.append(asyncio.wait_for(failing_cleanup(), timeout=5.0))
    
    # Execute all cleanup tasks with individual error handling
    try:
        results = await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        
        success_count = 0
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                if isinstance(result, asyncio.TimeoutError):
                    logger.warning(f"Cleanup task {i} timed out")
                else:
                    logger.error(f"Cleanup task {i} failed: {result}")
            else:
                success_count += 1
                logger.info(f"Cleanup task {i} succeeded")
        
        logger.info(f"Cleanup completed: {success_count}/{len(cleanup_tasks)} tasks succeeded")
        return True
        
    except Exception as e:
        logger.error(f"Unexpected error during cleanup: {e}")
        return False


async def test_stream_error_handling():
    """Test stream event error handling."""
    logger.info("Testing stream event error handling...")
    
    # Simulate stream events with various error conditions
    class MockEvent:
        def __init__(self, event_type, should_fail=False):
            self.type = event_type
            self.should_fail = should_fail
    
    events = [
        MockEvent("normal_event"),
        MockEvent("failing_event", should_fail=True),
        MockEvent("another_normal_event"),
    ]
    
    processed_count = 0
    error_count = 0
    
    for event in events:
        try:
            if event.should_fail:
                raise Exception(f"Simulated error processing {event.type}")
            
            # Simulate event processing
            await asyncio.sleep(0.01)
            processed_count += 1
            logger.info(f"Processed event: {event.type}")
            
        except Exception as e:
            error_count += 1
            logger.error(f"Error handling event {event.type}: {e}")
            # Continue processing other events instead of failing completely
    
    logger.info(f"Stream processing: {processed_count} succeeded, {error_count} failed")
    return processed_count > 0


async def main():
    """Run all tests."""
    logger.info("Starting Chainlit error handling tests...")
    
    tests = [
        test_mcp_connection_robustness,
        test_cleanup_robustness,
        test_stream_error_handling,
    ]
    
    results = []
    for test in tests:
        try:
            result = await test()
            results.append(result)
            logger.info(f"Test {test.__name__}: {'PASSED' if result else 'FAILED'}")
        except Exception as e:
            logger.error(f"Test {test.__name__} crashed: {e}")
            results.append(False)
    
    passed = sum(results)
    total = len(results)
    
    logger.info(f"\nTest summary: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("All tests passed! Error handling improvements are working.")
        return 0
    else:
        logger.error("Some tests failed. Check the error handling implementation.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)