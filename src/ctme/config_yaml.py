"""YAML configuration management with environment variable support."""

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

from ctme.models import (
    AppConfig,
    CameraConfigData,
    DatabaseExportConfig,
    ExportConfig,
    HTTPExportConfig,
    IndicatorConfigData,
    MeterConfigData,
    MQTTExportConfig,
    PerspectivePoints,
    ServerConfig,
)


class ConfigError(Exception):
    """Configuration error."""

    pass


def _substitute_env_vars(value: str) -> str:
    """Substitute environment variables in a string.

    Supports:
    - ${VAR_NAME} - required variable
    - ${VAR_NAME:-default} - variable with default value
    """
    pattern = r"\$\{([^}:]+)(?::-([^}]*))?\}"

    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        default = match.group(2)
        env_value = os.environ.get(var_name)

        if env_value is not None:
            return env_value
        if default is not None:
            return default
        raise ConfigError(f"Environment variable '{var_name}' is not set and no default provided")

    return re.sub(pattern, replacer, value)


def _process_env_vars(data: Any) -> Any:
    """Recursively process environment variables in configuration data."""
    if isinstance(data, str):
        return _substitute_env_vars(data)
    elif isinstance(data, dict):
        return {k: _process_env_vars(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_process_env_vars(item) for item in data]
    return data


def _parse_perspective(data: dict) -> PerspectivePoints:
    """Parse perspective configuration from dict."""
    points_data = data.get("points", [])
    if not points_data or len(points_data) != 4:
        raise ConfigError("Perspective must have exactly 4 points")

    points = tuple(tuple(p) for p in points_data)
    output_size = data.get("output_size", [400, 100])

    return PerspectivePoints(
        points=points,
        output_width=output_size[0] if isinstance(output_size, list) else 400,
        output_height=output_size[1] if isinstance(output_size, list) else 100,
    )


def _parse_meter(data: dict) -> MeterConfigData:
    """Parse meter configuration from dict."""
    if "id" not in data:
        raise ConfigError("Meter configuration must have 'id' field")
    if "perspective" not in data:
        raise ConfigError(f"Meter '{data['id']}' must have 'perspective' field")

    recognition = data.get("recognition", {})

    return MeterConfigData(
        id=data["id"],
        name=data.get("name", data["id"]),
        perspective=_parse_perspective(data["perspective"]),
        display_mode=recognition.get("display_mode", "light_on_dark"),
        color_channel=recognition.get("color_channel", "red"),
        threshold=recognition.get("threshold", 0),
        show_on_dashboard=data.get("show_on_dashboard", True),
        decimal_places=data.get("decimal_places", 0),
        unit=data.get("unit", ""),
        expected_digits=data.get("expected_digits", 0),
    )


def _parse_indicator(data: dict) -> IndicatorConfigData:
    """Parse indicator configuration from dict."""
    if "id" not in data:
        raise ConfigError("Indicator configuration must have 'id' field")
    if "perspective" not in data:
        raise ConfigError(f"Indicator '{data['id']}' must have 'perspective' field")

    detection = data.get("detection", {})

    return IndicatorConfigData(
        id=data["id"],
        name=data.get("name", data["id"]),
        perspective=_parse_perspective(data["perspective"]),
        detection_mode=detection.get("mode", "brightness"),
        threshold=detection.get("threshold", 128),
        on_color=detection.get("on_color", "red"),
        show_on_dashboard=data.get("show_on_dashboard", True),
    )


def _parse_camera(data: dict) -> CameraConfigData:
    """Parse camera configuration from dict."""
    if "id" not in data:
        raise ConfigError("Camera configuration must have 'id' field")
    if "url" not in data:
        raise ConfigError(f"Camera '{data['id']}' must have 'url' field")

    meters_data = data.get("meters", [])
    meters = tuple(_parse_meter(m) for m in meters_data)

    indicators_data = data.get("indicators", [])
    indicators = tuple(_parse_indicator(i) for i in indicators_data)

    return CameraConfigData(
        id=data["id"],
        name=data.get("name", data["id"]),
        url=data["url"],
        enabled=data.get("enabled", True),
        meters=meters,
        indicators=indicators,
        processing_interval_seconds=data.get("processing_interval_seconds", 1.0),
    )


def _parse_http_export(data: dict) -> HTTPExportConfig:
    """Parse HTTP export configuration."""
    return HTTPExportConfig(
        enabled=data.get("enabled", False),
        url=data.get("url", ""),
        interval_seconds=data.get("interval_seconds", 5.0),
        batch_size=data.get("batch_size", 10),
        headers=data.get("headers", {}),
        timeout_seconds=data.get("timeout_seconds", 10.0),
    )


def _parse_database_export(data: dict) -> DatabaseExportConfig:
    """Parse database export configuration."""
    return DatabaseExportConfig(
        enabled=data.get("enabled", False),
        type=data.get("type", "sqlite"),
        path=data.get("path", "./readings.db"),
        connection_string=data.get("connection_string", ""),
        retention_days=data.get("retention_days", 30),
    )


def _parse_mqtt_export(data: dict) -> MQTTExportConfig:
    """Parse MQTT export configuration."""
    return MQTTExportConfig(
        enabled=data.get("enabled", False),
        broker=data.get("broker", "localhost"),
        port=data.get("port", 1883),
        topic=data.get("topic", "ctme/readings"),
        qos=data.get("qos", 1),
        username=data.get("username", ""),
        password=data.get("password", ""),
    )


def _parse_export(data: dict) -> ExportConfig:
    """Parse export configuration."""
    return ExportConfig(
        http=_parse_http_export(data.get("http", {})),
        database=_parse_database_export(data.get("database", {})),
        mqtt=_parse_mqtt_export(data.get("mqtt", {})),
    )


def _parse_server(data: dict) -> ServerConfig:
    """Parse server configuration."""
    return ServerConfig(
        enabled=data.get("enabled", True),
        host=data.get("host", "0.0.0.0"),
        port=data.get("port", 8000),
    )


class YAMLConfig:
    """YAML configuration manager with environment variable support."""

    DEFAULT_CONFIG_DIR = Path.home() / ".config" / "ctme"
    DEFAULT_CONFIG_FILE = "config.yaml"
    LEGACY_CONFIG_FILE = "config.json"

    def __init__(self, config_path: Path | None = None):
        """Initialize configuration manager.

        Args:
            config_path: Optional custom config file path
        """
        if config_path:
            self.config_path = Path(config_path)
        else:
            self.config_path = self.DEFAULT_CONFIG_DIR / self.DEFAULT_CONFIG_FILE

        self.legacy_config_path = self.DEFAULT_CONFIG_DIR / self.LEGACY_CONFIG_FILE
        self._config: AppConfig | None = None

    @property
    def config(self) -> AppConfig:
        """Get current configuration, loading if necessary."""
        if self._config is None:
            self._config = self.load()
        return self._config

    def load(self) -> AppConfig:
        """Load configuration from YAML file.

        Returns:
            Parsed AppConfig

        Raises:
            ConfigError: If configuration is invalid
        """
        if not self.config_path.exists():
            # Check for legacy JSON config
            if self.legacy_config_path.exists():
                print(f"Found legacy config at {self.legacy_config_path}")
                print("Run 'ctme migrate' to convert to YAML format")
            return AppConfig()

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                raw_data = yaml.safe_load(f)

            if raw_data is None:
                return AppConfig()

            # Process environment variables
            data = _process_env_vars(raw_data)

            # Parse configuration
            cameras_data = data.get("cameras", [])
            cameras = tuple(_parse_camera(c) for c in cameras_data)

            # Check for duplicate camera IDs
            camera_ids = [c.id for c in cameras]
            if len(camera_ids) != len(set(camera_ids)):
                duplicates = [id for id in camera_ids if camera_ids.count(id) > 1]
                raise ConfigError(f"Duplicate camera IDs found: {set(duplicates)}")

            export = _parse_export(data.get("export", {}))
            server = _parse_server(data.get("server", {}))

            self._config = AppConfig(
                cameras=cameras,
                export=export,
                server=server,
            )
            return self._config

        except yaml.YAMLError as e:
            raise ConfigError(f"Invalid YAML syntax: {e}")

    def save(self, config: AppConfig | None = None) -> None:
        """Save configuration to YAML file.

        Args:
            config: Configuration to save (uses current if not provided)
        """
        if config is None:
            config = self._config or AppConfig()

        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        data = self._config_to_dict(config)

        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        self._config = config

    def _config_to_dict(self, config: AppConfig) -> dict:
        """Convert AppConfig to dictionary for YAML serialization."""
        cameras = []
        for cam in config.cameras:
            meters = []
            for m in cam.meters:
                meters.append({
                    "id": m.id,
                    "name": m.name,
                    "perspective": {
                        "points": [list(p) for p in m.perspective.points],
                        "output_size": [m.perspective.output_width, m.perspective.output_height],
                    },
                    "recognition": {
                        "display_mode": m.display_mode,
                        "color_channel": m.color_channel,
                        "threshold": m.threshold,
                    },
                    "show_on_dashboard": m.show_on_dashboard,
                    "decimal_places": m.decimal_places,
                    "unit": m.unit,
                    "expected_digits": m.expected_digits,
                })
            indicators = []
            for ind in cam.indicators:
                indicators.append({
                    "id": ind.id,
                    "name": ind.name,
                    "perspective": {
                        "points": [list(p) for p in ind.perspective.points],
                        "output_size": [ind.perspective.output_width, ind.perspective.output_height],
                    },
                    "detection": {
                        "mode": ind.detection_mode,
                        "threshold": ind.threshold,
                        "on_color": ind.on_color,
                    },
                    "show_on_dashboard": ind.show_on_dashboard,
                })
            cameras.append({
                "id": cam.id,
                "name": cam.name,
                "url": cam.url,
                "enabled": cam.enabled,
                "processing_interval_seconds": cam.processing_interval_seconds,
                "meters": meters,
                "indicators": indicators,
            })

        return {
            "cameras": cameras,
            "export": {
                "http": {
                    "enabled": config.export.http.enabled,
                    "url": config.export.http.url,
                    "interval_seconds": config.export.http.interval_seconds,
                    "batch_size": config.export.http.batch_size,
                    "headers": dict(config.export.http.headers),
                    "timeout_seconds": config.export.http.timeout_seconds,
                },
                "database": {
                    "enabled": config.export.database.enabled,
                    "type": config.export.database.type,
                    "path": config.export.database.path,
                    "connection_string": config.export.database.connection_string,
                    "retention_days": config.export.database.retention_days,
                },
                "mqtt": {
                    "enabled": config.export.mqtt.enabled,
                    "broker": config.export.mqtt.broker,
                    "port": config.export.mqtt.port,
                    "topic": config.export.mqtt.topic,
                    "qos": config.export.mqtt.qos,
                    "username": config.export.mqtt.username,
                    "password": config.export.mqtt.password,
                },
            },
            "server": {
                "enabled": config.server.enabled,
                "host": config.server.host,
                "port": config.server.port,
            },
        }

    def reload(self) -> AppConfig:
        """Reload configuration from file.

        Returns:
            Newly loaded AppConfig
        """
        self._config = None
        return self.load()

    # CRUD methods for cameras
    def get_camera(self, camera_id: str) -> CameraConfigData | None:
        """Get a camera by ID.

        Args:
            camera_id: Camera ID to find

        Returns:
            CameraConfigData or None if not found
        """
        for cam in self.config.cameras:
            if cam.id == camera_id:
                return cam
        return None

    def add_camera(
        self,
        camera_id: str,
        name: str,
        url: str,
        enabled: bool = True,
    ) -> CameraConfigData:
        """Add a new camera.

        Args:
            camera_id: Unique camera ID
            name: Camera display name
            url: RTSP URL
            enabled: Whether camera is enabled

        Returns:
            The new CameraConfigData

        Raises:
            ConfigError: If camera ID already exists
        """
        if self.get_camera(camera_id):
            raise ConfigError(f"Camera '{camera_id}' already exists")

        new_camera = CameraConfigData(
            id=camera_id,
            name=name,
            url=url,
            enabled=enabled,
            meters=(),
            indicators=(),
        )

        self._config = AppConfig(
            cameras=self.config.cameras + (new_camera,),
            export=self.config.export,
            server=self.config.server,
        )

        return new_camera

    def update_camera(
        self,
        camera_id: str,
        name: str | None = None,
        url: str | None = None,
        enabled: bool | None = None,
        processing_interval_seconds: float | None = None,
    ) -> CameraConfigData:
        """Update an existing camera.

        Args:
            camera_id: Camera ID to update
            name: New name (None = keep existing)
            url: New URL (None = keep existing)
            enabled: New enabled state (None = keep existing)
            processing_interval_seconds: New processing interval (None = keep existing)

        Returns:
            The updated CameraConfigData

        Raises:
            ConfigError: If camera not found
        """
        existing = self.get_camera(camera_id)
        if not existing:
            raise ConfigError(f"Camera '{camera_id}' not found")

        updated = CameraConfigData(
            id=existing.id,
            name=name if name is not None else existing.name,
            url=url if url is not None else existing.url,
            enabled=enabled if enabled is not None else existing.enabled,
            meters=existing.meters,
            indicators=existing.indicators,
            processing_interval_seconds=(
                processing_interval_seconds if processing_interval_seconds is not None
                else existing.processing_interval_seconds
            ),
        )

        new_cameras = tuple(
            updated if c.id == camera_id else c
            for c in self.config.cameras
        )

        self._config = AppConfig(
            cameras=new_cameras,
            export=self.config.export,
            server=self.config.server,
        )

        return updated

    def remove_camera(self, camera_id: str) -> None:
        """Remove a camera.

        Args:
            camera_id: Camera ID to remove

        Raises:
            ConfigError: If camera not found
        """
        if not self.get_camera(camera_id):
            raise ConfigError(f"Camera '{camera_id}' not found")

        new_cameras = tuple(c for c in self.config.cameras if c.id != camera_id)

        self._config = AppConfig(
            cameras=new_cameras,
            export=self.config.export,
            server=self.config.server,
        )

    # CRUD methods for meters
    def get_meter(self, camera_id: str, meter_id: str) -> MeterConfigData | None:
        """Get a meter by camera and meter ID.

        Args:
            camera_id: Camera ID
            meter_id: Meter ID

        Returns:
            MeterConfigData or None if not found
        """
        camera = self.get_camera(camera_id)
        if not camera:
            return None

        for meter in camera.meters:
            if meter.id == meter_id:
                return meter
        return None

    def add_meter(
        self,
        camera_id: str,
        meter_id: str,
        name: str,
        points: list[list[int]],
        output_size: list[int] | None = None,
        display_mode: str = "light_on_dark",
        color_channel: str = "red",
        threshold: int = 0,
        show_on_dashboard: bool = True,
        decimal_places: int = 0,
        unit: str = "",
        expected_digits: int = 0,
    ) -> MeterConfigData:
        """Add a new meter to a camera.

        Args:
            camera_id: Camera ID to add meter to
            meter_id: Unique meter ID within camera
            name: Meter display name
            points: 4 perspective points [[x,y], ...]
            output_size: [width, height] or None for default
            display_mode: Recognition display mode
            color_channel: Color channel for processing
            threshold: Threshold value (0=auto)
            show_on_dashboard: Whether to show readings on dashboard
            decimal_places: Number of decimal places for normalization
            unit: Unit string (e.g., "kPa")
            expected_digits: Expected digit count (0 = no validation)

        Returns:
            The new MeterConfigData

        Raises:
            ConfigError: If camera not found or meter ID exists
        """
        camera = self.get_camera(camera_id)
        if not camera:
            raise ConfigError(f"Camera '{camera_id}' not found")

        if self.get_meter(camera_id, meter_id):
            raise ConfigError(f"Meter '{meter_id}' already exists in camera '{camera_id}'")

        if len(points) != 4:
            raise ConfigError("Meter must have exactly 4 perspective points")

        output_size = output_size or [400, 100]

        perspective = PerspectivePoints(
            points=tuple(tuple(p) for p in points),
            output_width=output_size[0],
            output_height=output_size[1],
        )

        new_meter = MeterConfigData(
            id=meter_id,
            name=name,
            perspective=perspective,
            display_mode=display_mode,
            color_channel=color_channel,
            threshold=threshold,
            show_on_dashboard=show_on_dashboard,
            decimal_places=decimal_places,
            unit=unit,
            expected_digits=expected_digits,
        )

        updated_camera = CameraConfigData(
            id=camera.id,
            name=camera.name,
            url=camera.url,
            enabled=camera.enabled,
            meters=camera.meters + (new_meter,),
            indicators=camera.indicators,
        )

        new_cameras = tuple(
            updated_camera if c.id == camera_id else c
            for c in self.config.cameras
        )

        self._config = AppConfig(
            cameras=new_cameras,
            export=self.config.export,
            server=self.config.server,
        )

        return new_meter

    def update_meter(
        self,
        camera_id: str,
        meter_id: str,
        name: str | None = None,
        points: list[list[int]] | None = None,
        output_size: list[int] | None = None,
        display_mode: str | None = None,
        color_channel: str | None = None,
        threshold: int | None = None,
        show_on_dashboard: bool | None = None,
        decimal_places: int | None = None,
        unit: str | None = None,
        expected_digits: int | None = None,
    ) -> MeterConfigData:
        """Update an existing meter.

        Args:
            camera_id: Camera ID
            meter_id: Meter ID to update
            name: New name (None = keep)
            points: New perspective points (None = keep)
            output_size: New output size (None = keep)
            display_mode: New display mode (None = keep)
            color_channel: New color channel (None = keep)
            threshold: New threshold (None = keep)
            show_on_dashboard: Whether to show on dashboard (None = keep)
            decimal_places: Number of decimal places (None = keep)
            unit: Unit string (None = keep)
            expected_digits: Expected digit count (None = keep)

        Returns:
            Updated MeterConfigData

        Raises:
            ConfigError: If camera or meter not found
        """
        camera = self.get_camera(camera_id)
        if not camera:
            raise ConfigError(f"Camera '{camera_id}' not found")

        existing = self.get_meter(camera_id, meter_id)
        if not existing:
            raise ConfigError(f"Meter '{meter_id}' not found in camera '{camera_id}'")

        # Build new perspective if points or size changed
        if points is not None or output_size is not None:
            new_points = points if points is not None else [list(p) for p in existing.perspective.points]
            if len(new_points) != 4:
                raise ConfigError("Meter must have exactly 4 perspective points")

            new_output_width = (
                output_size[0] if output_size is not None else existing.perspective.output_width
            )
            new_output_height = (
                output_size[1] if output_size is not None else existing.perspective.output_height
            )

            new_perspective = PerspectivePoints(
                points=tuple(tuple(p) for p in new_points),
                output_width=new_output_width,
                output_height=new_output_height,
            )
        else:
            new_perspective = existing.perspective

        updated_meter = MeterConfigData(
            id=existing.id,
            name=name if name is not None else existing.name,
            perspective=new_perspective,
            display_mode=display_mode if display_mode is not None else existing.display_mode,
            color_channel=color_channel if color_channel is not None else existing.color_channel,
            threshold=threshold if threshold is not None else existing.threshold,
            show_on_dashboard=show_on_dashboard if show_on_dashboard is not None else existing.show_on_dashboard,
            decimal_places=decimal_places if decimal_places is not None else existing.decimal_places,
            unit=unit if unit is not None else existing.unit,
            expected_digits=expected_digits if expected_digits is not None else existing.expected_digits,
        )

        # Rebuild camera meters
        new_meters = tuple(
            updated_meter if m.id == meter_id else m
            for m in camera.meters
        )

        updated_camera = CameraConfigData(
            id=camera.id,
            name=camera.name,
            url=camera.url,
            enabled=camera.enabled,
            meters=new_meters,
            indicators=camera.indicators,
        )

        new_cameras = tuple(
            updated_camera if c.id == camera_id else c
            for c in self.config.cameras
        )

        self._config = AppConfig(
            cameras=new_cameras,
            export=self.config.export,
            server=self.config.server,
        )

        return updated_meter

    def remove_meter(self, camera_id: str, meter_id: str) -> None:
        """Remove a meter from a camera.

        Args:
            camera_id: Camera ID
            meter_id: Meter ID to remove

        Raises:
            ConfigError: If camera or meter not found
        """
        camera = self.get_camera(camera_id)
        if not camera:
            raise ConfigError(f"Camera '{camera_id}' not found")

        if not self.get_meter(camera_id, meter_id):
            raise ConfigError(f"Meter '{meter_id}' not found in camera '{camera_id}'")

        new_meters = tuple(m for m in camera.meters if m.id != meter_id)

        updated_camera = CameraConfigData(
            id=camera.id,
            name=camera.name,
            url=camera.url,
            enabled=camera.enabled,
            meters=new_meters,
            indicators=camera.indicators,
        )

        new_cameras = tuple(
            updated_camera if c.id == camera_id else c
            for c in self.config.cameras
        )

        self._config = AppConfig(
            cameras=new_cameras,
            export=self.config.export,
            server=self.config.server,
        )

    # CRUD methods for indicators
    def get_indicator(self, camera_id: str, indicator_id: str) -> IndicatorConfigData | None:
        """Get an indicator by camera and indicator ID.

        Args:
            camera_id: Camera ID
            indicator_id: Indicator ID

        Returns:
            IndicatorConfigData or None if not found
        """
        camera = self.get_camera(camera_id)
        if not camera:
            return None

        for indicator in camera.indicators:
            if indicator.id == indicator_id:
                return indicator
        return None

    def add_indicator(
        self,
        camera_id: str,
        indicator_id: str,
        name: str,
        points: list[list[int]],
        output_size: list[int] | None = None,
        detection_mode: str = "brightness",
        threshold: int = 128,
        on_color: str = "red",
        show_on_dashboard: bool = True,
    ) -> IndicatorConfigData:
        """Add a new indicator to a camera.

        Args:
            camera_id: Camera ID to add indicator to
            indicator_id: Unique indicator ID within camera
            name: Indicator display name
            points: 4 perspective points [[x,y], ...]
            output_size: [width, height] or None for default
            detection_mode: Detection mode (brightness or color)
            threshold: Threshold value (0=auto)
            on_color: Color for color mode detection
            show_on_dashboard: Whether to show on dashboard

        Returns:
            The new IndicatorConfigData

        Raises:
            ConfigError: If camera not found or indicator ID exists
        """
        camera = self.get_camera(camera_id)
        if not camera:
            raise ConfigError(f"Camera '{camera_id}' not found")

        if self.get_indicator(camera_id, indicator_id):
            raise ConfigError(f"Indicator '{indicator_id}' already exists in camera '{camera_id}'")

        if len(points) != 4:
            raise ConfigError("Indicator must have exactly 4 perspective points")

        output_size = output_size or [100, 50]

        perspective = PerspectivePoints(
            points=tuple(tuple(p) for p in points),
            output_width=output_size[0],
            output_height=output_size[1],
        )

        new_indicator = IndicatorConfigData(
            id=indicator_id,
            name=name,
            perspective=perspective,
            detection_mode=detection_mode,
            threshold=threshold,
            on_color=on_color,
            show_on_dashboard=show_on_dashboard,
        )

        updated_camera = CameraConfigData(
            id=camera.id,
            name=camera.name,
            url=camera.url,
            enabled=camera.enabled,
            meters=camera.meters,
            indicators=camera.indicators + (new_indicator,),
        )

        new_cameras = tuple(
            updated_camera if c.id == camera_id else c
            for c in self.config.cameras
        )

        self._config = AppConfig(
            cameras=new_cameras,
            export=self.config.export,
            server=self.config.server,
        )

        return new_indicator

    def update_indicator(
        self,
        camera_id: str,
        indicator_id: str,
        name: str | None = None,
        points: list[list[int]] | None = None,
        output_size: list[int] | None = None,
        detection_mode: str | None = None,
        threshold: int | None = None,
        on_color: str | None = None,
        show_on_dashboard: bool | None = None,
    ) -> IndicatorConfigData:
        """Update an existing indicator.

        Args:
            camera_id: Camera ID
            indicator_id: Indicator ID to update
            name: New name (None = keep)
            points: New perspective points (None = keep)
            output_size: New output size (None = keep)
            detection_mode: New detection mode (None = keep)
            threshold: New threshold (None = keep)
            on_color: New on_color (None = keep)
            show_on_dashboard: Whether to show on dashboard (None = keep)

        Returns:
            Updated IndicatorConfigData

        Raises:
            ConfigError: If camera or indicator not found
        """
        camera = self.get_camera(camera_id)
        if not camera:
            raise ConfigError(f"Camera '{camera_id}' not found")

        existing = self.get_indicator(camera_id, indicator_id)
        if not existing:
            raise ConfigError(f"Indicator '{indicator_id}' not found in camera '{camera_id}'")

        # Build new perspective if points or size changed
        if points is not None or output_size is not None:
            new_points = points if points is not None else [list(p) for p in existing.perspective.points]
            if len(new_points) != 4:
                raise ConfigError("Indicator must have exactly 4 perspective points")

            new_output_width = (
                output_size[0] if output_size is not None else existing.perspective.output_width
            )
            new_output_height = (
                output_size[1] if output_size is not None else existing.perspective.output_height
            )

            new_perspective = PerspectivePoints(
                points=tuple(tuple(p) for p in new_points),
                output_width=new_output_width,
                output_height=new_output_height,
            )
        else:
            new_perspective = existing.perspective

        updated_indicator = IndicatorConfigData(
            id=existing.id,
            name=name if name is not None else existing.name,
            perspective=new_perspective,
            detection_mode=detection_mode if detection_mode is not None else existing.detection_mode,
            threshold=threshold if threshold is not None else existing.threshold,
            on_color=on_color if on_color is not None else existing.on_color,
            show_on_dashboard=show_on_dashboard if show_on_dashboard is not None else existing.show_on_dashboard,
        )

        # Rebuild camera indicators
        new_indicators = tuple(
            updated_indicator if i.id == indicator_id else i
            for i in camera.indicators
        )

        updated_camera = CameraConfigData(
            id=camera.id,
            name=camera.name,
            url=camera.url,
            enabled=camera.enabled,
            meters=camera.meters,
            indicators=new_indicators,
        )

        new_cameras = tuple(
            updated_camera if c.id == camera_id else c
            for c in self.config.cameras
        )

        self._config = AppConfig(
            cameras=new_cameras,
            export=self.config.export,
            server=self.config.server,
        )

        return updated_indicator

    def remove_indicator(self, camera_id: str, indicator_id: str) -> None:
        """Remove an indicator from a camera.

        Args:
            camera_id: Camera ID
            indicator_id: Indicator ID to remove

        Raises:
            ConfigError: If camera or indicator not found
        """
        camera = self.get_camera(camera_id)
        if not camera:
            raise ConfigError(f"Camera '{camera_id}' not found")

        if not self.get_indicator(camera_id, indicator_id):
            raise ConfigError(f"Indicator '{indicator_id}' not found in camera '{camera_id}'")

        new_indicators = tuple(i for i in camera.indicators if i.id != indicator_id)

        updated_camera = CameraConfigData(
            id=camera.id,
            name=camera.name,
            url=camera.url,
            enabled=camera.enabled,
            meters=camera.meters,
            indicators=new_indicators,
        )

        new_cameras = tuple(
            updated_camera if c.id == camera_id else c
            for c in self.config.cameras
        )

        self._config = AppConfig(
            cameras=new_cameras,
            export=self.config.export,
            server=self.config.server,
        )

    def migrate_from_json(self, json_path: Path | None = None) -> AppConfig:
        """Migrate configuration from legacy JSON format.

        Args:
            json_path: Path to legacy JSON config

        Returns:
            Migrated AppConfig
        """
        if json_path is None:
            json_path = self.legacy_config_path

        if not json_path.exists():
            raise ConfigError(f"Legacy config not found: {json_path}")

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Convert legacy format to new format
        meters_data = data.get("meters", [])
        meters = []

        for i, m in enumerate(meters_data):
            persp_data = m.get("perspective", {})
            points = [tuple(p) for p in persp_data.get("points", [])]

            if len(points) == 4:
                meters.append(MeterConfigData(
                    id=f"meter-{i + 1:02d}",
                    name=m.get("name", f"Meter {i + 1}"),
                    perspective=PerspectivePoints(
                        points=tuple(points),
                        output_width=persp_data.get("output_width", 400),
                        output_height=persp_data.get("output_height", 100),
                    ),
                    display_mode=m.get("display_mode", "light_on_dark"),
                    color_channel=m.get("color_channel", "red"),
                    threshold=m.get("threshold", 0),
                ))

        # Create default camera with migrated meters
        camera = CameraConfigData(
            id="cam-01",
            name="Default Camera",
            url="${RTSP_URL}",  # Use environment variable
            enabled=True,
            meters=tuple(meters),
        )

        config = AppConfig(
            cameras=(camera,) if meters else (),
            export=ExportConfig(),
            server=ServerConfig(),
        )

        # Backup original file
        backup_path = json_path.with_suffix(".json.bak")
        if not backup_path.exists():
            json_path.rename(backup_path)
            print(f"Backed up legacy config to: {backup_path}")

        # Save new config
        self.save(config)
        print(f"Migrated config saved to: {self.config_path}")

        return config


def get_default_config_path() -> Path:
    """Get the default configuration file path."""
    return YAMLConfig.DEFAULT_CONFIG_DIR / YAMLConfig.DEFAULT_CONFIG_FILE


def load_config(config_path: Path | None = None) -> AppConfig:
    """Load configuration from file.

    Args:
        config_path: Optional custom config file path

    Returns:
        Loaded AppConfig
    """
    return YAMLConfig(config_path).load()
