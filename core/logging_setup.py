"""Logging setup. Sample-level messages stay at DEBUG so the log stays small."""

import logging
from logging.handlers import RotatingFileHandler

from core.config import Settings


def configure_logging(settings: Settings) -> None:
    """Attach one rotating file handler and one console handler to the nexus logger."""
    logger = logging.getLogger("nexus")
    if logger.handlers:
        return

    logger.setLevel(settings.log_level)
    logger.propagate = False
    settings.log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    file_handler = RotatingFileHandler(
        settings.log_path,
        maxBytes=512_000,
        backupCount=2,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.WARNING)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
