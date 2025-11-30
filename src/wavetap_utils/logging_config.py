"""
Centralized logging configuration for WaveTap components.

Provides a convenient way to configure logging for individual components
(publisher, subscriber, wavetap_api) with their own log files.

Usage:
    # In your module's main() or __main__:
    from wavetap_utils.logging_config import setup_component_logging

    setup_component_logging(
        component_name="publisher",
        log_level="DEBUG",
        log_dir="logs"  # optional, defaults to ./logs
    )
"""

import logging
from datetime import datetime
from pathlib import Path


def setup_component_logging(
    component_name: str,
    log_level: str = "DEBUG",
    log_dir: str | None = None,
    format_string: str | None = None,
) -> logging.Logger:
    """
    Configure logging for a WaveTap component with file and console output.

    Creates a log file named {component_name}_{timestamp}.log and configures
    both file and console handlers with the specified log level.

    Args:
        component_name: Name of the component (e.g., 'publisher', 'subscriber', 'wavetap_api')
        log_level: Logging level as string (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_dir: Directory for log files. Defaults to ./tmp/logs
        format_string: Log message format. If None, uses default format.

    Returns:
        Configured logger instance

    Example:
        logger = setup_component_logging("publisher", log_level="DEBUG")
        logger.debug("Starting publisher...")
    """
    if log_dir is None:
        log_dir = "tmp/logs"

    # Create log directory if it doesn't exist
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # Get log level
    level = getattr(logging, log_level.upper(), logging.DEBUG)

    # Default format
    if format_string is None:
        format_string = (
            "%(asctime)s - %(name)s - %(levelname)s - "
            "%(filename)s:%(lineno)d - %(funcName)s() - %(message)s"
        )

    formatter = logging.Formatter(format_string)

    # Create logger
    logger = logging.getLogger(component_name)
    logger.setLevel(level)
    logger.propagate = False  # Critical: prevent messages from going to root logger

    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()

    # Create file handler
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_path / f"{component_name}_{timestamp}.log"
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Also configure root logger with file handler so logging.info/debug/etc calls are captured
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    root_file_handler = logging.FileHandler(log_file)
    root_file_handler.setLevel(level)
    root_file_handler.setFormatter(formatter)
    root_logger.addHandler(root_file_handler)
    root_console_handler = logging.StreamHandler()
    root_console_handler.setLevel(level)
    root_console_handler.setFormatter(formatter)
    root_logger.addHandler(root_console_handler)

    logger.info(f"Logging configured for {component_name} component")
    logger.info(f"Log file: {log_file}")

    return logger


def setup_root_logging(
    log_level: str = "DEBUG",
    log_dir: str | None = None,
    format_string: str | None = None,
) -> None:
    """
    Configure root logger for the entire application.

    Useful for capturing logs from all modules when a single global logger is preferred.

    Args:
        log_level: Logging level as string
        log_dir: Directory for log files
        format_string: Log message format
    """
    if log_dir is None:
        log_dir = "tmp/logs"

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, log_level.upper(), logging.DEBUG)

    if format_string is None:
        format_string = (
            "%(asctime)s - %(name)s - %(levelname)s - "
            "%(filename)s:%(lineno)d - %(funcName)s() - %(message)s"
        )

    formatter = logging.Formatter(format_string)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()

    # File handler
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_path / f"wavetap_{timestamp}.log"
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)


def get_component_logger(component_name: str) -> logging.Logger:
    """
    Get logger for a component (assumes setup_component_logging was already called).

    Args:
        component_name: Name of the component

    Returns:
        Logger instance
    """
    return logging.getLogger(component_name)


def setup_per_component_logging(
    components: list[str],
    log_level: str = "DEBUG",
    log_dir: str | None = None,
) -> dict[str, logging.Logger]:
    """
    Configure logging for multiple components, each with their own log file.

    Args:
        components: List of component names to configure
        log_level: Logging level for all components
        log_dir: Base directory for log files

    Returns:
        Dictionary mapping component names to logger instances

    Example:
        loggers = setup_per_component_logging(
            ["publisher", "subscriber", "wavetap_api"],
            log_level="DEBUG"
        )
        loggers["publisher"].debug("Debug message")
        loggers["subscriber"].info("Info message")
    """
    loggers = {}
    for component in components:
        loggers[component] = setup_component_logging(
            component_name=component,
            log_level=log_level,
            log_dir=log_dir,
        )
    return loggers
