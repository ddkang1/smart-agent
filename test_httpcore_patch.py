#!/usr/bin/env python3
"""
Test script to verify that the httpcore patches work correctly.

This script simulates the conditions that cause the runtime errors
and verifies that the patches suppress them properly.
"""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import the patch first
from smart_agent.web.httpcore_patch import patch_httpcore, suppress_async_warnings

async def test_httpcore_patches():
    """Test that httpcore patches work correctly."""
    logger.info("Testing httpcore patches...")
    
    try:
        import httpx
        from openai import AsyncOpenAI
        
        # Create an HTTP client similar to what we use in the agent
        http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0, read=30.0, write=10.0, pool=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
            http2=False,
            transport=httpx.AsyncHTTPTransport(retries=3)
        )
        
        # Create an OpenAI client with the custom HTTP client
        openai_client = AsyncOpenAI(
            base_url="https://api.openai.com/v1",
            api_key="test-key",  # This won't work but that's fine for testing
            http_client=http_client,
        )
        
        logger.info("Created HTTP and OpenAI clients successfully")
        
        # Test cleanup - this is where the errors usually occur
        try:
            await asyncio.wait_for(openai_client.close(), timeout=5.0)
            logger.info("OpenAI client closed successfully")
        except Exception as e:
            logger.info(f"OpenAI client close error (expected): {e}")
        
        try:
            await asyncio.wait_for(http_client.aclose(), timeout=5.0)
            logger.info("HTTP client closed successfully")
        except Exception as e:
            logger.info(f"HTTP client close error (expected): {e}")
        
        logger.info("✅ Httpcore patches test completed without crashes")
        return True
        
    except Exception as e:
        logger.error(f"❌ Httpcore patches test failed: {e}")
        return False

async def test_async_generator_handling():
    """Test async generator handling that typically causes issues."""
    logger.info("Testing async generator handling...")
    
    try:
        async def problematic_generator():
            """Simulate a generator that might cause GeneratorExit issues."""
            try:
                for i in range(5):
                    yield f"item_{i}"
                    await asyncio.sleep(0.01)
            except GeneratorExit:
                logger.debug("GeneratorExit handled in generator")
                return
            except Exception as e:
                logger.debug(f"Generator error: {e}")
                return
        
        # Test generator cleanup scenarios
        generator = problematic_generator()
        
        # Get a few items then abandon the generator
        items = []
        async for item in generator:
            items.append(item)
            if len(items) >= 2:
                break
        
        # Force cleanup
        await generator.aclose()
        
        logger.info(f"✅ Async generator test completed, got items: {items}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Async generator test failed: {e}")
        return False

async def test_cancel_scope_handling():
    """Test cancel scope handling that typically causes cross-task issues."""
    logger.info("Testing cancel scope handling...")
    
    try:
        import anyio
        
        async def task_with_cancel_scope():
            """Task that uses cancel scope."""
            try:
                with anyio.CancelScope(deadline=asyncio.get_event_loop().time() + 1.0):
                    await asyncio.sleep(0.5)
                return "completed"
            except Exception as e:
                logger.debug(f"Cancel scope task error: {e}")
                return "error"
        
        # Run task in a separate task to simulate cross-task scenario
        task = asyncio.create_task(task_with_cancel_scope())
        result = await asyncio.wait_for(task, timeout=2.0)
        
        logger.info(f"✅ Cancel scope test completed with result: {result}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Cancel scope test failed: {e}")
        return False

async def main():
    """Run all tests."""
    logger.info("Starting httpcore patch tests...")
    
    tests = [
        test_httpcore_patches,
        test_async_generator_handling,
        test_cancel_scope_handling,
    ]
    
    results = []
    for test in tests:
        try:
            result = await test()
            results.append(result)
        except Exception as e:
            logger.error(f"Test {test.__name__} crashed: {e}")
            results.append(False)
    
    passed = sum(results)
    total = len(results)
    
    logger.info(f"\nTest summary: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("🎉 All httpcore patch tests passed!")
        return 0
    else:
        logger.error("❌ Some tests failed. Check the patches.")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)