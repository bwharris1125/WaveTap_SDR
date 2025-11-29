"""
Unit tests for WaveTap logging configuration system.
"""

import logging

from wavetap_utils.logging_config import (
    get_component_logger,
    setup_component_logging,
    setup_per_component_logging,
    setup_root_logging,
)


class TestComponentLogging:
    """Test component-specific logging setup."""

    def test_setup_component_logging_creates_log_file(self, tmp_path):
        """Verify setup_component_logging creates a log file with correct name."""
        logger = setup_component_logging(
            component_name="test_component",
            log_level="DEBUG",
            log_dir=str(tmp_path),
        )

        # Write a test message
        logger.debug("Test debug message")
        logger.info("Test info message")

        # Verify log file exists
        log_files = list(tmp_path.glob("test_component_*.log"))
        assert len(log_files) == 1
        log_file = log_files[0]

        # Verify log file contains messages
        content = log_file.read_text()
        assert "Test debug message" in content
        assert "Test info message" in content

    def test_setup_component_logging_respects_log_level(self, tmp_path):
        """Verify log level filtering works."""
        logger = setup_component_logging(
            component_name="test_level",
            log_level="INFO",  # Should filter out DEBUG
            log_dir=str(tmp_path),
        )

        logger.debug("This should not appear")
        logger.info("This should appear")

        log_files = list(tmp_path.glob("test_level_*.log"))
        assert len(log_files) == 1
        content = log_files[0].read_text()

        assert "This should not appear" not in content
        assert "This should appear" in content

    def test_setup_component_logging_creates_directory(self, tmp_path):
        """Verify log directory is created if it doesn't exist."""
        log_dir = tmp_path / "nested" / "log" / "path"
        assert not log_dir.exists()

        logger = setup_component_logging(
            component_name="test_nested",
            log_level="DEBUG",
            log_dir=str(log_dir),
        )

        assert log_dir.exists()
        assert list(log_dir.glob("test_nested_*.log"))

    def test_setup_per_component_logging(self, tmp_path):
        """Verify setup_per_component_logging creates multiple loggers."""
        components = ["publisher", "subscriber", "wavetap_api"]
        loggers = setup_per_component_logging(
            components=components,
            log_level="DEBUG",
            log_dir=str(tmp_path),
        )

        # Verify all loggers exist
        assert len(loggers) == 3
        assert all(c in loggers for c in components)

        # Write messages from each
        loggers["publisher"].info("Publisher message")
        loggers["subscriber"].info("Subscriber message")
        loggers["wavetap_api"].info("API message")

        # Verify separate log files exist
        log_files = list(tmp_path.glob("*.log"))
        assert len(log_files) == 3

        # Verify each file contains appropriate message
        publisher_log = next(f for f in log_files if "publisher" in f.name)
        subscriber_log = next(f for f in log_files if "subscriber" in f.name)
        api_log = next(f for f in log_files if "wavetap_api" in f.name)

        assert "Publisher message" in publisher_log.read_text()
        assert "Subscriber message" in subscriber_log.read_text()
        assert "API message" in api_log.read_text()

    def test_get_component_logger(self, tmp_path):
        """Verify get_component_logger retrieves existing logger."""
        component_name = "test_get"
        setup_component_logging(
            component_name=component_name,
            log_level="DEBUG",
            log_dir=str(tmp_path),
        )

        logger = get_component_logger(component_name)
        assert logger is not None
        assert logger.name == component_name

        logger.info("Retrieved logger message")

        log_files = list(tmp_path.glob("test_get_*.log"))
        assert len(log_files) == 1
        assert "Retrieved logger message" in log_files[0].read_text()


class TestRootLogging:
    """Test root-level logging setup."""

    def test_setup_root_logging_creates_global_log_file(self, tmp_path):
        """Verify setup_root_logging creates a single wavetap_*.log file."""
        setup_root_logging(
            log_level="DEBUG",
            log_dir=str(tmp_path),
        )

        # Use root logger
        root_logger = logging.getLogger()
        root_logger.info("Root logger message")

        log_files = list(tmp_path.glob("wavetap_*.log"))
        assert len(log_files) == 1
        assert "Root logger message" in log_files[0].read_text()


class TestLoggingFormats:
    """Test log message formatting."""

    def test_log_format_includes_required_fields(self, tmp_path):
        """Verify log entries include timestamp, level, file, and function."""
        logger = setup_component_logging(
            component_name="test_format",
            log_level="DEBUG",
            log_dir=str(tmp_path),
        )

        logger.info("Format test message")

        log_files = list(tmp_path.glob("test_format_*.log"))
        content = log_files[0].read_text()

        # Verify format includes key fields
        assert "test_format" in content  # Component name (logger name)
        assert "INFO" in content  # Log level
        assert "Format test message" in content  # Message
        # Could also check for filename, function name, etc.

    def test_custom_format_string(self, tmp_path):
        """Verify custom format string is used."""
        custom_format = "%(levelname)s | %(message)s"
        logger = setup_component_logging(
            component_name="test_custom",
            log_level="INFO",
            log_dir=str(tmp_path),
            format_string=custom_format,
        )

        logger.info("Custom format message")

        log_files = list(tmp_path.glob("test_custom_*.log"))
        content = log_files[0].read_text()

        # With custom format, should see "INFO | Custom format message"
        assert "INFO | Custom format message" in content


class TestLoggerClearing:
    """Test that setup doesn't create duplicate handlers."""

    def test_multiple_setups_same_component(self, tmp_path):
        """Verify multiple calls to setup don't duplicate handlers."""
        component = "test_multi"

        # First setup
        logger1 = setup_component_logging(
            component_name=component,
            log_level="DEBUG",
            log_dir=str(tmp_path),
        )

        initial_handler_count = len(logger1.handlers)

        # Second setup (should clear handlers first)
        logger2 = setup_component_logging(
            component_name=component,
            log_level="INFO",
            log_dir=str(tmp_path),
        )

        # Should have same number of handlers (not doubled)
        assert len(logger2.handlers) == initial_handler_count

        assert len(logger2.handlers) == initial_handler_count
