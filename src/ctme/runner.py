"""MeterEye server runner."""

import logging
import signal
import sys
import threading
from datetime import datetime
from pathlib import Path

from ctme.camera_manager import CameraManager
from ctme.config_yaml import YAMLConfig, load_config
from ctme.export import ExporterManager, HTTPExporter
from ctme.models import AppConfig, CameraStatus, Reading

logger = logging.getLogger(__name__)

# Optional imports
try:
    from ctme.export.database import DatabaseExporter
    DATABASE_AVAILABLE = True
except ImportError:
    DATABASE_AVAILABLE = False

try:
    from ctme.export.mqtt import MQTTExporter
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

try:
    from ctme.api.server import create_app
    import uvicorn
    API_AVAILABLE = True
except ImportError:
    API_AVAILABLE = False


class MeterEyeServer:
    """MeterEye server for multi-camera meter monitoring."""

    def __init__(self, config_path: Path | None = None):
        """Initialize MeterEye server.

        Args:
            config_path: Optional custom config file path
        """
        self.config_path = config_path
        self.yaml_config = YAMLConfig(config_path)
        self.config: AppConfig | None = None
        self.camera_manager: CameraManager | None = None
        self.exporter_manager: ExporterManager | None = None
        self._api_thread: threading.Thread | None = None
        self._api_server = None
        self._stop_event = threading.Event()
        self._reading_count = 0
        self._start_time: datetime | None = None

    def _on_status_change(self, camera_id: str, status: CameraStatus) -> None:
        """Handle camera status changes.

        Args:
            camera_id: Camera ID
            status: New status
        """
        logger.info(f"[{camera_id}] Status: {status.value}")

    def _on_reading(self, reading: Reading) -> None:
        """Handle new readings.

        Args:
            reading: New reading
        """
        self._reading_count += 1

        # Log reading
        if reading.value is not None:
            logger.info(
                f"[{reading.camera_id}/{reading.meter_id}] "
                f"Value: {reading.value} ({reading.raw_text})"
            )
        else:
            logger.debug(
                f"[{reading.camera_id}/{reading.meter_id}] "
                f"No value (raw: {reading.raw_text})"
            )

        # Push to exporters
        if self.exporter_manager:
            self.exporter_manager.push(reading)

        # Record for API
        if self._api_server:
            self._api_server.record_reading(reading)

    def _setup_exporters(self) -> None:
        """Setup data exporters based on configuration."""
        if not self.config:
            return

        self.exporter_manager = ExporterManager()
        export_config = self.config.export

        # HTTP exporter
        if export_config.http.enabled:
            http_exporter = HTTPExporter(export_config.http)
            self.exporter_manager.add_exporter(http_exporter)
            logger.info(f"HTTP exporter enabled: {export_config.http.url}")

        # Database exporter
        if export_config.database.enabled and DATABASE_AVAILABLE:
            db_exporter = DatabaseExporter(export_config.database)
            self.exporter_manager.add_exporter(db_exporter)
            logger.info(f"Database exporter enabled: {export_config.database.type}")
        elif export_config.database.enabled:
            logger.warning("Database export enabled but sqlalchemy not installed")

        # MQTT exporter
        if export_config.mqtt.enabled and MQTT_AVAILABLE:
            mqtt_exporter = MQTTExporter(export_config.mqtt)
            self.exporter_manager.add_exporter(mqtt_exporter)
            logger.info(f"MQTT exporter enabled: {export_config.mqtt.broker}")
        elif export_config.mqtt.enabled:
            logger.warning("MQTT export enabled but paho-mqtt not installed")

        self.exporter_manager.start()

    def _start_api_server(self) -> None:
        """Start the API server in a background thread."""
        if not self.config or not API_AVAILABLE:
            return

        server_config = self.config.server
        if not server_config.enabled:
            logger.info("API server disabled in configuration")
            return

        try:
            app = create_app(self.camera_manager, self.yaml_config)
            self._api_server = app.state.api_server

            def run_api():
                uvicorn.run(
                    app,
                    host=server_config.host,
                    port=server_config.port,
                    log_level="warning",
                )

            self._api_thread = threading.Thread(
                target=run_api,
                name="APIServer",
                daemon=True,
            )
            self._api_thread.start()
            logger.info(f"API server started on {server_config.host}:{server_config.port}")

        except Exception as e:
            logger.error(f"Failed to start API server: {e}")

    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, shutting down...")
            self._stop_event.set()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    def run(self) -> int:
        """Run the MeterEye server.

        Returns:
            Exit code (0 for success)
        """
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        logger.info("MeterEye Server - ChingTech")
        logger.info("=" * 40)

        # Load configuration
        try:
            self.config = self.yaml_config.load()
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return 1

        if not self.config.cameras:
            logger.error("No cameras configured")
            logger.info(f"Please create config at: {self.yaml_config.config_path}")
            return 1

        logger.info(f"Loaded {len(self.config.cameras)} camera(s)")
        for cam in self.config.cameras:
            logger.info(f"  - {cam.id}: {cam.name} ({len(cam.meters)} meters)")

        # Setup signal handlers
        self._setup_signal_handlers()

        # Setup exporters
        self._setup_exporters()

        # Start camera manager
        self.camera_manager = CameraManager()
        self._start_time = datetime.now()

        try:
            self.camera_manager.start()

            # Add reading callback
            self.camera_manager.add_reading_callback(self._on_reading)

            # Add cameras
            for cam_config in self.config.cameras:
                self.camera_manager.add_camera(
                    cam_config,
                    on_status_change=self._on_status_change,
                )

            # Start API server
            self._start_api_server()

            logger.info("Service started. Press Ctrl+C to stop.")

            # Main loop
            while not self._stop_event.is_set():
                self._stop_event.wait(1.0)

                # Print periodic stats
                if self._start_time:
                    elapsed = (datetime.now() - self._start_time).total_seconds()
                    if elapsed > 0 and int(elapsed) % 60 == 0:
                        rate = self._reading_count / elapsed
                        logger.info(
                            f"Stats: {self._reading_count} readings, "
                            f"{rate:.1f}/sec avg"
                        )

        except KeyboardInterrupt:
            logger.info("Interrupted by user")

        finally:
            logger.info("Shutting down...")

            if self.camera_manager:
                self.camera_manager.stop()

            if self.exporter_manager:
                self.exporter_manager.stop()

            elapsed = 0.0
            if self._start_time:
                elapsed = (datetime.now() - self._start_time).total_seconds()

            logger.info(
                f"Total: {self._reading_count} readings in {elapsed:.1f}s"
            )
            logger.info("Goodbye!")

        return 0


def run_server(config_path: Path | None = None) -> int:
    """Run MeterEye server.

    Args:
        config_path: Optional custom config file path

    Returns:
        Exit code
    """
    server = MeterEyeServer(config_path)
    return server.run()
