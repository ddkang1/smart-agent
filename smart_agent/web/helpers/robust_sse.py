"""Robust SSE client implementation for MCP."""

import logging
import asyncio
from contextlib import asynccontextmanager
from typing import Any, Optional, Tuple
from urllib.parse import urljoin, urlparse

import anyio
import httpx
from anyio.abc import TaskStatus
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from httpx_sse import aconnect_sse, ServerSentEvent

import mcp.types as types

logger = logging.getLogger("mcp")


def remove_request_params(url: str) -> str:
    """Remove request parameters from URL."""
    return urljoin(url, urlparse(url).path)


class RobustSSEConnection:
    """A robust SSE connection with automatic reconnection capabilities."""
    
    def __init__(
        self,
        url: str,
        headers: Optional[dict[str, Any]] = None,
        timeout: float = 5,
        sse_read_timeout: float = 60.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        """Initialize the robust SSE connection.
        
        Args:
            url: The URL to connect to
            headers: Optional headers to send with the request
            timeout: Timeout for HTTP operations in seconds
            sse_read_timeout: Timeout for SSE connection in seconds
            max_retries: Maximum number of retries for transient errors
            retry_delay: Base delay between retries in seconds
        """
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout
        self.sse_read_timeout = sse_read_timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        self.client = None
        self.endpoint_url = None
        self.connected = False
        self.reconnecting = False
        self.event_queue = asyncio.Queue()
        self.connection_task = None
        self.connection_lock = asyncio.Lock()
    
    async def connect(self):
        """Connect to the SSE endpoint."""
        async with self.connection_lock:
            if self.connected:
                return
            
            logger.info(f"Connecting to SSE endpoint: {remove_request_params(self.url)}")
            
            # Create HTTP client with keep-alive and retry options
            if self.client is None:
                self.client = httpx.AsyncClient(
                    headers=self.headers,
                    timeout=httpx.Timeout(self.timeout, read=self.sse_read_timeout),
                    limits=httpx.Limits(max_keepalive_connections=5, keepalive_expiry=30),
                )
            
            # Start the connection task
            if self.connection_task is None or self.connection_task.done():
                self.connection_task = asyncio.create_task(self._connection_loop())
    
    async def _connection_loop(self):
        """Maintain the SSE connection with automatic reconnection."""
        retry_count = 0
        
        while True:
            try:
                if retry_count > 0:
                    delay = self.retry_delay * (2 ** (retry_count - 1))
                    logger.info(f"Retrying SSE connection (attempt {retry_count}/{self.max_retries}, delay: {delay:.1f}s)")
                    await asyncio.sleep(delay)
                
                # Connect to the SSE endpoint
                async with aconnect_sse(
                    self.client,
                    "GET",
                    self.url,
                    timeout=httpx.Timeout(self.timeout, read=self.sse_read_timeout),
                ) as event_source:
                    event_source.response.raise_for_status()
                    logger.debug("SSE connection established")
                    self.connected = True
                    retry_count = 0  # Reset retry count on successful connection
                    
                    # Process SSE events
                    async for sse in event_source.aiter_sse():
                        logger.debug(f"Received SSE event: {sse.event}")
                        
                        if sse.event == "endpoint":
                            await self._handle_endpoint_event(sse)
                        elif sse.event == "message":
                            await self._handle_message_event(sse)
                        else:
                            logger.warning(f"Unknown SSE event: {sse.event}")
            
            except (httpx.HTTPError, httpx.TimeoutException, ConnectionError) as e:
                self.connected = False
                retry_count += 1
                
                if retry_count > self.max_retries:
                    logger.error(f"Failed to establish SSE connection after {self.max_retries} attempts: {e}")
                    await self.event_queue.put(e)
                    break
                
                logger.debug(f"Error in SSE connection: {e}, will retry")
            
            except asyncio.CancelledError:
                logger.debug("SSE connection task cancelled")
                self.connected = False
                break
            
            except Exception as e:
                self.connected = False
                logger.error(f"Unexpected error in SSE connection: {e}")
                await self.event_queue.put(e)
                
                retry_count += 1
                if retry_count > self.max_retries:
                    logger.error(f"Too many errors, giving up after {self.max_retries} attempts")
                    break
    
    async def _handle_endpoint_event(self, sse: ServerSentEvent):
        """Handle an endpoint event."""
        endpoint_url = urljoin(self.url, sse.data)
        logger.info(f"Received endpoint URL: {endpoint_url}")
        
        url_parsed = urlparse(self.url)
        endpoint_parsed = urlparse(endpoint_url)
        
        if (url_parsed.netloc != endpoint_parsed.netloc or
            url_parsed.scheme != endpoint_parsed.scheme):
            error_msg = f"Endpoint origin does not match connection origin: {endpoint_url}"
            logger.error(error_msg)
            await self.event_queue.put(ValueError(error_msg))
            return
        
        self.endpoint_url = endpoint_url
        await self.event_queue.put(("endpoint", endpoint_url))
    
    async def _handle_message_event(self, sse: ServerSentEvent):
        """Handle a message event."""
        try:
            message = types.JSONRPCMessage.model_validate_json(sse.data)
            logger.debug(f"Received server message: {message}")
            await self.event_queue.put(message)
        except Exception as exc:
            logger.error(f"Error parsing server message: {exc}")
            await self.event_queue.put(exc)
    
    async def send_message(self, message: types.JSONRPCMessage):
        """Send a message to the server."""
        if not self.endpoint_url:
            raise ValueError("No endpoint URL available. Make sure you're connected.")
        
        retry_count = 0
        while retry_count <= self.max_retries:
            try:
                if not self.connected:
                    # If connection is lost, wait for reconnection
                    logger.info("Connection lost, waiting for reconnection before sending message")
                    await asyncio.sleep(self.retry_delay)
                    retry_count += 1
                    continue
                
                logger.debug(f"Sending client message: {message}")
                response = await self.client.post(
                    self.endpoint_url,
                    json=message.model_dump(
                        by_alias=True,
                        mode="json",
                        exclude_none=True,
                    ),
                    timeout=httpx.Timeout(self.timeout),
                )
                response.raise_for_status()
                logger.debug(f"Client message sent successfully: {response.status_code}")
                return
            
            except (httpx.HTTPError, httpx.TimeoutException, ConnectionError) as e:
                retry_count += 1
                if retry_count > self.max_retries:
                    logger.error(f"Failed to send message after {self.max_retries} retries: {e}")
                    raise
                
                retry_delay_time = self.retry_delay * (2 ** (retry_count - 1))
                logger.debug(
                    f"Error sending message: {e}, retrying in {retry_delay_time:.1f}s "
                    f"(attempt {retry_count}/{self.max_retries})"
                )
                await asyncio.sleep(retry_delay_time)
    
    async def get_next_event(self):
        """Get the next event from the queue."""
        return await self.event_queue.get()
    
    async def close(self):
        """Close the connection."""
        if self.connection_task and not self.connection_task.done():
            self.connection_task.cancel()
            try:
                await self.connection_task
            except asyncio.CancelledError:
                pass
        
        if self.client:
            await self.client.aclose()
            self.client = None
        
        self.connected = False


@asynccontextmanager
async def robust_sse_client(
    url: str,
    headers: Optional[dict[str, Any]] = None,
    timeout: float = 5,
    sse_read_timeout: float = 60.0,
    max_retries: int = 3,
    retry_delay: float = 1.0,
):
    """
    Enhanced SSE client with automatic reconnection capabilities.

    Args:
        url: The URL to connect to
        headers: Optional headers to send with the request
        timeout: Timeout for HTTP operations in seconds
        sse_read_timeout: Timeout for SSE connection in seconds
        max_retries: Maximum number of retries for transient errors
        retry_delay: Base delay between retries in seconds
    """
    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)
    
    # Create the robust SSE connection
    connection = RobustSSEConnection(
        url=url,
        headers=headers,
        timeout=timeout,
        sse_read_timeout=sse_read_timeout,
        max_retries=max_retries,
        retry_delay=retry_delay,
    )
    
    async with anyio.create_task_group() as tg:
        try:
            # Connect to the SSE endpoint
            await connection.connect()
            
            async def reader_task():
                """Read events from the connection and forward them to the read stream."""
                try:
                    endpoint_url = None
                    # Wait for the endpoint URL
                    while True:
                        event = await connection.get_next_event()
                        if isinstance(event, tuple) and event[0] == "endpoint":
                            endpoint_url = event[1]
                            break
                        elif isinstance(event, Exception):
                            await read_stream_writer.send(event)
                            return
                    
                    # Start the writer task
                    tg.start_soon(writer_task, endpoint_url)
                    
                    # Process messages
                    while True:
                        event = await connection.get_next_event()
                        if isinstance(event, types.JSONRPCMessage):
                            await read_stream_writer.send(event)
                        elif isinstance(event, Exception):
                            await read_stream_writer.send(event)
                            # Don't return here, keep processing events
                except asyncio.CancelledError:
                    logger.debug("Reader task cancelled")
                    raise
                except Exception as e:
                    logger.error(f"Error in reader task: {e}")
                    await read_stream_writer.send(e)
                finally:
                    await read_stream_writer.aclose()
            
            async def writer_task(endpoint_url):
                """Read messages from the write stream and send them to the server."""
                try:
                    async with write_stream_reader:
                        async for message in write_stream_reader:
                            try:
                                await connection.send_message(message)
                            except Exception as e:
                                logger.error(f"Error sending message: {e}")
                except asyncio.CancelledError:
                    logger.debug("Writer task cancelled")
                    raise
                except Exception as e:
                    logger.error(f"Error in writer task: {e}")
                finally:
                    await write_stream.aclose()
            
            # Start the reader task
            tg.start_soon(reader_task)
            
            try:
                yield read_stream, write_stream
            finally:
                tg.cancel_scope.cancel()
        finally:
            await connection.close()
            await read_stream_writer.aclose()
            await write_stream.aclose()