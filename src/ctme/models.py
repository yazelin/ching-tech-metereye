"""Data models for MeterEye multi-camera system."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal


class CameraStatus(Enum):
    """Camera connection status."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"


class DisplayMode(Enum):
    """Display mode for 7-segment recognition."""

    LIGHT_ON_DARK = "light_on_dark"
    DARK_ON_LIGHT = "dark_on_light"


class ColorChannel(Enum):
    """Color channel for image processing."""

    RED = "red"
    GREEN = "green"
    BLUE = "blue"
    GRAY = "gray"


@dataclass(frozen=True)
class PerspectivePoints:
    """4-point perspective configuration (immutable)."""

    points: tuple[tuple[int, int], ...]  # TL, TR, BR, BL
    output_width: int = 400
    output_height: int = 100

    def is_valid(self) -> bool:
        """Check if config has valid 4 points."""
        return len(self.points) == 4


@dataclass(frozen=True)
class MeterConfigData:
    """Configuration for a single meter (immutable)."""

    id: str
    name: str
    perspective: PerspectivePoints
    display_mode: str = "light_on_dark"
    color_channel: str = "red"
    threshold: int = 0  # 0 = auto (Otsu)
    show_on_dashboard: bool = True  # Whether to show readings on dashboard
    decimal_places: int = 0  # Number of decimal places for normalization (0 = no normalization)
    unit: str = ""  # Unit string (e.g., "kPa", "bar", "°C")
    expected_digits: int = 0  # Expected digit count (0 = no validation)


@dataclass(frozen=True)
class CameraConfigData:
    """Configuration for a single camera (immutable)."""

    id: str
    name: str
    url: str
    enabled: bool = True
    meters: tuple[MeterConfigData, ...] = field(default_factory=tuple)
    processing_interval_seconds: float = 1.0  # How often to process frames for recognition


@dataclass(frozen=True)
class HTTPExportConfig:
    """HTTP export configuration."""

    enabled: bool = False
    url: str = ""
    interval_seconds: float = 5.0
    batch_size: int = 10
    headers: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 10.0


@dataclass(frozen=True)
class DatabaseExportConfig:
    """Database export configuration."""

    enabled: bool = False
    type: Literal["sqlite", "postgresql"] = "sqlite"
    path: str = "./readings.db"
    connection_string: str = ""
    retention_days: int = 30


@dataclass(frozen=True)
class MQTTExportConfig:
    """MQTT export configuration."""

    enabled: bool = False
    broker: str = "localhost"
    port: int = 1883
    topic: str = "ctme/readings"
    qos: int = 1
    username: str = ""
    password: str = ""


@dataclass(frozen=True)
class ExportConfig:
    """Combined export configuration."""

    http: HTTPExportConfig = field(default_factory=HTTPExportConfig)
    database: DatabaseExportConfig = field(default_factory=DatabaseExportConfig)
    mqtt: MQTTExportConfig = field(default_factory=MQTTExportConfig)


@dataclass(frozen=True)
class ServerConfig:
    """API server configuration."""

    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8000


@dataclass(frozen=True)
class AppConfig:
    """Top-level application configuration (immutable)."""

    cameras: tuple[CameraConfigData, ...] = field(default_factory=tuple)
    export: ExportConfig = field(default_factory=ExportConfig)
    server: ServerConfig = field(default_factory=ServerConfig)


# Runtime data models (mutable)


@dataclass
class Reading:
    """A single meter reading."""

    camera_id: str
    meter_id: str
    value: float | None
    raw_text: str
    timestamp: datetime
    confidence: float = 1.0  # 0.0 - 1.0

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "camera_id": self.camera_id,
            "meter_id": self.meter_id,
            "value": self.value,
            "raw_text": self.raw_text,
            "timestamp": self.timestamp.isoformat(),
            "confidence": self.confidence,
        }


@dataclass
class MeterStatus:
    """Runtime status of a meter."""

    meter_id: str
    name: str
    last_reading: Reading | None = None


@dataclass
class CameraRuntimeStatus:
    """Runtime status of a camera."""

    camera_id: str
    name: str
    status: CameraStatus = CameraStatus.DISCONNECTED
    last_frame_time: datetime | None = None
    fps: float = 0.0
    meters: list[MeterStatus] = field(default_factory=list)
    error_message: str = ""
