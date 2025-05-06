"""
SmoothStreamWrapper for optimizing token streaming in Chainlit.

This module provides a wrapper for Chainlit messages that implements token batching
to improve performance with long messages.
"""

import asyncio
import time
import logging
from typing import Optional, Dict, Any

# Set up logging
logger = logging.getLogger(__name__)

class SmoothStreamWrapper:
    """
    A wrapper for Chainlit messages that implements token batching to improve performance.
    
    This class buffers tokens and sends them in batches to reduce the number of socket events
    and React state updates, resulting in smoother streaming for long messages.
    """
    
    def __init__(
        self,
        original_message,
        batch_size: int = 20,
        flush_interval: float = 0.1,
        debug: bool = False
    ):
        """
        Initialize the SmoothStreamWrapper.
        
        Args:
            original_message: The original Chainlit message to wrap
            batch_size: Number of tokens to batch before sending
            flush_interval: Time in seconds between flushes
            debug: Whether to log debug information
        """
        self.original_message = original_message
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.debug = debug
        
        # Batching state
        self.token_buffer = []
        self.last_flush_time = time.time()
        self.flush_task = None
        self.is_sequence = False
        self.total_tokens = 0
        self.batch_count = 0
        
        # Forward content attribute to original message
        self.content = self.original_message.content
        
    async def stream_token(self, token: str, is_sequence: bool = False):
        """
        Buffer tokens and send them in batches to improve performance.
        
        Args:
            token: The token to stream
            is_sequence: If True, replace the content with the token instead of appending
        """
        if not token:
            return
            
        self.total_tokens += 1
        
        # Sequence tokens are sent immediately
        if is_sequence:
            # Flush any pending tokens first
            await self._flush_buffer()
            # Send the sequence token directly
            await self.original_message.stream_token(token, is_sequence=True)
            # Update our content tracking
            self.content = token
            return
            
        # Add token to buffer
        self.token_buffer.append(token)
        # Update our content tracking
        self.content += token
        
        # Start the background flush task if not already running
        if self.flush_task is None or self.flush_task.done():
            self.flush_task = asyncio.create_task(self._background_flush())
            
        # Flush immediately if buffer reaches batch size
        if len(self.token_buffer) >= self.batch_size:
            await self._flush_buffer()
            
    async def _background_flush(self):
        """Background task to periodically flush the token buffer"""
        try:
            while self.token_buffer:
                current_time = time.time()
                if current_time - self.last_flush_time >= self.flush_interval:
                    await self._flush_buffer()
                await asyncio.sleep(self.flush_interval / 2)  # Check twice per interval
        except asyncio.CancelledError:
            # Ensure buffer is flushed on cancellation
            if self.token_buffer:
                await self._flush_buffer()
            raise
        except Exception as e:
            logger.error(f"Error in background flush task: {e}")
    
    async def _flush_buffer(self):
        """Flush the token buffer to the underlying Message"""
        if not self.token_buffer:
            return
            
        # Join all buffered tokens
        combined_token = "".join(self.token_buffer)
        buffer_size = len(self.token_buffer)
        self.token_buffer = []
        
        # Send to the underlying message
        try:
            await self.original_message.stream_token(combined_token, is_sequence=False)
            self.last_flush_time = time.time()
            self.batch_count += 1
            
            if self.debug:
                logger.debug(f"Flushed batch #{self.batch_count} with {buffer_size} tokens")
        except Exception as e:
            logger.error(f"Error flushing token buffer: {e}")
    
    async def send(self):
        """Send the message, ensuring all buffered tokens are flushed first"""
        # Flush any remaining tokens
        await self._flush_buffer()
        
        # Cancel the background flush task if it's running
        if self.flush_task and not self.flush_task.done():
            self.flush_task.cancel()
            try:
                await self.flush_task
            except asyncio.CancelledError:
                pass
        
        # Send the underlying message
        result = await self.original_message.send()
        
        if self.debug:
            logger.debug(f"Message sent with {self.total_tokens} total tokens in {self.batch_count} batches")
            
        return result
        
    async def update(self):
        """Update the message, ensuring all buffered tokens are flushed first"""
        # Flush any remaining tokens
        await self._flush_buffer()
        
        # Update the underlying message
        return await self.original_message.update()
        
    # Forward other attributes to the underlying message
    def __getattr__(self, name):
        return getattr(self.original_message, name)