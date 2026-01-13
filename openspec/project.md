# Project Context

## Purpose
MeterEye is a multi-camera meter monitoring system developed by ChingTech that automatically reads seven-segment display values (0-9 digits and decimal points) from industrial pressure gauges and meters. It provides real-time monitoring of multiple RTSP cameras with interactive web-based configuration and REST API integration for industrial production monitoring.

## Tech Stack
- **Language:** Python 3.11+
- **Package Manager:** uv (astral-sh/uv)
- **Computer Vision:** OpenCV 4.8.0+
- **Configuration:** PyYAML 6.0+
- **Web Framework:** FastAPI 0.109.0+ with Starlette
- **ASGI Server:** Uvicorn 0.27.0+
- **Database (optional):** SQLAlchemy 2.0.0+ (SQLite/PostgreSQL)
- **Messaging (optional):** MQTT via paho-mqtt 2.0.0+
- **Frontend:** Vanilla HTML/CSS/JavaScript (no framework)

## Project Conventions

### Code Style
- **Type Hints:** Comprehensive PEP 484 syntax (`|` for unions, `dict[K,V]`)
- **Naming:** snake_case for functions/variables, UPPER_CASE for constants, CamelCase for classes
- **Docstrings:** Google-style with Args/Returns/Raises sections
- **Logging:** Per-module loggers via `logging.getLogger(__name__)`
- **Immutability:** Config models use `@dataclass(frozen=True)` for thread safety

### Architecture Patterns
- **Thread-per-camera:** Each camera runs in its own thread for decoupled processing
- **Callback-based events:** Signal-based propagation for readings and status changes
- **Async dispatch:** ExporterManager uses queue + worker thread pattern for data export
- **Layered design:** Separation of concerns (models, recognition, camera management, API, export)

### Testing Strategy
- Unit tests in `tests/` directory using pytest
- Primary focus on recognition accuracy testing (`test_recognition.py`)
- Run tests with: `uv run pytest tests/`

### Git Workflow
- **Config files:** YAML in `~/.config/ctme/config.yaml` (Linux XDG standard)
- **Secrets:** Environment variables via `.env` (excluded from git)
- **Excluded:** `__pycache__/`, `.venv/`, `config.yaml`, `test_output/`, `*.png`
- **No formal branching strategy documented** - recommend main/feature branches

## Domain Context
- **7-segment displays:** Industrial meters use seven-segment LED/LCD displays showing digits 0-9 and decimal points
- **RTSP streams:** Real-Time Streaming Protocol used by IP cameras for video streaming
- **Perspective transformation:** 4-point calibration to correct camera angle distortion for accurate reading
- **Display modes:** `light_on_dark` (bright digits on dark background) or `dark_on_light` (dark digits on light background)
- **Color channels:** Recognition can use red, green, blue, or grayscale channel

## Important Constraints
- **Real-time processing:** Recognition must keep up with camera frame rate
- **Thread safety:** Config objects are frozen/immutable; runtime state is mutable
- **Resource management:** Each camera thread must handle reconnection gracefully
- **Hot-reload:** Config changes should apply without service restart when possible

## External Dependencies
- **RTSP Cameras:** IP cameras with RTSP stream URLs (authentication via URL credentials)
- **HTTP Endpoints:** Optional external REST APIs for meter reading push
- **MQTT Broker:** Optional message broker for topic-based publishing
- **SQLite/PostgreSQL:** Optional database backends for reading persistence
