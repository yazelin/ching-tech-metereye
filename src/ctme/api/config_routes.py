"""Configuration API routes for MeterEye."""

import base64
import logging
from io import BytesIO
from typing import Any

import cv2
import numpy as np

try:
    from fastapi import APIRouter, HTTPException, Query
    from fastapi.responses import StreamingResponse
    from pydantic import BaseModel, Field

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

from ctme.camera_manager import CameraManager
from ctme.config_yaml import ConfigError, YAMLConfig
from ctme.models import PerspectivePoints
from ctme.recognition import SevenSegmentRecognizer

logger = logging.getLogger(__name__)


if FASTAPI_AVAILABLE:
    # Pydantic models for API requests/responses

    class CameraConfigRequest(BaseModel):
        """Request for creating/updating a camera."""

        id: str = Field(..., description="Unique camera ID")
        name: str = Field(..., description="Camera display name")
        url: str = Field(..., description="RTSP URL")
        enabled: bool = Field(True, description="Whether camera is enabled")

    class CameraConfigResponse(BaseModel):
        """Response for camera configuration."""

        id: str
        name: str
        url: str
        enabled: bool
        processing_interval_seconds: float = 1.0
        meter_count: int = 0

    class CameraUpdateRequest(BaseModel):
        """Request for updating a camera (partial update)."""

        name: str | None = None
        url: str | None = None
        enabled: bool | None = None
        processing_interval_seconds: float | None = None

    class MeterPerspectiveRequest(BaseModel):
        """Perspective configuration in request."""

        points: list[list[int]] = Field(..., description="4 points [[x,y], ...]")
        output_size: list[int] = Field([400, 100], description="[width, height]")

    class MeterRecognitionRequest(BaseModel):
        """Recognition parameters in request."""

        display_mode: str = Field("light_on_dark", description="light_on_dark or dark_on_light")
        color_channel: str = Field("red", description="red, green, blue, or gray")
        threshold: int = Field(0, description="0=auto (Otsu), 1-255=manual")

    class MeterConfigRequest(BaseModel):
        """Request for creating a meter."""

        id: str = Field(..., description="Unique meter ID within camera")
        name: str = Field(..., description="Meter display name")
        perspective: MeterPerspectiveRequest
        recognition: MeterRecognitionRequest = Field(default_factory=MeterRecognitionRequest)
        show_on_dashboard: bool = Field(True, description="Whether to show readings on dashboard")
        decimal_places: int = Field(0, description="Decimal places for normalization (0=none)")
        unit: str = Field("", description="Unit string (e.g., kPa, bar, °C)")
        expected_digits: int = Field(0, description="Expected digit count (0=no validation)")

    class MeterConfigResponse(BaseModel):
        """Response for meter configuration."""

        id: str
        name: str
        perspective: dict
        recognition: dict
        show_on_dashboard: bool = True
        decimal_places: int = 0
        unit: str = ""
        expected_digits: int = 0

    class MeterUpdateRequest(BaseModel):
        """Request for updating a meter (partial update)."""

        name: str | None = None
        perspective: MeterPerspectiveRequest | None = None
        recognition: MeterRecognitionRequest | None = None
        show_on_dashboard: bool | None = None
        decimal_places: int | None = None
        unit: str | None = None
        expected_digits: int | None = None

    class PerspectivePreviewRequest(BaseModel):
        """Request for perspective preview."""

        camera_id: str
        points: list[list[int]] = Field(..., description="4 points [[x,y], ...]")
        output_size: list[int] = Field([400, 100], description="[width, height]")
        display_mode: str = Field("light_on_dark")
        color_channel: str = Field("red")
        threshold: int = Field(0)
        expected_digits: int = Field(0, description="Expected digit count (0=auto-detect)")

    class PerspectivePreviewResponse(BaseModel):
        """Response for perspective preview."""

        transformed_image: str = Field(..., description="Base64 encoded JPEG")
        debug_image: str = Field(..., description="Base64 encoded debug visualization")
        recognized_text: str | None = Field(None, description="Recognized text if successful")
        recognized_value: float | None = Field(None, description="Parsed numeric value")

    class ConfigSaveResponse(BaseModel):
        """Response for config save operation."""

        success: bool
        message: str
        camera_count: int = 0

    class ConfigResponse(BaseModel):
        """Full configuration response."""

        cameras: list[CameraConfigResponse]


def create_config_router(
    camera_manager: CameraManager,
    yaml_config: YAMLConfig,
) -> Any:
    """Create configuration API router.

    Args:
        camera_manager: Camera manager instance
        yaml_config: YAML config instance

    Returns:
        FastAPI APIRouter
    """
    if not FASTAPI_AVAILABLE:
        raise ImportError("FastAPI not installed")

    router = APIRouter(prefix="/api/config", tags=["Configuration"])

    def _camera_to_response(cam) -> dict:
        """Convert CameraConfigData to response dict."""
        return {
            "id": cam.id,
            "name": cam.name,
            "url": cam.url,
            "enabled": cam.enabled,
            "processing_interval_seconds": cam.processing_interval_seconds,
            "meter_count": len(cam.meters),
        }

    def _meter_to_response(meter) -> dict:
        """Convert MeterConfigData to response dict."""
        return {
            "id": meter.id,
            "name": meter.name,
            "perspective": {
                "points": [list(p) for p in meter.perspective.points],
                "output_size": [meter.perspective.output_width, meter.perspective.output_height],
            },
            "recognition": {
                "display_mode": meter.display_mode,
                "color_channel": meter.color_channel,
                "threshold": meter.threshold,
            },
            "show_on_dashboard": meter.show_on_dashboard,
            "decimal_places": meter.decimal_places,
            "unit": meter.unit,
            "expected_digits": meter.expected_digits,
        }

    # Camera CRUD endpoints

    @router.get("/cameras", response_model=list[CameraConfigResponse])
    async def list_cameras():
        """List all camera configurations."""
        return [_camera_to_response(cam) for cam in yaml_config.config.cameras]

    @router.get("/cameras/{camera_id}", response_model=CameraConfigResponse)
    async def get_camera(camera_id: str):
        """Get a single camera configuration."""
        cam = yaml_config.get_camera(camera_id)
        if not cam:
            raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
        return _camera_to_response(cam)

    @router.post("/cameras", response_model=CameraConfigResponse, status_code=201)
    async def create_camera(request: CameraConfigRequest):
        """Create a new camera."""
        try:
            cam = yaml_config.add_camera(
                camera_id=request.id,
                name=request.name,
                url=request.url,
                enabled=request.enabled,
            )
            return _camera_to_response(cam)
        except ConfigError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.put("/cameras/{camera_id}", response_model=CameraConfigResponse)
    async def update_camera(camera_id: str, request: CameraUpdateRequest):
        """Update an existing camera."""
        try:
            cam = yaml_config.update_camera(
                camera_id=camera_id,
                name=request.name,
                url=request.url,
                enabled=request.enabled,
                processing_interval_seconds=request.processing_interval_seconds,
            )
            # Hot-reload processing interval to running worker
            if request.processing_interval_seconds is not None:
                camera_manager.update_camera_processing_interval(
                    camera_id, request.processing_interval_seconds
                )
            return _camera_to_response(cam)
        except ConfigError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @router.delete("/cameras/{camera_id}", status_code=204)
    async def delete_camera(camera_id: str):
        """Delete a camera."""
        try:
            yaml_config.remove_camera(camera_id)
        except ConfigError as e:
            raise HTTPException(status_code=404, detail=str(e))

    # Meter CRUD endpoints

    @router.get("/cameras/{camera_id}/meters", response_model=list[MeterConfigResponse])
    async def list_meters(camera_id: str):
        """List all meters for a camera."""
        cam = yaml_config.get_camera(camera_id)
        if not cam:
            raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
        return [_meter_to_response(m) for m in cam.meters]

    @router.get("/cameras/{camera_id}/meters/{meter_id}", response_model=MeterConfigResponse)
    async def get_meter(camera_id: str, meter_id: str):
        """Get a single meter configuration."""
        meter = yaml_config.get_meter(camera_id, meter_id)
        if not meter:
            raise HTTPException(
                status_code=404,
                detail=f"Meter '{meter_id}' not found in camera '{camera_id}'",
            )
        return _meter_to_response(meter)

    @router.post("/cameras/{camera_id}/meters", response_model=MeterConfigResponse, status_code=201)
    async def create_meter(camera_id: str, request: MeterConfigRequest):
        """Create a new meter for a camera."""
        try:
            meter = yaml_config.add_meter(
                camera_id=camera_id,
                meter_id=request.id,
                name=request.name,
                points=request.perspective.points,
                output_size=request.perspective.output_size,
                display_mode=request.recognition.display_mode,
                color_channel=request.recognition.color_channel,
                threshold=request.recognition.threshold,
                show_on_dashboard=request.show_on_dashboard,
                decimal_places=request.decimal_places,
                unit=request.unit,
                expected_digits=request.expected_digits,
            )
            return _meter_to_response(meter)
        except ConfigError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.put("/cameras/{camera_id}/meters/{meter_id}", response_model=MeterConfigResponse)
    async def update_meter(camera_id: str, meter_id: str, request: MeterUpdateRequest):
        """Update an existing meter."""
        try:
            points = None
            output_size = None
            display_mode = None
            color_channel = None
            threshold = None

            if request.perspective:
                points = request.perspective.points
                output_size = request.perspective.output_size

            if request.recognition:
                display_mode = request.recognition.display_mode
                color_channel = request.recognition.color_channel
                threshold = request.recognition.threshold

            meter = yaml_config.update_meter(
                camera_id=camera_id,
                meter_id=meter_id,
                name=request.name,
                points=points,
                output_size=output_size,
                display_mode=display_mode,
                color_channel=color_channel,
                threshold=threshold,
                show_on_dashboard=request.show_on_dashboard,
                decimal_places=request.decimal_places,
                unit=request.unit,
                expected_digits=request.expected_digits,
            )
            return _meter_to_response(meter)
        except ConfigError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @router.delete("/cameras/{camera_id}/meters/{meter_id}", status_code=204)
    async def delete_meter(camera_id: str, meter_id: str):
        """Delete a meter from a camera."""
        try:
            yaml_config.remove_meter(camera_id, meter_id)
        except ConfigError as e:
            raise HTTPException(status_code=404, detail=str(e))

    # Config save/apply endpoints

    @router.post("/save", response_model=ConfigSaveResponse)
    async def save_config():
        """Save current configuration to file."""
        try:
            yaml_config.save()
            return {
                "success": True,
                "message": f"Configuration saved to {yaml_config.config_path}",
                "camera_count": len(yaml_config.config.cameras),
            }
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            return {
                "success": False,
                "message": str(e),
                "camera_count": 0,
            }

    @router.post("/apply", response_model=ConfigSaveResponse)
    async def apply_config():
        """Apply current configuration (reload camera workers)."""
        try:
            # Get current in-memory config
            config = yaml_config.config

            # TODO: Implement camera manager reload with new config
            # For now, this is a placeholder

            return {
                "success": True,
                "message": "Configuration applied (camera reload not yet implemented)",
                "camera_count": len(config.cameras),
            }
        except Exception as e:
            logger.error(f"Failed to apply config: {e}")
            return {
                "success": False,
                "message": str(e),
                "camera_count": 0,
            }

    return router


def create_frame_router(
    camera_manager: CameraManager,
    yaml_config: YAMLConfig,
) -> Any:
    """Create frame capture and preview API router.

    Args:
        camera_manager: Camera manager instance
        yaml_config: YAML config instance

    Returns:
        FastAPI APIRouter
    """
    if not FASTAPI_AVAILABLE:
        raise ImportError("FastAPI not installed")

    router = APIRouter(prefix="/api", tags=["Frame"])

    @router.get("/frame/{camera_id}")
    async def get_frame(
        camera_id: str,
        width: int | None = Query(None, description="Scale to this width"),
    ):
        """Get a single JPEG frame from a camera.

        This is similar to /snapshot but optimized for configuration UI
        with optional width scaling.
        """
        frame = camera_manager.get_latest_frame(camera_id)

        if frame is None:
            raise HTTPException(
                status_code=503,
                detail="No frame available. Camera may be disconnected.",
            )

        # Scale if width specified
        if width and width > 0:
            h, w = frame.shape[:2]
            scale = width / w
            new_h = int(h * scale)
            frame = cv2.resize(frame, (width, new_h), interpolation=cv2.INTER_AREA)

        # Encode to JPEG
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, 85]
        success, jpeg = cv2.imencode(".jpg", frame, encode_params)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to encode frame")

        return StreamingResponse(
            iter([jpeg.tobytes()]),
            media_type="image/jpeg",
        )

    @router.post("/preview/perspective", response_model=PerspectivePreviewResponse)
    async def preview_perspective(request: PerspectivePreviewRequest):
        """Preview perspective transform and recognition result.

        Returns the transformed image, debug visualization, and recognition result.
        """
        # Get frame from camera
        frame = camera_manager.get_latest_frame(request.camera_id)

        if frame is None:
            raise HTTPException(
                status_code=503,
                detail="No frame available. Camera may be disconnected.",
            )

        # Validate points
        if len(request.points) != 4:
            raise HTTPException(status_code=400, detail="Exactly 4 points required")

        # Apply perspective transform
        src_pts = np.array(request.points, dtype=np.float32)
        output_w, output_h = request.output_size

        dst_pts = np.array([
            [0, 0],
            [output_w - 1, 0],
            [output_w - 1, output_h - 1],
            [0, output_h - 1],
        ], dtype=np.float32)

        matrix = cv2.getPerspectiveTransform(src_pts, dst_pts)
        transformed = cv2.warpPerspective(frame, matrix, (output_w, output_h))

        # Run recognition
        recognizer = SevenSegmentRecognizer(
            display_mode=request.display_mode,
            color_channel=request.color_channel,
            threshold=request.threshold,
            expected_digits=request.expected_digits,
        )

        recognized_text, debug_image = recognizer.recognize(transformed)

        # Parse numeric value
        recognized_value = None
        if recognized_text:
            try:
                recognized_value = float(recognized_text)
            except ValueError:
                pass

        # Encode images to base64
        _, transformed_jpeg = cv2.imencode(".jpg", transformed, [cv2.IMWRITE_JPEG_QUALITY, 90])
        _, debug_jpeg = cv2.imencode(".jpg", debug_image, [cv2.IMWRITE_JPEG_QUALITY, 90])

        transformed_b64 = base64.b64encode(transformed_jpeg.tobytes()).decode("utf-8")
        debug_b64 = base64.b64encode(debug_jpeg.tobytes()).decode("utf-8")

        return {
            "transformed_image": transformed_b64,
            "debug_image": debug_b64,
            "recognized_text": recognized_text,
            "recognized_value": recognized_value,
        }

    return router
