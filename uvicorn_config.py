"""
Custom uvicorn configuration to suppress WebSocket logs.
"""

import logging

# Configure logging
LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": True,
    "formatters": {
        "default": {
            "()": "uvicorn.logging.DefaultFormatter",
            "fmt": "%(levelprefix)s %(message)s",
            "use_colors": None,
        },
        "access": {
            "()": "uvicorn.logging.AccessFormatter",
            "fmt": '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
        },
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
        "access": {
            "formatter": "access",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
        },
        "null": {
            "class": "logging.NullHandler",
        },
    },
    "loggers": {
        "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
        # Set WebSocket loggers to use null handler
        "uvicorn.websockets": {"handlers": ["null"], "level": "CRITICAL", "propagate": False},
        "websockets": {"handlers": ["null"], "level": "CRITICAL", "propagate": False},
        "websockets.protocol": {"handlers": ["null"], "level": "CRITICAL", "propagate": False},
        "websockets.client": {"handlers": ["null"], "level": "CRITICAL", "propagate": False},
        "websockets.server": {"handlers": ["null"], "level": "CRITICAL", "propagate": False},
        "socketio": {"handlers": ["null"], "level": "CRITICAL", "propagate": False},
        "engineio": {"handlers": ["null"], "level": "CRITICAL", "propagate": False},
    },
}

# Set log levels
log_level = "info"