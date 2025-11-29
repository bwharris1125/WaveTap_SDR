# Tmp Directory Refactoring Summary

## Overview
Successfully refactored the WaveTap application to use a centralized `tmp` directory at the project root for organizing metrics and logs.

## Directory Structure Created
```
/home/bwharris/cs7319/project/
├── tmp/
│   ├── logs/          # All component log files
│   └── metrics/       # All metrics CSV files
```

## Changes Made

### 1. Directory Creation
- Created `/tmp/logs` subdirectory for log files
- Created `/tmp/metrics` subdirectory for metrics CSV files

### 2. Logging Configuration Updates

**src/wavetap_utils/logging_config.py**
- Changed default `log_dir` from `"logs"` to `"tmp/logs"` in `setup_component_logging()`
- Changed default `log_dir` from `"logs"` to `"tmp/logs"` in `setup_root_logging()`

**src/sdr_cap/adsb_publisher.py**
- Updated environment variable default: `ADSB_LOG_DIR` from `"logs"` to `"tmp/logs"`

**src/database_api/adsb_subscriber.py**
- Updated environment variable default: `ADSB_LOG_DIR` from `"logs"` to `"tmp/logs"`

**src/database_api/wavetap_api.py**
- Updated environment variable default: `ADSB_LOG_DIR` from `"logs"` to `"tmp/logs"`

### 3. Metrics Configuration Updates

**src/wavetap_utils/metrics.py**
- Updated `DroppedTCPPacketsCollector.start_csv_logging()`:
  - Default metrics directory changed from `"metrics"` to `"tmp/metrics"`
  - Updated path construction: `Path.cwd() / "tmp" / "metrics"` with `parents=True`
  - Updated docstring to reflect new location

### 4. Documentation Updates

**src/wavetap_utils/LOGGING_GUIDE.md**
- Updated all environment variable examples to use `ADSB_LOG_DIR=tmp/logs`
- Updated Python code examples to use `log_dir="tmp/logs"`
- Updated expected log file paths to include `tmp/logs/` prefix
- Updated troubleshooting section with correct tail commands

**LOGGING_SETUP.md**
- Updated quick start environment variables to use `ADSB_LOG_DIR=tmp/logs`
- Updated API reference to show `log_dir="tmp/logs"` as default
- Updated log file path examples with `tmp/logs/` prefix
- Updated monitoring examples with new paths

### 5. Examples Updates

**examples/logging_examples.py**
- Updated all 6 examples to use `log_dir="tmp/logs"`
- Updated print statements to reference `tmp/logs/` paths
- All [OK] indicators verified for accuracy

### 6. .gitignore Updates

**.gitignore**
- Changed: `/metrics` → `/tmp`
- Now ignores entire tmp directory to prevent version control of runtime artifacts

## Verification

### Tests Passed
```bash
pytest tests/test_wavetap_utils/test_logging_config.py -v
# Result: 9/9 tests passed
```

### Syntax Validation
```bash
python -m py_compile examples/logging_examples.py
# Result: Syntax OK
```

### Directory Structure Verified
```
tmp/
├── logs/          [empty - created for log files]
└── metrics/       [empty - created for metrics CSV files]
```

## Configuration Notes

### Environment Variables
Users can still override the default locations using environment variables:

```bash
# Override log directory
export ADSB_LOG_DIR=/custom/log/path

# Override metrics directory (in Python code, still defaults to tmp/metrics)
# To customize, pass file_path parameter to start_csv_logging()
```

### Backwards Compatibility
- All changes are backwards compatible
- Existing code continues to work with new default paths
- Environment variables still take precedence over defaults
- No breaking changes to public APIs

## Files Modified Summary
- 5 source files updated with new defaults
- 2 documentation files updated
- 1 examples file updated
- 1 .gitignore updated
- 2 directories created

## Benefits
1. **Organized Structure**: All runtime artifacts in single `tmp` directory
2. **Clean Version Control**: Single `/tmp` entry in .gitignore instead of multiple entries
3. **Professional Layout**: Follows common application conventions
4. **Consistent Location**: Metrics and logs co-located for easier management
5. **Ease of Cleanup**: Users can simply `rm -rf tmp/*` to clean all artifacts
