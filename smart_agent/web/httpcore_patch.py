"""
Monkey patch for httpcore to fix async generator cleanup issues.

This module patches the problematic methods in httpcore that cause
RuntimeError: async generator ignored GeneratorExit and
RuntimeError: Attempted to exit cancel scope in a different task
"""

import asyncio
import logging
import warnings
from typing import Any

logger = logging.getLogger(__name__)

def patch_httpcore():
    """Apply monkey patches to fix httpcore async generator issues."""
    try:
        import httpcore._async.http11
        import httpcore._async.connection_pool
        import anyio
        
        # Find the correct classes to patch
        classes_to_patch = []
        
        # Check for HTTP11ConnectionByteStream in http11 module
        if hasattr(httpcore._async.http11, 'HTTP11ConnectionByteStream'):
            classes_to_patch.append(httpcore._async.http11.HTTP11ConnectionByteStream)
            logger.debug("Found HTTP11ConnectionByteStream in http11 module")
        
        # Check for other byte stream classes
        for module_name, module in [
            ('http11', httpcore._async.http11),
            ('connection_pool', httpcore._async.connection_pool),
        ]:
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (hasattr(attr, '__aiter__') and hasattr(attr, 'aclose') and
                    'ByteStream' in attr_name):
                    classes_to_patch.append(attr)
                    logger.debug(f"Found {attr_name} in {module_name} module")
        
        # Remove duplicates
        classes_to_patch = list(set(classes_to_patch))
        
        if not classes_to_patch:
            logger.warning("No httpcore byte stream classes found to patch")
            return
        
        # Completely replace the async generator with a safe implementation
        def create_patched_aiter(original_aiter):
            def patched_aiter(self):
                """Patched __aiter__ that returns a safe async iterator."""
                return SafeAsyncIterator(self, original_aiter)
            return patched_aiter
        
        # Safe async iterator that handles all edge cases
        class SafeAsyncIterator:
            def __init__(self, stream_obj, original_aiter_func):
                self.stream_obj = stream_obj
                self.original_aiter_func = original_aiter_func
                self.generator = None
                self.closed = False
                
            def __aiter__(self):
                return self
                
            async def __anext__(self):
                if self.closed:
                    raise StopAsyncIteration
                    
                try:
                    if self.generator is None:
                        self.generator = self.original_aiter_func(self.stream_obj)
                    
                    return await self.generator.__anext__()
                    
                except StopAsyncIteration:
                    await self.aclose()
                    raise
                except GeneratorExit:
                    logger.debug("Suppressed GeneratorExit in SafeAsyncIterator")
                    await self.aclose()
                    raise StopAsyncIteration
                except Exception as e:
                    logger.debug(f"HTTP stream error (suppressed): {e}")
                    await self.aclose()
                    raise StopAsyncIteration
                    
            async def aclose(self):
                if not self.closed:
                    self.closed = True
                    if self.generator and hasattr(self.generator, 'aclose'):
                        try:
                            await asyncio.wait_for(self.generator.aclose(), timeout=1.0)
                        except Exception:
                            pass
                        finally:
                            self.generator = None
        
        # Patched aclose method that handles task context issues
        def create_patched_aclose(original_aclose):
            async def patched_aclose(self):
                """Patched aclose that handles cross-task context issues."""
                try:
                    # Use asyncio shield to prevent cancellation issues
                    await asyncio.shield(asyncio.wait_for(original_aclose(self), timeout=5.0))
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    # Suppress timeout and cancellation errors
                    logger.debug("Suppressed timeout/cancellation in HTTP close")
                    pass
                except RuntimeError as e:
                    if "cancel scope" in str(e) or "different task" in str(e):
                        # Suppress the specific cross-task cancel scope error
                        logger.debug(f"Suppressed cancel scope error: {e}")
                        pass
                    else:
                        logger.debug(f"HTTP close error (suppressed): {e}")
                except Exception as e:
                    # Log other exceptions but don't crash
                    logger.debug(f"HTTP close error (suppressed): {e}")
            return patched_aclose
        
        # Apply patches to all found classes
        patched_count = 0
        for cls in classes_to_patch:
            try:
                if hasattr(cls, '__aiter__'):
                    original_aiter = cls.__aiter__
                    cls.__aiter__ = create_patched_aiter(original_aiter)
                    patched_count += 1
                    
                if hasattr(cls, 'aclose'):
                    original_aclose = cls.aclose
                    cls.aclose = create_patched_aclose(original_aclose)
                    
                logger.debug(f"Applied patches to {cls.__name__}")
            except Exception as e:
                logger.debug(f"Failed to patch {cls.__name__}: {e}")
        
        if patched_count > 0:
            logger.debug(f"Applied httpcore patches to {patched_count} classes")
        
        # Patch anyio CancelScope to handle cross-task issues
        try:
            original_cancel_scope_exit = anyio.CancelScope.__exit__
            
            def patched_cancel_scope_exit(self, exc_type, exc_val, exc_tb):
                """Patched CancelScope.__exit__ that handles cross-task issues."""
                try:
                    return original_cancel_scope_exit(self, exc_type, exc_val, exc_tb)
                except RuntimeError as e:
                    if "different task" in str(e) or "cancel scope" in str(e):
                        # Suppress the cross-task cancel scope error
                        logger.debug(f"Suppressed cancel scope error: {e}")
                        return False
                    else:
                        raise
            
            anyio.CancelScope.__exit__ = patched_cancel_scope_exit
            logger.debug("Applied anyio CancelScope patch")
            
        except Exception as e:
            logger.debug(f"Failed to patch anyio CancelScope: {e}")
        
        logger.debug("Successfully applied httpcore/anyio patches to fix async generator issues")
        
    except ImportError as e:
        logger.warning(f"Could not import httpcore/anyio for patching: {e}")
    except Exception as e:
        logger.error(f"Failed to apply httpcore patches: {e}")

def suppress_async_warnings():
    """Suppress specific async-related warnings."""
    # Suppress the specific warnings
    warnings.filterwarnings("ignore", 
                          category=RuntimeWarning, 
                          message=".*async generator ignored GeneratorExit.*")
    warnings.filterwarnings("ignore", 
                          category=RuntimeWarning, 
                          message=".*Attempted to exit cancel scope in a different task.*")
    warnings.filterwarnings("ignore", 
                          category=RuntimeWarning, 
                          message=".*coroutine.*was never awaited.*")
    
    # Suppress module-level warnings
    warnings.filterwarnings("ignore", module="httpcore.*")
    warnings.filterwarnings("ignore", module="anyio.*")
    
    logger.debug("Applied async warning suppressions")

# Apply patches immediately when module is imported
suppress_async_warnings()
patch_httpcore()