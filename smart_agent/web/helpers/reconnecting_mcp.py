"""Reconnecting MCP implementation for robust connections."""

import anyio
import backoff
import logging
import asyncio
import httpx
from contextlib import AsyncExitStack
from agents.mcp.server import MCPServerSse
from .robust_sse import robust_sse_client

log = logging.getLogger("mcp")

class ReconnectingMCP(MCPServerSse):
    """MCP Server with automatic reconnection capabilities.
    
    This class extends the standard MCPServerSse with automatic reconnection
    using exponential backoff when the connection is lost.
    """
    
    def __init__(self, name=None, params=None,
                 max_reconnect_attempts=10,
                 reconnect_base_delay=1.0,
                 reconnect_max_delay=60.0,
                 ping_interval=5.0,
                 sse_read_timeout=60.0):  # Reduced from default 5 minutes to 1 minute
        """Initialize the ReconnectingMCP server.
        
        Args:
            name: The name of the server
            params: The parameters for the server
            max_reconnect_attempts: Maximum number of reconnection attempts before giving up
            reconnect_base_delay: Base delay for reconnection attempts in seconds
            reconnect_max_delay: Maximum delay between reconnection attempts in seconds
            ping_interval: Interval between ping attempts in seconds
            sse_read_timeout: Timeout for SSE connection in seconds (default: 60s)
        """
        # Update params with our custom sse_read_timeout if not explicitly set
        if params is None:
            params = {}
        if "sse_read_timeout" not in params:
            params["sse_read_timeout"] = sse_read_timeout
            
        super().__init__(name=name, params=params)
        self._ping_task = None
        self._task_group = None
        self._connected = False
        self._exit_stack = AsyncExitStack()
        self._max_reconnect_attempts = max_reconnect_attempts
        self._reconnect_base_delay = reconnect_base_delay
        self._reconnect_max_delay = reconnect_max_delay
        self._ping_interval = ping_interval
        self._connection_lock = asyncio.Lock()
        self._reconnecting = False
    
    @backoff.on_exception(backoff.expo, Exception, max_time=None,
                         giveup=lambda e: isinstance(e, asyncio.CancelledError))
    async def _connect_once(self):
        """Connect to the MCP server with backoff retry.
        
        This method will retry connecting to the server with exponential backoff
        if the connection fails. It will not retry if the operation is cancelled.
        """
        try:
            await super().connect()
            self._connected = True
            log.info(f"Successfully connected to MCP server: {self.name}")
        except asyncio.CancelledError:
            log.debug("Connection attempt cancelled")
            self._connected = False
            raise
        except Exception as e:
            log.warning(f"Connection attempt failed: {e}")
            self._connected = False
            raise

    async def connect(self):
        """Connect to the MCP server and start the ping task.
        
        This method connects to the server and starts a background task that
        periodically pings the server to detect disconnections.
        """
        async with self._connection_lock:
            if self._connected:
                return
                
            try:
                await self._connect_once()
                
                # Create a new task group for the ping task
                self._task_group = anyio.create_task_group()
                await self._task_group.__aenter__()
                self._task_group.start_soon(self._ping)
            except Exception as e:
                log.warning(f"Failed to connect to MCP server: {e}")
                await self.cleanup()
                raise

    async def _attempt_reconnect(self):
        """Attempt to reconnect to the MCP server with exponential backoff.
        
        This method will try multiple times to reconnect with increasing delays
        between attempts, up to a maximum number of attempts or until successful.
        
        Returns:
            bool: True if reconnection was successful, False otherwise
        """
        if self._reconnecting:
            log.debug("Reconnection already in progress, skipping")
            return False
            
        self._reconnecting = True
        try:
            attempts = 0
            while attempts < self._max_reconnect_attempts:
                try:
                    delay = min(self._reconnect_base_delay * (2 ** attempts), self._reconnect_max_delay)
                    attempts += 1
                    
                    log.info(f"Reconnection attempt {attempts}/{self._max_reconnect_attempts} (delay: {delay:.1f}s)")
                    await anyio.sleep(delay)
                    
                    # Make sure we're not already connected
                    if self._connected:
                        log.info("Already reconnected, skipping reconnection attempt")
                        return True
                    
                    # Clean up existing connection but keep task group
                    await self.cleanup(keep_task_group=True)
                    
                    # Try to connect again
                    await self._connect_once()
                    log.info(f"Successfully reconnected to MCP server after {attempts} attempts")
                    return True
                    
                except asyncio.CancelledError:
                    log.debug("Reconnection attempt cancelled")
                    raise
                except Exception as e:
                    log.warning(f"Reconnection attempt {attempts} failed: {e}")
            
            log.error(f"Failed to reconnect after {self._max_reconnect_attempts} attempts")
            return False
        finally:
            self._reconnecting = False

    async def _ping(self):
        """Periodically ping the server to detect disconnections.
        
        If the ping fails, the connection is considered lost and a reconnection
        is attempted with exponential backoff.
        """
        try:
            while True:
                try:
                    if self._connected:
                        await self.send_ping()
                except Exception as e:
                    if isinstance(e, asyncio.CancelledError):
                        log.debug("Ping task cancelled")
                        break
                    
                    log.warning(f"Lost connection to MCP server: {e} -- attempting to reconnect")
                    self._connected = False
                    
                    try:
                        reconnected = await self._attempt_reconnect()
                        if reconnected:
                            self._connected = True
                        else:
                            log.error("Maximum reconnection attempts reached, will try again in next ping cycle")
                    except asyncio.CancelledError:
                        log.debug("Reconnection process cancelled")
                        break
                
                await anyio.sleep(self._ping_interval)
        except asyncio.CancelledError:
            log.debug("Ping task cancelled")
            raise
        except Exception as e:
            log.warning(f"Error in ping task: {e}")

    def create_streams(self):
        """Override create_streams to use our robust SSE client with better error handling."""
        url = self.params["url"]
        headers = self.params.get("headers", None)
        timeout = self.params.get("timeout", 5)
        sse_read_timeout = self.params.get("sse_read_timeout", 60)  # Default to 1 minute
        
        return robust_sse_client(
            url=url,
            headers=headers,
            timeout=timeout,
            sse_read_timeout=sse_read_timeout,
            max_retries=3,
            retry_delay=1.0,
        )

    async def cleanup(self, keep_task_group=False):
        """Clean up resources.
        
        Args:
            keep_task_group: Whether to keep the task group alive
        """
        async with self._connection_lock:
            self._connected = False
            
            # Call the parent cleanup method
            try:
                await super().cleanup()
            except Exception as e:
                log.debug(f"Error during parent cleanup: {e}")
            
            # Clean up the task group if it exists and we're not keeping it
            if self._task_group is not None and not keep_task_group:
                try:
                    await self._task_group.__aexit__(None, None, None)
                    self._task_group = None
                except Exception as e:
                    log.debug(f"Error cleaning up task group: {e}")
            
            # Close the exit stack
            try:
                await self._exit_stack.aclose()
            except Exception as e:
                log.debug(f"Error closing exit stack: {e}")

    async def send_ping(self):
        """Send a ping request to check if the connection is alive.
        
        This is a lightweight alternative to list_tools() for health checks.
        
        Returns:
            The empty result from the ping request
        
        Raises:
            Exception: If the ping fails
        """
        try:
            # Use the session attribute to send a ping request
            if hasattr(self, 'session') and self.session:
                await self.session.send_ping()
                return True
            else:
                raise RuntimeError("No active session available for ping")
        except (httpx.HTTPError, httpx.TimeoutException, ConnectionError, RuntimeError) as e:
            log.warning(f"Connection error during ping: {e}")
            self._connected = False
            raise
    
    async def call_tool(self, tool_name, arguments=None):
        """Override call_tool to handle connection issues."""
        try:
            return await super().call_tool(tool_name, arguments)
        except (httpx.HTTPError, httpx.TimeoutException, ConnectionError) as e:
            log.warning(f"Connection error during tool call: {e}")
            self._connected = False
            
            # Attempt to reconnect
            reconnected = await self._attempt_reconnect()
            if reconnected:
                # Retry the tool call
                return await super().call_tool(tool_name, arguments)
            else:
                # If reconnection failed, raise the original error
                raise

    async def __aenter__(self):
        """Enter the async context manager."""
        await self._exit_stack.__aenter__()
        try:
            await self.connect()
            return self
        except Exception as e:
            await self._exit_stack.__aexit__(type(e), e, None)
            raise

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit the async context manager."""
        await self.cleanup()
        await self._exit_stack.__aexit__(exc_type, exc_val, exc_tb)