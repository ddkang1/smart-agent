# Streamable HTTP Transport for Smart Agent

This document describes the new Streamable HTTP transport option added to Smart Agent, which provides an efficient alternative to SSE (Server-Sent Events) transport for MCP (Model Context Protocol) servers.

## Overview

Streamable HTTP is a transport mechanism that allows for bidirectional streaming communication between MCP clients and servers over HTTP. It offers several advantages over traditional SSE transport:

- **Bidirectional Communication**: Unlike SSE which is unidirectional, Streamable HTTP allows both client and server to send messages
- **Better Connection Management**: More efficient handling of connection lifecycle and error recovery
- **Improved Performance**: Reduced overhead compared to SSE for high-frequency message exchanges
- **Standard HTTP**: Built on standard HTTP protocols, making it easier to deploy and debug

## Configuration

To use the Streamable HTTP transport, configure your tools in the YAML configuration file with `transport: streamable-http`:

```yaml
tools:
  my_tool:
    enabled: true
    url: http://localhost:8000/mcp
    transport: streamable-http
    headers:  # Optional custom headers
      Authorization: "Bearer your-token-here"
      X-Custom-Header: "custom-value"
    timeouts:  # Optional timeout configurations
      timeout: 30                    # HTTP request timeout in seconds
      sse_read_timeout: 300         # SSE read timeout in seconds
      client_session_timeout: 30    # MCP client session timeout in seconds
```

### Configuration Options

- **url**: The HTTP endpoint of your MCP server (required)
- **transport**: Set to `streamable-http` or `streamable_http` (required)
- **headers**: Optional dictionary of HTTP headers to send with requests
- **timeouts**: Optional timeout configurations
  - `timeout`: HTTP request timeout in seconds (default: 30)
  - `sse_read_timeout`: SSE read timeout for underlying streams in seconds (default: 300)
  - `client_session_timeout`: MCP client session timeout in seconds (default: 30)

## Creating a Streamable HTTP MCP Server

You can create an MCP server that supports Streamable HTTP transport using the FastMCP framework:

```python
from mcp.server.fastmcp import FastMCP

# Create server
mcp = FastMCP("My MCP Server")

@mcp.tool()
def my_tool(param: str) -> str:
    """Example tool function"""
    return f"Processed: {param}"

if __name__ == "__main__":
    # Run with streamable-http transport
    mcp.run(transport="streamable-http", host="localhost", port=8000)
```

The server will be available at `http://localhost:8000/mcp`.

## Example Usage

### 1. Start the Example Server

```bash
cd smart-agent
python examples/streamable_http_server.py
```

### 2. Configure Smart Agent

Create a configuration file (e.g., `config-streamable-http.yaml`):

```yaml
llm:
  base_url: "http://your-llm-server:4001"
  model: "your-model"
  api_key: "your-api-key"

tools:
  example_server:
    enabled: true
    url: http://localhost:8000/mcp
    transport: streamable-http
```

### 3. Test the Connection

```bash
cd smart-agent
python examples/test_streamable_http.py
```

## Comparison with Other Transports

| Transport | Direction | Use Case | Pros | Cons |
|-----------|-----------|----------|------|------|
| **streamable-http** | Bidirectional | Remote HTTP servers | Efficient, bidirectional, standard HTTP | Requires HTTP server |
| **sse** | Unidirectional | Remote HTTP servers | Simple, widely supported | One-way communication only |
| **stdio** | Bidirectional | Local processes | Direct process communication | Local only |

## Migration from SSE

To migrate from SSE to Streamable HTTP transport:

1. **Update your server**: Ensure your MCP server supports Streamable HTTP (most FastMCP servers do)
2. **Update configuration**: Change `transport: sse` to `transport: streamable-http`
3. **Update URL**: The URL might change from `/sse` to `/mcp` (check your server documentation)
4. **Test thoroughly**: Verify all tools work correctly with the new transport

Example migration:

```yaml
# Before (SSE)
tools:
  my_tool:
    enabled: true
    url: http://localhost:8000/sse
    transport: sse

# After (Streamable HTTP)
tools:
  my_tool:
    enabled: true
    url: http://localhost:8000/mcp
    transport: streamable-http
```

## Troubleshooting

### Connection Issues

1. **Server not responding**: Ensure your MCP server is running and accessible at the configured URL
2. **Timeout errors**: Increase timeout values in the configuration
3. **Authentication errors**: Check that headers (especially Authorization) are correctly configured

### Performance Issues

1. **Slow responses**: Consider adjusting timeout values
2. **Connection drops**: Check network stability and server logs
3. **High latency**: Ensure server and client are on the same network when possible

### Debugging

Enable debug logging to see detailed connection information:

```yaml
logging:
  level: DEBUG
```

## Implementation Details

The Streamable HTTP transport is implemented using:

- **FastMCP Client**: Leverages the `StreamableHttpTransport` from the fastmcp library
- **Async Context Management**: Proper connection lifecycle management with async context managers
- **Error Recovery**: Automatic reconnection on connection failures
- **Timeout Handling**: Configurable timeouts for different aspects of the connection

## Best Practices

1. **Use appropriate timeouts**: Set timeouts based on your tool's expected response times
2. **Handle authentication**: Use headers for API keys or tokens when needed
3. **Monitor connections**: Enable logging to monitor connection health
4. **Test thoroughly**: Always test your configuration before deploying to production
5. **Consider fallbacks**: Have backup transport options configured if possible

## Future Enhancements

Planned improvements for the Streamable HTTP transport include:

- Connection pooling for better performance
- Automatic retry mechanisms with exponential backoff
- Health check endpoints for monitoring
- Support for WebSocket upgrades where beneficial