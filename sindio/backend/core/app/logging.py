import structlog
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Configure root logger to output to file and stdout
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# File handler
log_file = Path("app.log")
file_handler = RotatingFileHandler(log_file, maxBytes=10485760, backupCount=5)
file_handler.setFormatter(logging.Formatter('%(message)s'))

# Stream handler
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(logging.Formatter('%(message)s'))

root_logger.handlers = []
root_logger.addHandler(file_handler)
root_logger.addHandler(stream_handler)

# Configure structlog to emit JSON lines
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="ISO", utc=True),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

# Export a ready-to-use logger
logger = structlog.get_logger("sindio")
