"""
Logging configuration for the Chainlit web interface.
This module configures logging for all components, including WebSockets.
"""

import logging
import os
import sys

# Create a null handler that doesn't output anything
class NullHandler(logging.Handler):
    def emit(self, record):
        pass

def configure_logging(debug=False):
    """
    Configure logging for the Chainlit web interface.
    
    Args:
        debug (bool): Whether to enable debug logging.
    """
    # Set default log level based on debug flag
    default_level = logging.DEBUG if debug else logging.INFO
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(default_level)
    
    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create a console handler with a specific formatter
    console_handler = logging.StreamHandler()
    console_handler.setLevel(default_level)
    
    # Create formatter
    if debug:
        formatter = logging.Formatter('%(levelname)s: %(message)s')
    else:
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # Configure specific loggers
    if debug:
        # Enable debug logging for Smart Agent components
        logging.getLogger('smart_agent').setLevel(logging.DEBUG)
        logging.getLogger('smart_agent.core').setLevel(logging.DEBUG)
        logging.getLogger('smart_agent.web').setLevel(logging.DEBUG)
        logging.getLogger('mcp.client').setLevel(logging.DEBUG)
        logging.getLogger('httpx').setLevel(logging.DEBUG)
    else:
        # In normal mode, suppress verbose logging from external libraries
        logging.getLogger('asyncio').setLevel(logging.ERROR)
        logging.getLogger('httpx').setLevel(logging.WARNING)
        logging.getLogger('mcp.client.sse').setLevel(logging.WARNING)
    
    # Completely disable WebSocket-related loggers
    websocket_loggers = [
        'uvicorn',
        'uvicorn.error',
        'uvicorn.access',
        'uvicorn.websockets',
        'websockets',
        'websockets.protocol',
        'websockets.client',
        'websockets.server',
        'socketio',
        'engineio',
        'backoff'
    ]
    
    # Create a null handler
    null_handler = NullHandler()
    
    # Apply aggressive suppression to WebSocket loggers
    for logger_name in websocket_loggers:
        logger = logging.getLogger(logger_name)
        # Remove all handlers
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        # Add null handler
        logger.addHandler(null_handler)
        # Set to highest level
        logger.setLevel(logging.CRITICAL)
        # Prevent propagation to parent loggers
        logger.propagate = False
    
    # Set environment variables to control uvicorn logging
    os.environ["UVICORN_LOG_LEVEL"] = "critical"
    os.environ["UVICORN_ACCESS_LOG"] = "0"
    os.environ["UVICORN_ERROR_LOG"] = "0"
    
    # Monkey patch the uvicorn logger config function
    try:
        import uvicorn.config
        original_configure_logging = uvicorn.config.LOGGING_CONFIG
        
        def patched_logging_config(*args, **kwargs):
            result = original_configure_logging(*args, **kwargs)
            # After uvicorn configures logging, reapply our settings
            for logger_name in websocket_loggers:
                logger = logging.getLogger(logger_name)
                for handler in logger.handlers[:]:
                    logger.removeHandler(handler)
                logger.addHandler(null_handler)
                logger.setLevel(logging.CRITICAL)
                logger.propagate = False
            return result
        
        uvicorn.config.LOGGING_CONFIG = patched_logging_config
    except ImportError:
        pass
    
    # Print debug status
    if debug:
        print("DEBUG MODE ENABLED - Smart Agent running with verbose logging (WebSocket logs suppressed)")
        logging.getLogger(__name__).debug("Debug mode enabled - setting verbose logging")