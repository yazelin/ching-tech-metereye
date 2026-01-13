"""MQTT exporter for publishing readings to a broker."""

import json
import logging
import threading
from typing import Any

try:
    import paho.mqtt.client as mqtt

    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

from ctme.export.base import BaseExporter
from ctme.models import MQTTExportConfig, Reading

logger = logging.getLogger(__name__)


class MQTTExporter(BaseExporter):
    """Export readings via MQTT publish."""

    def __init__(self, config: MQTTExportConfig):
        """Initialize MQTT exporter.

        Args:
            config: MQTT export configuration
        """
        super().__init__("MQTT")
        self.config = config
        self._enabled = config.enabled
        self._client: Any = None
        self._connected = False
        self._connect_lock = threading.Lock()

        if not MQTT_AVAILABLE:
            logger.warning(
                "paho-mqtt not installed. Install with: pip install paho-mqtt"
            )
            self._enabled = False

    def _on_connect(self, client, userdata, flags, rc, properties=None) -> None:
        """Handle MQTT connection callback."""
        if rc == 0:
            self._connected = True
            logger.info(f"MQTT connected to {self.config.broker}:{self.config.port}")
        else:
            self._connected = False
            logger.error(f"MQTT connection failed: rc={rc}")

    def _on_disconnect(self, client, userdata, rc, properties=None) -> None:
        """Handle MQTT disconnection callback."""
        self._connected = False
        if rc != 0:
            logger.warning(f"MQTT disconnected unexpectedly: rc={rc}")

    def start(self) -> None:
        """Start MQTT client and connect to broker."""
        super().start()

        if not MQTT_AVAILABLE or not self._enabled:
            return

        try:
            self._client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"ctme-{id(self)}",
            )

            self._client.on_connect = self._on_connect
            self._client.on_disconnect = self._on_disconnect

            # Set credentials if provided
            if self.config.username:
                self._client.username_pw_set(
                    self.config.username,
                    self.config.password or None,
                )

            # Connect (non-blocking)
            self._client.connect_async(self.config.broker, self.config.port)
            self._client.loop_start()

            logger.info(f"MQTT connecting to {self.config.broker}:{self.config.port}")

        except Exception as e:
            logger.error(f"MQTT setup failed: {e}")
            self._enabled = False

    def stop(self) -> None:
        """Stop MQTT client."""
        super().stop()

        if self._client:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception as e:
                logger.error(f"MQTT disconnect error: {e}")
            finally:
                self._client = None
                self._connected = False

    def _get_topic(self, reading: Reading) -> str:
        """Get MQTT topic for a reading.

        Supports placeholders: {camera_id}, {meter_id}

        Args:
            reading: Reading to get topic for

        Returns:
            MQTT topic string
        """
        topic = self.config.topic
        topic = topic.replace("{camera_id}", reading.camera_id)
        topic = topic.replace("{meter_id}", reading.meter_id)
        return topic

    def _publish(self, topic: str, payload: dict) -> bool:
        """Publish message to MQTT broker.

        Args:
            topic: MQTT topic
            payload: JSON payload

        Returns:
            True if publish succeeded
        """
        if not self._client or not self._connected:
            return False

        try:
            message = json.dumps(payload)
            result = self._client.publish(
                topic,
                message,
                qos=self.config.qos,
            )

            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                return True
            else:
                logger.warning(f"MQTT publish failed: rc={result.rc}")
                return False

        except Exception as e:
            logger.error(f"MQTT publish error: {e}")
            return False

    def export(self, reading: Reading) -> bool:
        """Export a single reading via MQTT.

        Args:
            reading: Reading to export

        Returns:
            True if export succeeded
        """
        if not self._enabled:
            return True

        topic = self._get_topic(reading)
        payload = reading.to_dict()

        return self._publish(topic, payload)

    def export_batch(self, readings: list[Reading]) -> bool:
        """Export a batch of readings via MQTT.

        Each reading is published to its own topic.

        Args:
            readings: List of readings to export

        Returns:
            True if all exports succeeded
        """
        if not self._enabled:
            return True

        if not readings:
            return True

        success = True
        for reading in readings:
            if not self.export(reading):
                success = False

        return success
