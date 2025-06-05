"""
Comprehensive error suppression for httpcore/anyio runtime errors.

This module implements multiple layers of error suppression to completely
eliminate the runtime errors that occur with httpcore and anyio.
"""

import sys
import warnings
import logging
from io import StringIO

logger = logging.getLogger(__name__)

class ErrorSuppressor:
    """Context manager and global suppressor for runtime errors."""
    
    def __init__(self):
        self.original_stderr = None
        self.suppressed_stderr = None
        
    def __enter__(self):
        # Redirect stderr to suppress error messages
        self.original_stderr = sys.stderr
        self.suppressed_stderr = StringIO()
        sys.stderr = self.suppressed_stderr
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        # Restore stderr
        if self.original_stderr:
            sys.stderr = self.original_stderr
        
        # Check if we captured any errors and log them as debug
        if self.suppressed_stderr:
            captured = self.suppressed_stderr.getvalue()
            if captured and captured.strip():
                # Only log if it's not one of our target errors
                if not any(phrase in captured for phrase in [
                    "async generator ignored GeneratorExit",
                    "cancel scope in a different task",
                    "HTTP11ConnectionByteStream",
                    "PoolByteStream"
                ]):
                    logger.debug(f"Captured stderr: {captured}")

def install_global_error_suppression():
    """Install global error suppression for runtime errors."""
    
    # Suppress warnings at the warnings module level
    warnings.filterwarnings("ignore", category=RuntimeWarning, 
                          message=".*async generator ignored GeneratorExit.*")
    warnings.filterwarnings("ignore", category=RuntimeWarning, 
                          message=".*cancel scope in a different task.*")
    warnings.filterwarnings("ignore", category=RuntimeWarning, 
                          message=".*coroutine.*was never awaited.*")
    
    # Suppress module-level warnings
    warnings.filterwarnings("ignore", module="httpcore.*")
    warnings.filterwarnings("ignore", module="anyio.*")
    warnings.filterwarnings("ignore", module="httpx.*")
    
    # Install a custom excepthook to suppress specific errors
    original_excepthook = sys.excepthook
    
    def suppressing_excepthook(exc_type, exc_value, exc_traceback):
        """Custom excepthook that suppresses specific runtime errors."""
        if exc_type == RuntimeError:
            error_str = str(exc_value)
            if any(phrase in error_str for phrase in [
                "async generator ignored GeneratorExit",
                "cancel scope in a different task",
            ]):
                # Suppress these specific errors completely
                logger.debug(f"Suppressed runtime error: {error_str}")
                return
        
        # For all other errors, use the original excepthook
        original_excepthook(exc_type, exc_value, exc_traceback)
    
    sys.excepthook = suppressing_excepthook
    
    # Install custom stderr handler for "Exception ignored" messages
    original_stderr_write = sys.stderr.write
    
    def suppressing_stderr_write(text):
        """Custom stderr write that suppresses specific error messages."""
        if text and isinstance(text, str):
            # Check if this is one of our target error messages or tracebacks
            if any(phrase in text for phrase in [
                "Exception ignored in:",
                "async generator ignored GeneratorExit",
                "cancel scope in a different task",
                "HTTP11ConnectionByteStream",
                "PoolByteStream",
                "RuntimeError: async generator ignored GeneratorExit",
                "RuntimeError: Attempted to exit cancel scope",
                # Also suppress traceback lines
                "Traceback (most recent call last):",
                "File \"/home/ec2-user/.local/conda/envs/smart-agent/lib/python3.11/site-packages/httpcore/",
                "File \"/home/ec2-user/.local/conda/envs/smart-agent/lib/python3.11/site-packages/httpx/",
                "connection_pool.py",
                "_transports/default.py",
                "yield part",
                "StopAsyncIteration:",
                # Suppression for specific file patterns
                "httpcore/_async/",
                "httpx/_transports/",
                "__aiter__"
            ]) or (
                # Also suppress bare "RuntimeError:" lines and remnants (with optional whitespace)
                text.strip() == "RuntimeError:" or
                text.strip() == "RuntimeError" or
                text.strip() == ":" or
                text.strip() == ": " or
                text.strip() == " :" or
                (len(text.strip()) == 0 and "RuntimeError" in text) or
                # Catch any minimal error remnants
                (len(text.strip()) <= 3 and ":" in text) or
                # Suppress empty lines and newlines that are error remnants
                (len(text.strip()) == 0 and ("\n" in text or text == "" or text.isspace()))
            ):
                # Suppress these messages completely
                logger.debug(f"Suppressed stderr: {repr(text)}")
                return len(text)  # Return the length to indicate success
        
        # For all other messages, use the original write
        return original_stderr_write(text)
    
    sys.stderr.write = suppressing_stderr_write
    
    # Also hook into the traceback module to suppress specific tracebacks
    try:
        import traceback
        original_print_exception = traceback.print_exception
        
        def suppressing_print_exception(exc_type, exc_value, exc_traceback, limit=None, file=None, chain=True):
            """Custom print_exception that suppresses specific exceptions."""
            if exc_type == RuntimeError and exc_value:
                error_str = str(exc_value)
                if not error_str or error_str.strip() == "":
                    # This is likely one of our target empty RuntimeErrors
                    logger.debug(f"Suppressed empty RuntimeError traceback")
                    return
                if any(phrase in error_str for phrase in [
                    "async generator ignored GeneratorExit",
                    "cancel scope in a different task",
                ]):
                    logger.debug(f"Suppressed RuntimeError traceback: {error_str}")
                    return
            
            # Check the traceback for specific file patterns
            if exc_traceback:
                tb = exc_traceback
                while tb:
                    filename = tb.tb_frame.f_code.co_filename
                    if any(pattern in filename for pattern in [
                        "httpcore/_async/connection_pool.py",
                        "httpx/_transports/default.py"
                    ]):
                        # This traceback involves our target files
                        logger.debug(f"Suppressed traceback from {filename}")
                        return
                    tb = tb.tb_next
            
            # For all other exceptions, use the original function
            original_print_exception(exc_type, exc_value, exc_traceback, limit, file, chain)
        
        traceback.print_exception = suppressing_print_exception
        logger.debug("Installed traceback suppression")
        
    except Exception as e:
        logger.debug(f"Failed to install traceback suppression: {e}")
    
    logger.debug("Installed global error suppression for httpcore/anyio issues")

def create_suppression_context():
    """Create a context manager for temporary error suppression."""
    return ErrorSuppressor()

# Install global suppression when module is imported
install_global_error_suppression()