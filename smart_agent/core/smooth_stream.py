"""
SmoothStreamWrapper for optimizing token streaming in Chainlit.

This module provides a wrapper for Chainlit messages that implements token batching
to improve performance with long messages.
"""

import asyncio
import time
import logging
from typing import Optional, Dict, Any
from collections import deque

# Set up logging
logger = logging.getLogger(__name__)

class SmoothStreamWrapper:
    """
    A wrapper for Chainlit messages that implements token batching to improve performance.
    
    This class buffers tokens and sends them in batches to reduce the number of socket events
    and React state updates, resulting in smoother streaming for long messages.
    
    Implementation is based on a producer-consumer pattern with a dedicated streaming task
    that runs continuously until streaming is complete.
    """
    
    def __init__(
        self,
        original_message,
        batch_size: int = 20,
        flush_interval: float = 0.05,
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
        self.token_buffer = deque()
        self.stream_ended = asyncio.Event()
        self.streaming_task = None
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
        self.token_buffer.extend(token)
        # Update our content tracking
        self.content += token
        
        # Start the streaming task if not already running
        if not self.streaming_task or self.streaming_task.done():
            self.streaming_task = asyncio.create_task(
                self._stream_output_task(
                    self.original_message,
                    self.token_buffer,
                    self.flush_interval,
                    self.batch_size,
                    self.stream_ended
                )
            )
            
    async def _stream_output_task(self, msg, buffer, interval, size, end_event):
        """
        Background task to periodically flush the token buffer.
        
        This task runs continuously until streaming is complete and the buffer is empty.
        
        Args:
            msg: The message to stream tokens to
            buffer: The token buffer (deque)
            interval: Time in seconds between flushes
            size: Maximum number of tokens to flush at once
            end_event: Event to signal when streaming is complete
        """
        try:
            # Initialize streaming if needed
            if not hasattr(msg, 'streaming') or not msg.streaming:
                if len(buffer) > 0:
                    # Get one token to start streaming
                    first_token = buffer.popleft()
                    await msg.stream_token(first_token)
            
            # Continue until signaled and buffer is empty
            while not end_event.is_set() or buffer:
                if buffer:
                    # Calculate how many tokens to flush
                    flush_count = min(size, len(buffer))
                    
                    if flush_count > 0:
                        # Join tokens into a single string
                        to_flush = ''.join([buffer.popleft() for _ in range(flush_count)])
                        
                        # Send the combined token
                        await msg.stream_token(to_flush)
                        
                        # Update batch count
                        self.batch_count += 1
                        
                        if self.debug:
                            logger.debug(f"Flushed batch #{self.batch_count} with {flush_count} tokens")
                
                # Wait before checking again
                await asyncio.sleep(interval)
                
        except asyncio.CancelledError:
            # Task cancellation is expected on completion
            if self.debug:
                logger.debug("Streaming task cancelled")
            
            # Make sure to flush any remaining tokens
            if buffer:
                to_flush = ''.join(list(buffer))
                buffer.clear()
                await msg.stream_token(to_flush)
                
            raise
            
        except Exception as e:
            logger.error(f"Error in streaming task: {e}")
    
    async def _flush_buffer(self):
        """Flush the token buffer to the underlying Message"""
        if not self.token_buffer:
            return
            
        # Join all buffered tokens
        to_flush = ''.join(list(self.token_buffer))
        buffer_size = len(self.token_buffer)
        self.token_buffer.clear()
        
        # Send to the underlying message
        try:
            await self.original_message.stream_token(to_flush, is_sequence=False)
            self.batch_count += 1
            
            if self.debug:
                logger.debug(f"Manually flushed batch with {buffer_size} tokens")
        except Exception as e:
            logger.error(f"Error flushing token buffer: {e}")
    
    async def send(self):
        """Send the message, ensuring all buffered tokens are flushed first"""
        # Signal that streaming is complete
        self.stream_ended.set()
        
        # Wait for the streaming task to finish processing the buffer
        if self.streaming_task and not self.streaming_task.done():
            try:
                await self.streaming_task
            except asyncio.CancelledError:
                # This is expected
                pass
        
        # Send the underlying message
        result = await self.original_message.send()
        
        if self.debug:
            logger.debug(f"Message sent with {self.total_tokens} total tokens in {self.batch_count} batches")
            
        return result
        
    async def update(self):
        """Update the message, ensuring all buffered tokens are flushed first"""
        # Signal that streaming is complete
        self.stream_ended.set()
        
        # Wait for the streaming task to finish processing the buffer
        if self.streaming_task and not self.streaming_task.done():
            try:
                await self.streaming_task
            except asyncio.CancelledError:
                # This is expected
                pass
        
        # Update the underlying message
        return await self.original_message.update()
        
    # Forward other attributes to the underlying message
    def __getattr__(self, name):
        return getattr(self.original_message, name)