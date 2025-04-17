"""Reconnecting MCP implementation for robust connections."""

import anyio
import backoff
import logging
import asyncio
from contextlib import AsyncExitStack
from agents.mcp.server import MCPServerSse

log = logging.getLogger("mcp")

class ReconnectingMCP(MCPServerSse):
    """MCP Server with automatic reconnection capabilities.
    
    This class extends the standard MCPServerSse with automatic reconnection
    using exponential backoff when the connection is lost.
    """
    
    def __init__(self, name=None, params=None):
        """Initialize the ReconnectingMCP server.
        
        Args:
            name: The name of the server
            params: The parameters for the server
        """
        super().__init__(name=name, params=params)
        self._ping_task = None
        self._task_group = None
        self._connected = False
        self._exit_stack = AsyncExitStack()
    
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
        except asyncio.CancelledError:
            log.debug("Connection attempt cancelled")
            self._connected = False
            raise

    async def connect(self):
        """Connect to the MCP server and start the ping task.
        
        This method connects to the server and starts a background task that
        periodically pings the server to detect disconnections.
        """
        try:
            await self._connect_once()
            
            # Create a new task group for the ping task
            self._task_group = anyio.create_task_group()
            await self._task_group.__aenter__()
            self._task_group.start_soon(self._ping)
        except Exception as e:
            log.warning("Failed to connect to MCP server: %s", e)
            await self.cleanup()
            raise

    async def _ping(self):
        """Periodically ping the server to detect disconnections.
        
        If the ping fails, the connection is considered lost and a reconnection
        is attempted.
        """
        try:
            while True:
                try:
                    if self._connected:
                        await self.list_tools()
                except Exception as e:
                    if isinstance(e, asyncio.CancelledError):
                        log.debug("Ping task cancelled")
                        break
                    log.warning("Lost connection to MCP server: %s -- reconnecting", e)
                    self._connected = False
                    try:
                        await self.cleanup(keep_task_group=True)
                        await self._connect_once()
                        self._connected = True
                    except asyncio.CancelledError:
                        log.debug("Reconnection attempt cancelled")
                        break
                    except Exception as reconnect_error:
                        log.warning("Failed to reconnect: %s", reconnect_error)
                
                await anyio.sleep(5)
        except asyncio.CancelledError:
            log.debug("Ping task cancelled")
            raise
        except Exception as e:
            log.warning("Error in ping task: %s", e)

    async def cleanup(self, keep_task_group=False):
        """Clean up resources.
        
        Args:
            keep_task_group: Whether to keep the task group alive
        """
        self._connected = False
        
        # Call the parent cleanup method
        try:
            await super().cleanup()
        except Exception as e:
            log.warning("Error during parent cleanup: %s", e)
        
        # Clean up the task group if it exists and we're not keeping it
        if self._task_group is not None and not keep_task_group:
            try:
                await self._task_group.__aexit__(None, None, None)
                self._task_group = None
            except Exception as e:
                log.warning("Error closing task group: %s", e)
        
        # Close the exit stack
        try:
            await self._exit_stack.aclose()
        except Exception as e:
            log.warning("Error closing exit stack: %s", e)

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