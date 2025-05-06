# Token Streaming Optimization for Smart Agent

This document explains the token streaming optimization implemented in Smart Agent to improve performance with long messages.

## The Problem

When streaming long messages in Chainlit, each token is sent as a separate Socket.IO event, which can cause performance issues:

1. **High Socket.IO Overhead**: Each token requires a separate network event
2. **Frequent React State Updates**: Each token triggers a state update in React
3. **Recursive Tree Traversal**: The frontend performs a recursive search through the message tree for each token
4. **String Concatenation Inefficiency**: Repeatedly appending to strings becomes inefficient for long messages

These issues can lead to UI lag, especially with long streaming responses from LLMs.

## The Solution: Token Batching

Smart Agent now includes a `SmoothStreamWrapper` class that implements token batching to optimize streaming performance:

- **Token Buffering**: Collects tokens in a buffer instead of sending each one individually
- **Periodic Flushing**: Sends tokens in batches at regular intervals
- **Background Processing**: Uses asyncio tasks to manage flushing without blocking
- **Drop-in Replacement**: Maintains the same API as the standard Chainlit Message class

## How It Works

1. When a token is received from the LLM, it's added to a buffer
2. The buffer is flushed when:
   - It reaches the configured batch size
   - The flush interval has elapsed
   - The message is sent or updated
3. When flushed, all buffered tokens are combined and sent as a single token
4. This significantly reduces the number of Socket.IO events and React state updates

## Usage

Token batching is enabled by default in Smart Agent. You can control it using command-line arguments:

```bash
# Run with default settings (batch size 20, flush interval 0.1s)
smart-agent chainlit

# Disable token batching
smart-agent chainlit --no-stream-batching

# Customize batch size and flush interval
smart-agent chainlit --batch-size 50 --flush-interval 0.2
```

### Command-line Arguments

- `--no-stream-batching`: Disable token batching
- `--batch-size`: Number of tokens to batch before sending (default: 20)
- `--flush-interval`: Time in seconds between flushes (default: 0.1)
- `--debug`: Enable debug logging, including token batching statistics

## Performance Tuning

You can adjust the batch size and flush interval to optimize performance for your specific use case:

### Batch Size

- **Smaller batch size** (e.g., 10): More responsive UI, but higher network overhead
- **Larger batch size** (e.g., 50-100): Better performance for long messages, but slightly delayed token appearance

### Flush Interval

- **Shorter interval** (e.g., 0.05s): More responsive UI, but more frequent updates
- **Longer interval** (e.g., 0.2s): Better performance, but slightly delayed token appearance

## Implementation Details

The optimization is implemented in three main files:

1. `smart_agent/core/smooth_stream.py`: Contains the `SmoothStreamWrapper` class that implements token batching
2. `smart_agent/web/chainlit_app.py`: Modified to use the wrapper based on configuration
3. `smart_agent/commands/chainlit.py`: Modified to accept token batching command-line arguments

The `SmoothStreamWrapper` wraps a Chainlit message and provides the same API, but with token batching. It's used in the `on_message` handler to wrap the assistant message before passing it to `process_query`.

## Benefits

- **Smoother UI Experience**: Reduces UI lag and jitter during streaming
- **Lower Network Overhead**: Significantly reduces the number of Socket.IO events
- **Reduced CPU Usage**: Fewer React state updates and DOM manipulations
- **Better Performance with Long Messages**: Scales well with increasing message length

## When to Adjust Settings

Consider adjusting the default settings in these scenarios:

1. **Very Long Messages**: For responses with thousands of tokens, increase the batch size to 50-100
2. **Low-End Devices**: For users on low-end devices, increase the batch size and flush interval
3. **High Responsiveness Needed**: For applications where immediate token appearance is critical, decrease the batch size and flush interval

## Technical Implementation

The `SmoothStreamWrapper` class:

1. Buffers tokens in an array
2. Uses a background task to periodically flush the buffer
3. Forwards attribute access to the underlying Chainlit message
4. Handles both regular tokens and sequence tokens (replacing content)
5. Ensures all buffered tokens are flushed when the message is sent or updated

This implementation provides significant performance improvements without modifying the Chainlit library itself.

## Configuration Flow

1. Command-line arguments are parsed by the CLI (`smart-agent chainlit`)
2. Arguments are passed to the Chainlit app as environment variables
3. The Chainlit app reads these environment variables and configures token batching accordingly
4. When a message is created, it's wrapped with `SmoothStreamWrapper` if token batching is enabled
5. The wrapper handles token batching transparently, maintaining the same API as the standard Chainlit Message class

This approach allows for easy configuration without modifying the Chainlit library itself.