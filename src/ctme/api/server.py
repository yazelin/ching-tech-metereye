"""FastAPI server for MeterEye REST API."""

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Generator

import cv2

try:
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

from ctme.camera_manager import CameraManager
from ctme.config_yaml import YAMLConfig
from ctme.models import AppConfig, CameraRuntimeStatus, CameraStatus, IndicatorReading, Reading
from ctme.api.config_routes import create_config_router, create_frame_router

logger = logging.getLogger(__name__)


if FASTAPI_AVAILABLE:

    # Pydantic models for API responses
    class MeterStatusResponse(BaseModel):
        """Meter status response."""

        meter_id: str
        name: str
        last_value: float | None = None
        normalized_value: float | None = None
        last_raw_text: str | None = None
        last_reading_time: str | None = None
        show_on_dashboard: bool = True
        decimal_places: int = 0
        unit: str = ""

    class IndicatorStatusResponse(BaseModel):
        """Indicator status response."""

        indicator_id: str
        name: str
        state: bool | None = None
        brightness: float | None = None
        last_reading_time: str | None = None
        show_on_dashboard: bool = True

    class IndicatorReadingResponse(BaseModel):
        """Indicator reading response."""

        camera_id: str
        indicator_id: str
        state: bool
        brightness: float
        timestamp: str

    class CameraStatusResponse(BaseModel):
        """Camera status response."""

        camera_id: str
        name: str
        status: str
        last_frame_time: str | None = None
        fps: float
        meter_count: int
        indicator_count: int = 0
        error_message: str = ""

    class CameraDetailResponse(CameraStatusResponse):
        """Camera detail response with meters and indicators."""

        meters: list[MeterStatusResponse]
        indicators: list[IndicatorStatusResponse] = []

    class ReadingResponse(BaseModel):
        """Reading response."""

        camera_id: str
        meter_id: str
        value: float | None
        raw_text: str
        timestamp: str
        confidence: float

    class SystemStatusResponse(BaseModel):
        """System status response."""

        status: str
        uptime_seconds: float
        camera_count: int
        connected_cameras: int
        total_readings: int

    class ReloadResponse(BaseModel):
        """Config reload response."""

        success: bool
        message: str
        cameras_updated: list[str] = []


def normalize_value(raw_value: float | None, decimal_places: int) -> float | None:
    """Normalize a value by dividing by 10^decimal_places.

    Args:
        raw_value: The raw reading value
        decimal_places: Number of decimal places (0 = no normalization)

    Returns:
        Normalized value, or None if raw_value is None
    """
    if raw_value is None:
        return None
    if decimal_places <= 0:
        return raw_value
    return raw_value / (10 ** decimal_places)


class APIServer:
    """FastAPI server wrapper for MeterEye."""

    def __init__(
        self,
        camera_manager: CameraManager,
        yaml_config: YAMLConfig,
    ):
        """Initialize API server.

        Args:
            camera_manager: Camera manager instance
            yaml_config: YAML config instance
        """
        self.camera_manager = camera_manager
        self.yaml_config = yaml_config
        self._start_time = datetime.now()
        self._reading_count = 0
        self._indicator_reading_count = 0
        self._latest_readings: dict[str, Reading] = {}  # key: camera_id/meter_id
        self._latest_indicator_readings: dict[str, IndicatorReading] = {}  # key: camera_id/indicator_id

    def record_reading(self, reading: Reading) -> None:
        """Record a meter reading for API access.

        Args:
            reading: Reading to record
        """
        key = f"{reading.camera_id}/{reading.meter_id}"
        self._latest_readings[key] = reading
        self._reading_count += 1

    def record_indicator_reading(self, reading: IndicatorReading) -> None:
        """Record an indicator reading for API access.

        Args:
            reading: Indicator reading to record
        """
        key = f"{reading.camera_id}/{reading.indicator_id}"
        self._latest_indicator_readings[key] = reading
        self._indicator_reading_count += 1

    def get_status(self) -> dict[str, Any]:
        """Get system status."""
        statuses = self.camera_manager.get_all_camera_status()
        connected = sum(1 for s in statuses if s.status == CameraStatus.CONNECTED)

        return {
            "status": "running",
            "uptime_seconds": (datetime.now() - self._start_time).total_seconds(),
            "camera_count": len(statuses),
            "connected_cameras": connected,
            "total_readings": self._reading_count,
        }

    def get_cameras(self) -> list[dict[str, Any]]:
        """Get all camera statuses."""
        statuses = self.camera_manager.get_all_camera_status()
        return [self._format_camera_status(s) for s in statuses]

    def get_camera(self, camera_id: str) -> dict[str, Any] | None:
        """Get single camera status."""
        status = self.camera_manager.get_camera_status(camera_id)
        if status:
            return self._format_camera_detail(status)
        return None

    def get_readings(
        self,
        camera_id: str | None = None,
        meter_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get latest readings."""
        readings = []

        for key, reading in self._latest_readings.items():
            if camera_id and reading.camera_id != camera_id:
                continue
            if meter_id and reading.meter_id != meter_id:
                continue

            readings.append(reading.to_dict())

        return readings

    def reload_config(self) -> tuple[bool, str, list[str]]:
        """Reload configuration and apply to camera workers.

        Returns:
            (success, message, cameras_updated)
        """
        try:
            config = self.yaml_config.reload()
            cameras_updated = []

            # Update each camera's meters
            for camera_config in config.cameras:
                if self.camera_manager.update_camera_meters(
                    camera_config.id,
                    camera_config.meters,
                ):
                    cameras_updated.append(camera_config.id)

            return True, "Configuration reloaded", cameras_updated

        except Exception as e:
            return False, str(e), []

    def _format_camera_status(self, status: CameraRuntimeStatus) -> dict[str, Any]:
        """Format camera status for API response."""
        return {
            "camera_id": status.camera_id,
            "name": status.name,
            "status": status.status.value,
            "last_frame_time": (
                status.last_frame_time.isoformat() if status.last_frame_time else None
            ),
            "fps": round(status.fps, 2),
            "meter_count": len(status.meters),
            "indicator_count": len(status.indicators),
            "error_message": status.error_message,
        }

    def _format_camera_detail(self, status: CameraRuntimeStatus) -> dict[str, Any]:
        """Format camera detail for API response."""
        result = self._format_camera_status(status)

        # Get config data for meter settings
        camera_config = self.yaml_config.get_camera(status.camera_id)
        config_meters = {m.id: m for m in camera_config.meters} if camera_config else {}

        meters = []
        for m in status.meters:
            # Get meter config settings
            meter_config = config_meters.get(m.meter_id)
            show_on_dashboard = meter_config.show_on_dashboard if meter_config else True
            decimal_places = meter_config.decimal_places if meter_config else 0
            unit = meter_config.unit if meter_config else ""

            meter_data = {
                "meter_id": m.meter_id,
                "name": m.name,
                "last_value": None,
                "normalized_value": None,
                "last_raw_text": None,
                "last_reading_time": None,
                "show_on_dashboard": show_on_dashboard,
                "decimal_places": decimal_places,
                "unit": unit,
            }

            if m.last_reading:
                meter_data["last_value"] = m.last_reading.value
                meter_data["normalized_value"] = normalize_value(
                    m.last_reading.value, decimal_places
                )
                meter_data["last_raw_text"] = m.last_reading.raw_text
                meter_data["last_reading_time"] = m.last_reading.timestamp.isoformat()

            meters.append(meter_data)

        result["meters"] = meters

        # Get config data for indicator settings
        config_indicators = {i.id: i for i in camera_config.indicators} if camera_config else {}

        indicators = []
        for ind in status.indicators:
            # Get indicator config settings
            indicator_config = config_indicators.get(ind.indicator_id)
            show_on_dashboard = indicator_config.show_on_dashboard if indicator_config else True

            indicator_data = {
                "indicator_id": ind.indicator_id,
                "name": ind.name,
                "state": None,
                "brightness": None,
                "last_reading_time": None,
                "show_on_dashboard": show_on_dashboard,
            }

            if ind.last_reading:
                indicator_data["state"] = ind.last_reading.state
                indicator_data["brightness"] = ind.last_reading.brightness
                indicator_data["last_reading_time"] = ind.last_reading.timestamp.isoformat()

            indicators.append(indicator_data)

        result["indicators"] = indicators
        return result


def create_app(
    camera_manager: CameraManager,
    yaml_config: YAMLConfig,
) -> Any:
    """Create FastAPI application.

    Args:
        camera_manager: Camera manager instance
        yaml_config: YAML config instance

    Returns:
        FastAPI application
    """
    if not FASTAPI_AVAILABLE:
        raise ImportError("FastAPI not installed. Install with: pip install fastapi")

    app = FastAPI(
        title="MeterEye API",
        description="REST API for MeterEye multi-camera monitoring system",
        version="1.0.0",
    )

    api_server = APIServer(camera_manager, yaml_config)

    # Store reference for reading callback
    app.state.api_server = api_server

    # Include configuration and frame routers
    config_router = create_config_router(camera_manager, yaml_config)
    frame_router = create_frame_router(camera_manager, yaml_config)
    app.include_router(config_router)
    app.include_router(frame_router)

    # Static files and dashboard
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", include_in_schema=False)
    async def dashboard():
        """Serve the dashboard HTML."""
        index_file = static_dir / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return JSONResponse(
            {"message": "Dashboard not available. API is running at /api/"},
            status_code=200,
        )

    @app.get("/config.html", include_in_schema=False)
    async def config_page():
        """Serve the configuration page HTML."""
        config_file = static_dir / "config.html"
        if config_file.exists():
            return FileResponse(str(config_file))
        return JSONResponse(
            {"message": "Configuration page not available."},
            status_code=404,
        )

    @app.get("/api/status", response_model=SystemStatusResponse)
    async def get_status():
        """Get system status."""
        return api_server.get_status()

    @app.get("/api/cameras", response_model=list[CameraStatusResponse])
    async def get_cameras():
        """List all cameras."""
        return api_server.get_cameras()

    @app.get("/api/cameras/{camera_id}", response_model=CameraDetailResponse)
    async def get_camera(camera_id: str):
        """Get single camera status with meters."""
        result = api_server.get_camera(camera_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Camera not found")
        return result

    @app.get("/api/cameras/{camera_id}/meters", response_model=list[MeterStatusResponse])
    async def get_camera_meters(camera_id: str):
        """Get meters for a camera."""
        result = api_server.get_camera(camera_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Camera not found")
        return result.get("meters", [])

    @app.get("/api/cameras/{camera_id}/indicators", response_model=list[IndicatorStatusResponse])
    async def get_camera_indicators(camera_id: str):
        """Get indicators for a camera."""
        result = api_server.get_camera(camera_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Camera not found")
        return result.get("indicators", [])

    @app.get("/api/readings", response_model=list[ReadingResponse])
    async def get_readings(
        camera_id: str | None = Query(None, description="Filter by camera ID"),
        meter_id: str | None = Query(None, description="Filter by meter ID"),
    ):
        """Get latest readings."""
        return api_server.get_readings(camera_id, meter_id)

    @app.get("/api/readings/{camera_id}/{meter_id}", response_model=ReadingResponse)
    async def get_reading(camera_id: str, meter_id: str):
        """Get latest reading for a specific meter."""
        readings = api_server.get_readings(camera_id, meter_id)
        if not readings:
            raise HTTPException(status_code=404, detail="Reading not found")
        return readings[0]

    @app.post("/api/config/reload", response_model=ReloadResponse)
    async def reload_config():
        """Reload configuration from file and apply to camera workers."""
        success, message, cameras_updated = api_server.reload_config()
        return {
            "success": success,
            "message": message,
            "cameras_updated": cameras_updated,
        }

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "ok"}

    @app.get("/stream/{camera_id}")
    async def video_stream(camera_id: str):
        """MJPEG video stream for a camera.

        Returns a continuous MJPEG stream of the camera feed.
        Use in HTML: <img src="/stream/{camera_id}">
        """
        # Check if camera exists
        if api_server.get_camera(camera_id) is None:
            raise HTTPException(status_code=404, detail="Camera not found")

        def generate_frames() -> Generator[bytes, None, None]:
            """Generate MJPEG frames."""
            while True:
                frame = camera_manager.get_latest_frame(camera_id)

                if frame is not None:
                    # Encode frame to JPEG
                    encode_params = [cv2.IMWRITE_JPEG_QUALITY, 70]
                    success, jpeg = cv2.imencode('.jpg', frame, encode_params)

                    if success:
                        yield (
                            b'--frame\r\n'
                            b'Content-Type: image/jpeg\r\n\r\n' +
                            jpeg.tobytes() +
                            b'\r\n'
                        )

                # Limit frame rate to ~15 fps
                time.sleep(0.067)

        return StreamingResponse(
            generate_frames(),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    @app.get("/snapshot/{camera_id}")
    async def camera_snapshot(camera_id: str):
        """Get a single JPEG snapshot from a camera.

        Returns a JPEG image of the current camera frame.
        """
        frame = camera_manager.get_latest_frame(camera_id)

        if frame is None:
            raise HTTPException(
                status_code=503,
                detail="No frame available. Camera may be disconnected.",
            )

        # Encode frame to JPEG
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, 85]
        success, jpeg = cv2.imencode('.jpg', frame, encode_params)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to encode frame")

        return StreamingResponse(
            iter([jpeg.tobytes()]),
            media_type="image/jpeg",
        )

    return app


def run_server(
    camera_manager: CameraManager,
    yaml_config: YAMLConfig,
    host: str = "0.0.0.0",
    port: int = 8000,
) -> None:
    """Run the API server.

    Args:
        camera_manager: Camera manager instance
        yaml_config: YAML config instance
        host: Host to bind to
        port: Port to listen on
    """
    try:
        import uvicorn
    except ImportError:
        logger.error("uvicorn not installed. Install with: pip install uvicorn")
        return

    app = create_app(camera_manager, yaml_config)

    logger.info(f"Starting API server on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
