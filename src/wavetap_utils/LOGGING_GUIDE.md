"""
WaveTap Logging Configuration Guide - Generated using CoPilot

This guide shows how to use the centralized logging system for WaveTap components.
Each component (publisher, subscriber, wavetap_api) can log to its own file.

=== QUICK START ===

1. Using environment variables (recommended):

   # Publisher
   export ADSB_PUBLISHER_LOG_LEVEL=DEBUG
   export ADSB_LOG_DIR=tmp/logs
   python src/sdr_cap/adsb_publisher.py

   # Subscriber
   export ADSB_SUBSCRIBER_LOG_LEVEL=DEBUG
   export ADSB_LOG_DIR=tmp/logs
   python src/database_api/adsb_subscriber.py

   # WaveTap API
   export WAVETAP_API_LOG_LEVEL=INFO
   export ADSB_LOG_DIR=tmp/logs
   export FLASK_DEBUG=False
   export FLASK_PORT=5000
   python src/database_api/wavetap_api.py


2. Using Python directly:

   from wavetap_utils.logging_config import setup_component_logging

   # Setup publisher logging
   logger = setup_component_logging("publisher", log_level="DEBUG", log_dir="tmp/logs")
   logger.debug("Starting publisher...")

   # Setup subscriber logging
   logger = setup_component_logging("subscriber", log_level="DEBUG", log_dir="tmp/logs")
   logger.info("Subscriber initialized")

   # Setup multiple components
   from wavetap_utils.logging_config import setup_per_component_logging
   
   loggers = setup_per_component_logging(
       components=["publisher", "subscriber", "wavetap_api"],
       log_level="DEBUG",
       log_dir="tmp/logs"
   )
   
   loggers["publisher"].debug("Publisher debug message")
   loggers["subscriber"].info("Subscriber info message")
   loggers["wavetap_api"].warning("API warning message")


=== ENVIRONMENT VARIABLES ===

ADSB_PUBLISHER_LOG_LEVEL (default: DEBUG)
   - Logging level for publisher
   - Options: DEBUG, INFO, WARNING, ERROR, CRITICAL

ADSB_SUBSCRIBER_LOG_LEVEL (default: DEBUG)
   - Logging level for subscriber
   - Options: DEBUG, INFO, WARNING, ERROR, CRITICAL

WAVETAP_API_LOG_LEVEL (default: INFO)
   - Logging level for wavetap_api
   - Options: DEBUG, INFO, WARNING, ERROR, CRITICAL

ADSB_LOG_DIR (default: tmp/logs)
   - Base directory for all component log files
   - Subdirectories are created automatically if they don't exist

FLASK_DEBUG (default: False)
   - Enable Flask debug mode for wavetap_api
   - Options: true, false (case-insensitive)

FLASK_PORT (default: 5000)
   - Port for wavetap_api Flask server

FLASK_HOST (default: 0.0.0.0)
   - Host/IP for wavetap_api Flask server


=== LOG FILE OUTPUT ===

Log files are created in the directory specified by ADSB_LOG_DIR (default: tmp/logs) with names:
- tmp/logs/publisher_20251129_143022.log
- tmp/logs/subscriber_20251129_143023.log
- tmp/logs/wavetap_api_20251129_143024.log

The timestamp ensures each run creates new log files and old logs are preserved.


=== LOG FORMAT ===

Each log entry includes:
- Timestamp (ISO format with microseconds)
- Component name (logger name)
- Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- Filename and line number
- Function name
- Log message

Example:
2025-11-29 14:30:22,123 - publisher - DEBUG - adsb_publisher.py:123 - _update_assembly_time() - Aircraft ABC123 reached full completion in 7224.77ms


=== PROGRAMMATIC USAGE ===

Use setup_component_logging() in your code:

    from wavetap_utils.logging_config import setup_component_logging
    
    # In your __main__ block
    logger = setup_component_logging(
        component_name="my_component",
        log_level="DEBUG",
        log_dir="tmp/logs"
    )
    
    logger.debug("Debug message")
    logger.info("Info message")
    logger.warning("Warning message")
    logger.error("Error message")
    logger.critical("Critical message")


To get a logger after setup:

    from wavetap_utils.logging_config import get_component_logger
    
    logger = get_component_logger("publisher")
    logger.debug("Message from elsewhere in code")


For root-level logging across all modules:

    from wavetap_utils.logging_config import setup_root_logging
    
    setup_root_logging(log_level="DEBUG", log_dir="tmp/logs")
    # Now all log messages go to tmp/logs/wavetap_{timestamp}.log


=== EXAMPLES ===

Example 1: Run all components with debugging

    export ADSB_LOG_DIR=tmp/logs
    export ADSB_PUBLISHER_LOG_LEVEL=DEBUG
    export ADSB_SUBSCRIBER_LOG_LEVEL=DEBUG
    export WAVETAP_API_LOG_LEVEL=DEBUG
    
    # In separate terminals:
    python src/sdr_cap/adsb_publisher.py
    python src/database_api/adsb_subscriber.py
    python src/database_api/wavetap_api.py


Example 2: Production configuration

    export ADSB_LOG_DIR=/var/log/wavetap
    export ADSB_PUBLISHER_LOG_LEVEL=INFO
    export ADSB_SUBSCRIBER_LOG_LEVEL=INFO
    export WAVETAP_API_LOG_LEVEL=WARNING
    export FLASK_DEBUG=false
    
    python src/sdr_cap/adsb_publisher.py &
    python src/database_api/adsb_subscriber.py &
    python src/database_api/wavetap_api.py


Example 3: Monitor logs in real-time

    # In separate terminals:
    tail -f tmp/logs/publisher_*.log
    tail -f tmp/logs/subscriber_*.log
    tail -f tmp/logs/wavetap_api_*.log


=== TROUBLESHOOTING ===

Q: Why aren't my log files being created?
A: Check that the ADSB_LOG_DIR directory is writable by the process.
   The logging system will create it if it doesn't exist.

Q: I'm getting duplicate log messages
A: This can happen if logging is configured multiple times.
   The setup_component_logging() function clears existing handlers,
   but make sure you're not calling basicConfig() or other logging setup before it.

Q: How do I change log level at runtime?
A: You can't easily change it after setup, so it's best to use environment variables.
   For testing, use different log level values when calling setup_component_logging().

Q: What if I want all logs in one file?
A: Use setup_root_logging() instead of setup_component_logging().
   This creates a single wavetap_*.log file with all messages.

Q: How do I suppress logs from specific modules?
A: After calling setup_component_logging(), get individual loggers:
   
   logging.getLogger("urllib3").setLevel(logging.WARNING)
   logging.getLogger("flask").setLevel(logging.WARNING)
"""

# This file is purely documentation; import logging_config for actual functionality
from wavetap_utils.logging_config import (
    setup_component_logging,
    setup_root_logging,
    setup_per_component_logging,
    get_component_logger,
)

__all__ = [
    "setup_component_logging",
    "setup_root_logging",
    "setup_per_component_logging",
    "get_component_logger",
]
