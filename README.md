# WaveTap SDR Utilities (CS7319 - Software Architecture)

Repository for SMU Software Architecture (CS7319) Class Project
<p align="center">
   <img src="documentation/wavetap_icon.png" 
   alt="WaveTap Logo" width="200"/>
   <div style="text-align: center;">
      <strong><em>ADS-B and SDR Utilities</em></strong>
   </div>
</p>

## Containerized microservices

Docker build contexts for each deployable component live under `docker/` so the ADS-B capture pipeline can run as independent services:

| Service | Context | Default command | Ports |
| --- | --- | --- | --- |
| SDR capture (publisher) | `docker/sdr_cap` | `python -m sdr_cap.adsb_publisher` | 8443 (WebSocket) |
| ADS-B subscriber | `docker/database_api` | `python -m adsb_subscriber --uri … --db …` | n/a |
| WaveTap API | `docker/database_api` | `gunicorn wavetap_api:app` | 5000 (HTTP) |
| Arbiter control plane | `docker/arbiter` | `uvicorn arbiter.service:app` | 8000 (HTTP) |

> The subscriber and API reuse the same base image; the active command is selected via Docker Compose.

### Quick start with Docker Compose

```bash
docker compose up --build
```

Environment variables can be supplied via `.env` or the shell to point the ADS-B publisher at your Dump1090 host:

```
DUMP1090_HOST=192.168.50.106
DUMP1090_RAW_PORT=30002
ADSB_PUBLISH_INTERVAL=2.5
```

Persistent ADS-B data is stored in the named volume `adsb-data` and can be inspected on the host under `/var/lib/docker/volumes/adsb-data/_data/adsb_data.db`.

For manual builds the contexts can be built independently, for example:

```bash
docker build -t wavetap-database-api -f docker/database_api/Dockerfile .
docker run --rm -p 5000:5000 \
  -e ADSB_DB_PATH=/data/adsb_data.db \
  -v $(pwd)/data:/data \
  wavetap-database-api
```

See the "Microservice deployment" section later in this document for a deeper dive into configuration, exposed environment variables, and health-check endpoints.

   ## Project Structure
```
CS7319_SW_Arch/
├── src/              # Main source code for reusable modules
│   ├── sdr_cap/      # SDR IQ capture and streaming modules
│   │   ├── radio.py      # IQ streaming server
│   │   ├── iq_client.py  # IQ streaming client library  
│   │   └── examples.py   # Usage examples and CLI
│   ├── main.py       # Main application entry point
│   └── README.md     # Source code documentation
├── tests/            # Unit and integration tests (pytest)
├── documentation/    # Documentation, diagrams and project instructions
│   ├── diagrams/     # Mermaid source (.mmd)
│   └── diagrams_output/ # Generated PNGs
├── tools/            # Utility scripts and tools
│   └── adsb_rtlsdr_pymodes.py # ADS-B decoding utility
├── dev-env/          # Development environment configuration
│   └── init_env.sh   # Environment setup script
├── Dockerfile        # Container build configuration
├── pyproject.toml    # Project configuration
├── README.md         # Project documentation
└── LICENSE           # Project license (MIT)
```

## Getting Started

- Use the provided setup script (`dev-env/init_env.sh`) to initialize your Python environment and install dependencies.
- All code is primarily written in Python, with open source libraries as needed.

## Installation

To set up the Python virtual environment and install required libraries:

### Linux/WSL
1. Open a terminal and navigate to the project directory.
2. Run:
   ```bash
   bash dev-env/init_env.sh
   ```


### Installed Libraries
The setup script and requirements.txt will install the following Python libraries in the virtual environment:
- `pyrtlsdr` (RTL-SDR library for software defined radio)
- `pyModeS` (ADS-B message decoding)
- `numpy` (numerical computing)
- `matplotlib` (data visualization)
- `flask` (web application framework)
- `fastapi` (web API framework)
- `httpx` (HTTP client for external API communication)
- `pytest` (testing framework)
- `pytest-cov` (test coverage)
- `ruff` (linting and code quality)
- `black` (code formatting)
- `isort` (import sorting)
- `mypy` (static type checking)
- `setuptools` (package development and distribution tools)

## RTL-SDR Setup

This project includes Software Defined Radio (SDR) functionality using RTL-SDR dongles. The setup script automatically installs the required system libraries.

### WSL2 USB Device Setup
If you're using WSL2 on Windows, you'll need to share your RTL-SDR USB device:

1. **Install usbipd-win on Windows** (PowerShell as Administrator):
   ```powershell
   winget install usbipd
   ```

2. **Find your RTL-SDR device**:
   ```powershell
   usbipd list
   ```

3. **Share and attach the device** (replace X-X with your device's bus ID):
   ```powershell
   usbipd bind --busid X-X
   usbipd attach --wsl --busid X-X
   ```

4. **Verify in WSL**:
   ```bash
   lsusb | grep -i rtl
   rtl_test -t
   ```

## Usage

### Running the SDR Application
To run the main SDR application:
```bash
source .venv/bin/activate
python src/main.py
```

## Microservice deployment details

| Component | Purpose | Default command | Key environment variables |
| --- | --- | --- | --- |
| `adsb-publisher` | Streams ADS-B messages from Dump1090 and republishes them over WebSocket. | `python -m sdr_cap.adsb_publisher` | `DUMP1090_HOST`, `DUMP1090_RAW_PORT`, `ADSB_WS_PORT`, `ADSB_PUBLISH_INTERVAL`, `RECEIVER_LAT`, `RECEIVER_LON` |
| `adsb-subscriber` | Consumes the publisher stream and persists telemetry into SQLite. | `python -m adsb_subscriber --uri ws://adsb-publisher:8443 --db /data/adsb_data.db` | `ADSB_WS_URI`, `ADSB_DB_PATH`, `ADSB_SAVE_INTERVAL` |
| `database-api` | Flask UI and REST endpoints for browsing stored aircraft data. | `gunicorn wavetap_api:app` | `ADSB_DB_PATH`, `WAVETAP_API_PORT` (via Compose) |
| `arbiter` | FastAPI control plane for orchestrating SDR modules. | `uvicorn arbiter.service:app` | none (module registration happens over HTTP) |

### Ports and networking

| Service | External port | Protocol |
| --- | --- | --- |
| `adsb-publisher` | 8443 | WebSocket stream of aircraft JSON |
| `database-api` | 5000 | HTTP dashboard and REST APIs |
| `arbiter` | 8000 | HTTP control plane |

The subscriber container shares the `adsb-data` named volume with the API so both have access to the same SQLite database. Adjust Compose bindings or replace the volume with a bind-mount if you need to persist data outside Docker.

### Health checks

- Database API: `GET http://localhost:5000/adsb/api/aircraft?window=300`
- ADS-B publisher: connects clients to `ws://localhost:8443` (receives JSON messages)
- Arbiter: `GET http://localhost:8000/health`

### SDR Module
The RTL-SDR functionality is located in `src/sdr/radio.py`. This module provides basic RTL-SDR configuration and testing capabilities.

### Diagrams
System architecture sources are located in `documentation/diagrams/` and generated images are stored in `documentation/diagrams_output/`.
The repository includes a small helper script to render PNGs from the Mermaid sources:

```bash
bash documentation/generate_diagrams.sh
```

This script uses `mmdc` (mermaid-cli / puppeteer). If you see errors about missing Chrome/Chromium, install a system browser or set `PUPPETEER_EXECUTABLE_PATH` to the browser executable before running the script.

_Additional usage examples and instructions will be added as the project develops._

## Contributing

_Outline guidelines for contributing to this project (coding standards, pull requests, etc.)._

## Testing

All tests should be placed in the `tests/` folder and written using `pytest`.
To run tests:
```bash
pytest
```
_Explain how to run tests and ensure code quality (e.g., using pytest, ruff, mypy)._ 

## References

_List any references, resources, or documentation relevant to the project._

## Linux/WSL Setup Guide

This project is intended to be run exclusively on Linux or Windows Subsystem for Linux (WSL):

### 1. Install WSL (if on Windows)
- Open PowerShell as Administrator and run:
  ```powershell
  wsl --install
  ```
- Restart your computer if prompted.
- Choose and set up your preferred Linux distribution (e.g., Ubuntu) from the Microsoft Store.

### 2. Install the VS Code WSL Extension
- Open VS Code.
- Go to Extensions (`Ctrl+Shift+X`).
- Search for "Remote - WSL" and install the extension by Microsoft.

### 3. Open Your Project in WSL
- Open the Command Palette (`Ctrl+Shift+P`).
- Type and select: `Remote-WSL: Open Folder in WSL`.
- Choose your project folder (`CS7319_SW_Arch`).

### 4. Set Up Your Python Environment in WSL
- Open a terminal in VS Code (it will use WSL).
- Run:
  ```bash
  bash dev-env/init_env.sh
  ```
- This will create the virtual environment and install dependencies in WSL.

### 5. Update VS Code Settings (Optional)
- For Linux/WSL compatibility, set the Python interpreter path in `.vscode/settings.json`:
  ```json
  {
    "python.defaultInterpreterPath": ".venv/bin/python"
  }
  ```

You can now develop and run your project in a Linux environment using WSL, with all VS Code features.

## Docker Containerization

The repository ships first-class Docker support for each microservice—refer to the "Microservice deployment details" section above or the `docker-compose.yml` file for an opinionated development stack. Customize the build contexts under `docker/` if you need to extend the base images (for example to add hardware drivers or corporate certificate bundles).

### Quick Docker Start (single image)

```bash
# Build the WaveTap API image only
docker build -t wavetap-api -f docker/database_api/Dockerfile .

# Run and expose the dashboard on http://localhost:5000
docker run --rm -p 5000:5000 \
   -e ADSB_DB_PATH=/data/adsb_data.db \
   -v $(pwd)/data:/data \
   wavetap-api
```

---

### Disclaimer

AI assistance (GitHub Copilot) was used to help with documentation and environment setup for this project. Project code is to be primarily human-authored. Any use of AI assistants for code generation or other tasks will be clearly disclosed in relevant files or documentation sections.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.

---
