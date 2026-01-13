"""HTTP exporter for sending readings to a REST API."""

import json
import logging
import time
import urllib.request
import urllib.error
from typing import Any

from ctme.export.base import BaseExporter
from ctme.models import HTTPExportConfig, Reading

logger = logging.getLogger(__name__)


class HTTPExporter(BaseExporter):
    """Export readings via HTTP POST requests."""

    # Exponential backoff delays (seconds)
    RETRY_DELAYS = [1, 2, 4, 8, 16, 30]
    MAX_RETRIES = 5

    def __init__(self, config: HTTPExportConfig):
        """Initialize HTTP exporter.

        Args:
            config: HTTP export configuration
        """
        super().__init__("HTTP")
        self.config = config
        self._enabled = config.enabled
        self._consecutive_failures = 0

    def _make_request(self, data: dict[str, Any]) -> bool:
        """Make HTTP POST request with retry logic.

        Args:
            data: JSON data to send

        Returns:
            True if request succeeded
        """
        if not self.config.url:
            logger.warning("HTTP exporter: No URL configured")
            return False

        json_data = json.dumps(data).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "MeterEye/1.0",
        }
        headers.update(self.config.headers)

        for attempt in range(self.MAX_RETRIES):
            try:
                request = urllib.request.Request(
                    self.config.url,
                    data=json_data,
                    headers=headers,
                    method="POST",
                )

                with urllib.request.urlopen(
                    request,
                    timeout=self.config.timeout_seconds,
                ) as response:
                    if response.status < 300:
                        self._consecutive_failures = 0
                        return True
                    else:
                        logger.warning(
                            f"HTTP export failed: {response.status} {response.reason}"
                        )

            except urllib.error.HTTPError as e:
                logger.warning(f"HTTP error: {e.code} {e.reason}")
            except urllib.error.URLError as e:
                logger.warning(f"URL error: {e.reason}")
            except TimeoutError:
                logger.warning("HTTP request timeout")
            except Exception as e:
                logger.error(f"HTTP request error: {e}")

            # Retry with backoff
            if attempt < self.MAX_RETRIES - 1:
                delay = self.RETRY_DELAYS[min(attempt, len(self.RETRY_DELAYS) - 1)]
                logger.debug(f"Retrying in {delay}s (attempt {attempt + 2})")
                time.sleep(delay)

        self._consecutive_failures += 1
        if self._consecutive_failures >= 10:
            logger.error(
                f"HTTP exporter: {self._consecutive_failures} consecutive failures"
            )

        return False

    def export(self, reading: Reading) -> bool:
        """Export a single reading.

        Args:
            reading: Reading to export

        Returns:
            True if export succeeded
        """
        if not self._enabled:
            return True

        data = {
            "readings": [reading.to_dict()],
            "count": 1,
        }

        return self._make_request(data)

    def export_batch(self, readings: list[Reading]) -> bool:
        """Export a batch of readings.

        Args:
            readings: List of readings to export

        Returns:
            True if export succeeded
        """
        if not self._enabled:
            return True

        if not readings:
            return True

        data = {
            "readings": [r.to_dict() for r in readings],
            "count": len(readings),
        }

        return self._make_request(data)

    def start(self) -> None:
        """Start the HTTP exporter."""
        super().start()
        if self.config.url:
            logger.info(f"HTTP exporter target: {self.config.url}")
        else:
            logger.warning("HTTP exporter: No URL configured")

    def stop(self) -> None:
        """Stop the HTTP exporter."""
        super().stop()
