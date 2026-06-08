"""
Loguru setup — console always, file optional.

Trimmed from the production spec to suit the CV core: console output by default,
plus a rotating file sink when LOG_FILE_PATH is set.
"""
import os
import sys

from loguru import logger

_CONSOLE_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{line}</cyan> | <level>{message}</level>"
)


def setup_logging():
    logger.remove()
    level = os.getenv("LOG_LEVEL", "INFO")

    logger.add(sys.stdout, level=level, colorize=True, format=_CONSOLE_FORMAT)

    log_file = os.getenv("LOG_FILE_PATH")
    if log_file:
        os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
        logger.add(
            log_file,
            level=level,
            rotation=os.getenv("LOG_ROTATION", "50 MB"),
            retention=os.getenv("LOG_RETENTION", "7 days"),
            compression="zip",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{line} | {message}",
        )

    logger.info(f"Logging initialized | level={level}")
    return logger
