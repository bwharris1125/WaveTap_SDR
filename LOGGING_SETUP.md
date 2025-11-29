## WaveTap Component Logging Configuration

A centralized logging system has been implemented that allows each WaveTap component (publisher, subscriber, wavetap_api) to log debug output to its own file.

### Features

✅ **Component-specific log files** - Each component logs to its own file with timestamps
✅ **Configurable log levels** - Set per-component via environment variables
✅ **Automatic directory creation** - Log directories are created automatically
✅ **Clean API** - Simple setup functions for easy integration
✅ **Console + File output** - Logs go to both stdout and files simultaneously
✅ **No breaking changes** - Fully backwards compatible with existing code
✅ **9 comprehensive unit tests** - All tests passing

### Files Added/Modified

**New files:**
- `/src/wavetap_utils/logging_config.py` - Core logging configuration module
- `/src/wavetap_utils/LOGGING_GUIDE.md` - Comprehensive usage guide
- `/tests/test_wavetap_utils/test_logging_config.py` - 9 unit tests
- `/tests/test_wavetap_utils/__init__.py` - Package marker

**Modified files:**
- `/src/sdr_cap/adsb_publisher.py` - Updated to use logging config
- `/src/database_api/adsb_subscriber.py` - Updated to use logging config
- `/src/database_api/wavetap_api.py` - Updated to use logging config

### Quick Start

**Option 1: Using environment variables (recommended)**
```bash
export ADSB_LOG_DIR=tmp/logs
export ADSB_PUBLISHER_LOG_LEVEL=DEBUG
export ADSB_SUBSCRIBER_LOG_LEVEL=DEBUG
export WAVETAP_API_LOG_LEVEL=INFO

python src/sdr_cap/adsb_publisher.py
python src/database_api/adsb_subscriber.py
python src/database_api/wavetap_api.py
```

Each component will create its own log file:
- `tmp/logs/publisher_20251129_143022.log`
- `tmp/logs/subscriber_20251129_143023.log`
- `tmp/logs/wavetap_api_20251129_143024.log`

**Option 2: In Python code**
```python
from wavetap_utils.logging_config import setup_component_logging

logger = setup_component_logging("my_component", log_level="DEBUG", log_dir="tmp/logs")
logger.debug("Debug message")
logger.info("Info message")
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ADSB_LOG_DIR` | `tmp/logs` | Base directory for all log files |
| `ADSB_PUBLISHER_LOG_LEVEL` | `DEBUG` | Log level for publisher |
| `ADSB_SUBSCRIBER_LOG_LEVEL` | `DEBUG` | Log level for subscriber |
| `WAVETAP_API_LOG_LEVEL` | `INFO` | Log level for wavetap_api |
| `FLASK_DEBUG` | `False` | Enable Flask debug mode |
| `FLASK_PORT` | `5000` | Flask server port |
| `FLASK_HOST` | `0.0.0.0` | Flask server host |

### Log File Format

Each log entry includes:
```
2025-11-29 14:30:22,123 - publisher - DEBUG - adsb_publisher.py:123 - _update_assembly_time() - Aircraft ABC123 reached full completion in 7224.77ms
```

Breakdown:
- **Timestamp** - ISO format with microseconds
- **Component** - Logger name (publisher, subscriber, wavetap_api)
- **Level** - DEBUG, INFO, WARNING, ERROR, CRITICAL
- **File:Line** - Source code location
- **Function** - Function name
- **Message** - Log message

### API Reference

**Main Functions:**

1. `setup_component_logging(component_name, log_level="DEBUG", log_dir="tmp/logs", format_string=None)`
   - Configure logging for a single component
   - Returns: logger instance

2. `setup_root_logging(log_level="DEBUG", log_dir="tmp/logs", format_string=None)`
   - Configure root logger for all modules
   - Creates single wavetap_*.log file

3. `setup_per_component_logging(components, log_level="DEBUG", log_dir="tmp/logs")`
   - Configure multiple components at once
   - Returns: dict of {component_name: logger}

4. `get_component_logger(component_name)`
   - Get logger after it's been setup
   - Returns: logger instance

### Examples

**Monitor all logs in real-time:**
```bash
# Terminal 1
tail -f tmp/logs/publisher_*.log

# Terminal 2
tail -f tmp/logs/subscriber_*.log

# Terminal 3
tail -f tmp/logs/wavetap_api_*.log
```

**Production configuration:**
```bash
export ADSB_LOG_DIR=/var/log/wavetap
export ADSB_PUBLISHER_LOG_LEVEL=INFO
export ADSB_SUBSCRIBER_LOG_LEVEL=INFO
export WAVETAP_API_LOG_LEVEL=WARNING
export FLASK_DEBUG=false
```

**Development with full debugging:**
```bash
export ADSB_LOG_DIR=tmp/logs
export ADSB_PUBLISHER_LOG_LEVEL=DEBUG
export ADSB_SUBSCRIBER_LOG_LEVEL=DEBUG
export WAVETAP_API_LOG_LEVEL=DEBUG
export FLASK_DEBUG=true
```

### Testing

All logging functionality is tested with 9 comprehensive tests:
```bash
pytest tests/test_wavetap_utils/test_logging_config.py -v
```

✅ Tests verify:
- Log files are created with correct names
- Log levels filter messages correctly
- Directories are created automatically
- Multiple components work independently
- Log format includes all required fields
- Custom format strings work
- Multiple setups don't duplicate handlers

### Troubleshooting

**Q: Log files aren't being created?**
A: Check that the directory specified in `ADSB_LOG_DIR` is writable.

**Q: Seeing duplicate messages?**
A: Make sure you're not calling `logging.basicConfig()` before `setup_component_logging()`.

**Q: Need to change log level at runtime?**
A: Use environment variables before starting the component, as levels are set at initialization.

**Q: Want all logs in one file?**
A: Use `setup_root_logging()` instead of `setup_component_logging()`.

### See Also

- `src/wavetap_utils/LOGGING_GUIDE.md` - Detailed guide with more examples
- `tests/test_wavetap_utils/test_logging_config.py` - Test cases showing usage patterns
