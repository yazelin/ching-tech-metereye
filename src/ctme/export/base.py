"""Base exporter interface and manager."""

import logging
import queue
import threading
from abc import ABC, abstractmethod
from typing import Union

from ctme.models import IndicatorReading, Reading

logger = logging.getLogger(__name__)

# Union type for all reading types
AnyReading = Union[Reading, IndicatorReading]


class BaseExporter(ABC):
    """Abstract base class for data exporters."""

    def __init__(self, name: str):
        """Initialize exporter.

        Args:
            name: Exporter name for logging
        """
        self.name = name
        self._enabled = True

    @property
    def enabled(self) -> bool:
        """Check if exporter is enabled."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        """Set exporter enabled state."""
        self._enabled = value

    @abstractmethod
    def export(self, reading: Reading) -> bool:
        """Export a single reading.

        Args:
            reading: Reading to export

        Returns:
            True if export succeeded, False otherwise
        """
        pass

    @abstractmethod
    def export_batch(self, readings: list[Reading]) -> bool:
        """Export a batch of readings.

        Args:
            readings: List of readings to export

        Returns:
            True if export succeeded, False otherwise
        """
        pass

    def export_indicator(self, reading: IndicatorReading) -> bool:
        """Export a single indicator reading.

        Default implementation does nothing. Subclasses can override.

        Args:
            reading: Indicator reading to export

        Returns:
            True if export succeeded, False otherwise
        """
        return True

    def export_indicator_batch(self, readings: list[IndicatorReading]) -> bool:
        """Export a batch of indicator readings.

        Default implementation calls export_indicator for each.

        Args:
            readings: List of indicator readings to export

        Returns:
            True if all exports succeeded, False otherwise
        """
        success = True
        for reading in readings:
            if not self.export_indicator(reading):
                success = False
        return success

    def start(self) -> None:
        """Start the exporter (optional initialization)."""
        logger.info(f"Exporter started: {self.name}")

    def stop(self) -> None:
        """Stop the exporter (cleanup)."""
        logger.info(f"Exporter stopped: {self.name}")


class ExporterManager:
    """Manager for multiple exporters with async dispatch."""

    def __init__(self, max_queue_size: int = 10000):
        """Initialize exporter manager.

        Args:
            max_queue_size: Maximum size of export queue
        """
        self._exporters: list[BaseExporter] = []
        self._queue: queue.Queue[Reading] = queue.Queue(maxsize=max_queue_size)
        self._indicator_queue: queue.Queue[IndicatorReading] = queue.Queue(maxsize=max_queue_size)
        self._worker_thread: threading.Thread | None = None
        self._indicator_worker_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._batch_size = 10
        self._batch_timeout = 1.0  # seconds

    def add_exporter(self, exporter: BaseExporter) -> None:
        """Add an exporter.

        Args:
            exporter: Exporter to add
        """
        self._exporters.append(exporter)
        logger.info(f"Added exporter: {exporter.name}")

    def remove_exporter(self, exporter: BaseExporter) -> None:
        """Remove an exporter.

        Args:
            exporter: Exporter to remove
        """
        if exporter in self._exporters:
            self._exporters.remove(exporter)
            logger.info(f"Removed exporter: {exporter.name}")

    def push(self, reading: Reading) -> bool:
        """Push a reading to the export queue.

        Args:
            reading: Reading to export

        Returns:
            True if queued successfully
        """
        try:
            self._queue.put_nowait(reading)
            return True
        except queue.Full:
            logger.warning("Export queue full, dropping reading")
            return False

    def push_indicator(self, reading: IndicatorReading) -> bool:
        """Push an indicator reading to the export queue.

        Args:
            reading: Indicator reading to export

        Returns:
            True if queued successfully
        """
        try:
            self._indicator_queue.put_nowait(reading)
            return True
        except queue.Full:
            logger.warning("Indicator export queue full, dropping reading")
            return False

    def _worker(self) -> None:
        """Background worker that processes the export queue."""
        batch: list[Reading] = []

        while not self._stop_event.is_set():
            try:
                # Collect batch
                while len(batch) < self._batch_size:
                    try:
                        reading = self._queue.get(timeout=self._batch_timeout)
                        batch.append(reading)
                    except queue.Empty:
                        break

                if not batch:
                    continue

                # Export to all exporters
                for exporter in self._exporters:
                    if not exporter.enabled:
                        continue

                    try:
                        if len(batch) == 1:
                            exporter.export(batch[0])
                        else:
                            exporter.export_batch(batch)
                    except Exception as e:
                        logger.error(f"Export error ({exporter.name}): {e}")

                batch.clear()

            except Exception as e:
                logger.error(f"Export worker error: {e}")
                batch.clear()

        # Flush remaining on shutdown
        if batch:
            for exporter in self._exporters:
                if exporter.enabled:
                    try:
                        exporter.export_batch(batch)
                    except Exception as e:
                        logger.error(f"Final export error ({exporter.name}): {e}")

    def _indicator_worker(self) -> None:
        """Background worker that processes the indicator export queue."""
        batch: list[IndicatorReading] = []

        while not self._stop_event.is_set():
            try:
                # Collect batch
                while len(batch) < self._batch_size:
                    try:
                        reading = self._indicator_queue.get(timeout=self._batch_timeout)
                        batch.append(reading)
                    except queue.Empty:
                        break

                if not batch:
                    continue

                # Export to all exporters
                for exporter in self._exporters:
                    if not exporter.enabled:
                        continue

                    try:
                        if len(batch) == 1:
                            exporter.export_indicator(batch[0])
                        else:
                            exporter.export_indicator_batch(batch)
                    except Exception as e:
                        logger.error(f"Indicator export error ({exporter.name}): {e}")

                batch.clear()

            except Exception as e:
                logger.error(f"Indicator export worker error: {e}")
                batch.clear()

        # Flush remaining on shutdown
        if batch:
            for exporter in self._exporters:
                if exporter.enabled:
                    try:
                        exporter.export_indicator_batch(batch)
                    except Exception as e:
                        logger.error(f"Final indicator export error ({exporter.name}): {e}")

    def start(self) -> None:
        """Start all exporters and the worker threads."""
        for exporter in self._exporters:
            try:
                exporter.start()
            except Exception as e:
                logger.error(f"Failed to start exporter {exporter.name}: {e}")

        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._worker,
            name="ExportWorker",
            daemon=True,
        )
        self._worker_thread.start()

        self._indicator_worker_thread = threading.Thread(
            target=self._indicator_worker,
            name="IndicatorExportWorker",
            daemon=True,
        )
        self._indicator_worker_thread.start()

        logger.info("Exporter manager started")

    def stop(self) -> None:
        """Stop all exporters and the worker threads."""
        self._stop_event.set()

        if self._worker_thread:
            self._worker_thread.join(timeout=5.0)
            self._worker_thread = None

        if self._indicator_worker_thread:
            self._indicator_worker_thread.join(timeout=5.0)
            self._indicator_worker_thread = None

        for exporter in self._exporters:
            try:
                exporter.stop()
            except Exception as e:
                logger.error(f"Failed to stop exporter {exporter.name}: {e}")

        logger.info("Exporter manager stopped")

    def __enter__(self) -> "ExporterManager":
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, *args) -> None:
        """Context manager exit."""
        self.stop()
