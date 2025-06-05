"""
Cleanup handler for Smart Agent web interface.

This module provides utilities for handling cleanup during shutdown
to prevent async cleanup errors.
"""

import asyncio
import logging
import signal
import sys
import warnings
from typing import Optional

logger = logging.getLogger(__name__)


class CleanupHandler:
    """Handles graceful cleanup during application shutdown."""
    
    def __init__(self):
        self.cleanup_tasks = []
        self.shutdown_event = asyncio.Event()
        self._original_handlers = {}
        
    def add_cleanup_task(self, coro):
        """Add a cleanup coroutine to be executed during shutdown."""
        self.cleanup_tasks.append(coro)
        
    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating graceful shutdown...")
            self.shutdown_event.set()
            
        # Store original handlers
        self._original_handlers[signal.SIGINT] = signal.signal(signal.SIGINT, signal_handler)
        self._original_handlers[signal.SIGTERM] = signal.signal(signal.SIGTERM, signal_handler)
        
    def restore_signal_handlers(self):
        """Restore original signal handlers."""
        for sig, handler in self._original_handlers.items():
            signal.signal(sig, handler)
            
    async def cleanup(self):
        """Execute all cleanup tasks."""
        logger.info("Executing cleanup tasks...")
        
        for task in self.cleanup_tasks:
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Cleanup task timed out")
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")
                
        logger.info("Cleanup completed")


def setup_error_suppression():
    """Setup comprehensive error suppression for HTTP cleanup issues."""
    
    # Suppress specific warnings
    warnings.filterwarnings("ignore", message="Attempted to exit cancel scope in a different task than it was entered in")
    warnings.filterwarnings("ignore", message="async generator ignored GeneratorExit")
    warnings.filterwarnings("ignore", message="no running event loop")
    warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*async generator.*")
    warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*event loop.*")
    warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*cancel scope.*")
    
    # Custom exception hook to suppress specific HTTP cleanup errors
    def custom_excepthook(exc_type, exc_value, exc_traceback):
        """Custom exception hook to suppress specific HTTP cleanup errors."""
        if exc_type == RuntimeError:
            error_msg = str(exc_value)
            if any(msg in error_msg for msg in [
                "async generator ignored GeneratorExit",
                "no running event loop",
                "Attempted to exit cancel scope in a different task",
                "cancel scope"
            ]):
                # Suppress these specific errors
                return
        
        # For all other exceptions, use the default handler
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    # Install the custom exception hook
    sys.excepthook = custom_excepthook

    # Handle async exceptions
    def handle_exception(loop, context):
        """Handle async exceptions to suppress HTTP cleanup errors."""
        exception = context.get('exception')
        if isinstance(exception, RuntimeError):
            error_msg = str(exception)
            if any(msg in error_msg for msg in [
                "async generator ignored GeneratorExit",
                "no running event loop", 
                "Attempted to exit cancel scope in a different task",
                "cancel scope"
            ]):
                # Suppress these specific errors
                return
        
        # For other exceptions, log them normally
        logger.error(f"Async exception: {context}")

    # Set the exception handler for the event loop
    try:
        loop = asyncio.get_event_loop()
        loop.set_exception_handler(handle_exception)
    except RuntimeError:
        # No event loop running yet, will be set later
        pass


# Global cleanup handler instance
cleanup_handler = CleanupHandler()