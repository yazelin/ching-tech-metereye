"""Multi-camera manager with thread-per-camera architecture."""

import logging
import queue
import threading
import time
from datetime import datetime
from typing import Callable

import cv2
import numpy as np

from ctme.models import (
    CameraConfigData,
    CameraRuntimeStatus,
    CameraStatus,
    MeterConfigData,
    MeterStatus,
    PerspectivePoints,
    Reading,
)
from ctme.recognition import SevenSegmentRecognizer

logger = logging.getLogger(__name__)


def apply_perspective_transform(
    frame: np.ndarray,
    perspective: PerspectivePoints,
) -> np.ndarray | None:
    """Apply perspective transform to extract meter region.

    Args:
        frame: Input frame
        perspective: Perspective configuration

    Returns:
        Transformed image or None if invalid config
    """
    if not perspective.is_valid():
        return None

    src_pts = np.array(perspective.points, dtype=np.float32)
    dst_pts = np.array([
        [0, 0],
        [perspective.output_width - 1, 0],
        [perspective.output_width - 1, perspective.output_height - 1],
        [0, perspective.output_height - 1],
    ], dtype=np.float32)

    matrix = cv2.getPerspectiveTransform(src_pts, dst_pts)
    warped = cv2.warpPerspective(
        frame, matrix, (perspective.output_width, perspective.output_height)
    )

    return warped


class CameraWorker(threading.Thread):
    """Worker thread for a single camera."""

    RECONNECT_DELAYS = [3, 6, 12, 24, 48, 60]  # Exponential backoff (max 60s)
    STABLE_CONNECTION_TIME = 300  # 5 minutes to reset reconnect counter

    def __init__(
        self,
        config: CameraConfigData,
        reading_queue: "queue.Queue[Reading]",
        on_status_change: Callable[[str, CameraStatus], None] | None = None,
    ):
        """Initialize camera worker.

        Args:
            config: Camera configuration
            reading_queue: Queue to publish readings
            on_status_change: Callback for status changes
        """
        super().__init__(name=f"CameraWorker-{config.id}", daemon=True)

        self.config = config
        self.reading_queue = reading_queue
        self.on_status_change = on_status_change

        self._stop_event = threading.Event()
        self._status = CameraStatus.DISCONNECTED
        self._status_lock = threading.Lock()
        self._last_frame_time: datetime | None = None
        self._fps = 0.0
        self._error_message = ""
        self._reconnect_count = 0
        self._last_stable_time: datetime | None = None

        # Latest frame storage for streaming
        self._latest_frame: np.ndarray | None = None
        self._frame_lock = threading.Lock()

        # Processing interval control
        self._processing_interval = config.processing_interval_seconds
        self._last_process_time: float = 0.0  # Unix timestamp

        # Create recognizers for each meter
        self._recognizers: dict[str, SevenSegmentRecognizer] = {}
        self._meter_status: dict[str, MeterStatus] = {}
        self._meters = config.meters  # Mutable reference for hot reload

        for meter in config.meters:
            self._recognizers[meter.id] = SevenSegmentRecognizer(
                display_mode=meter.display_mode,
                color_channel=meter.color_channel,
                threshold=meter.threshold,
                expected_digits=meter.expected_digits,
            )
            self._meter_status[meter.id] = MeterStatus(
                meter_id=meter.id,
                name=meter.name,
            )

    @property
    def status(self) -> CameraStatus:
        """Get current camera status."""
        with self._status_lock:
            return self._status

    def _set_status(self, status: CameraStatus, error: str = "") -> None:
        """Set camera status and notify callback."""
        with self._status_lock:
            if self._status != status:
                self._status = status
                self._error_message = error
                logger.info(f"Camera {self.config.id} status: {status.value}")
                if self.on_status_change:
                    try:
                        self.on_status_change(self.config.id, status)
                    except Exception as e:
                        logger.error(f"Status callback error: {e}")

    def get_runtime_status(self) -> CameraRuntimeStatus:
        """Get current runtime status."""
        with self._status_lock:
            return CameraRuntimeStatus(
                camera_id=self.config.id,
                name=self.config.name,
                status=self._status,
                last_frame_time=self._last_frame_time,
                fps=self._fps,
                meters=list(self._meter_status.values()),
                error_message=self._error_message,
            )

    def get_latest_frame(self) -> np.ndarray | None:
        """Get the latest captured frame.

        Returns:
            Latest frame or None if not available
        """
        with self._frame_lock:
            if self._latest_frame is not None:
                return self._latest_frame.copy()
            return None

    def stop(self) -> None:
        """Request the worker to stop."""
        self._stop_event.set()

    def update_meters(self, meters: tuple[MeterConfigData, ...]) -> None:
        """Hot update meter configurations without stopping the worker.

        Args:
            meters: New meter configurations
        """
        with self._status_lock:
            # Rebuild recognizers
            old_recognizers = self._recognizers
            old_status = self._meter_status

            self._recognizers = {}
            self._meter_status = {}

            for meter in meters:
                # Reuse existing recognizer if config unchanged
                old_rec = old_recognizers.get(meter.id)
                if (old_rec and
                    old_rec.display_mode == meter.display_mode and
                    old_rec.color_channel == meter.color_channel and
                    old_rec.threshold == meter.threshold and
                    old_rec.expected_digits == meter.expected_digits):
                    self._recognizers[meter.id] = old_rec
                else:
                    self._recognizers[meter.id] = SevenSegmentRecognizer(
                        display_mode=meter.display_mode,
                        color_channel=meter.color_channel,
                        threshold=meter.threshold,
                        expected_digits=meter.expected_digits,
                    )

                # Preserve last reading if meter still exists
                old_meter_status = old_status.get(meter.id)
                if old_meter_status:
                    self._meter_status[meter.id] = MeterStatus(
                        meter_id=meter.id,
                        name=meter.name,
                        last_reading=old_meter_status.last_reading,
                    )
                else:
                    self._meter_status[meter.id] = MeterStatus(
                        meter_id=meter.id,
                        name=meter.name,
                    )

            # Update config with new meters
            # Note: CameraConfigData is frozen, so we store meters reference separately
            self._meters = meters

            logger.info(f"Camera {self.config.id} meters updated: {[m.id for m in meters]}")

    def update_processing_interval(self, interval_seconds: float) -> None:
        """Hot update processing interval without stopping the worker.

        Args:
            interval_seconds: New processing interval in seconds
        """
        with self._status_lock:
            self._processing_interval = max(0.1, interval_seconds)  # Minimum 0.1s
            logger.info(f"Camera {self.config.id} processing interval updated: {self._processing_interval}s")

    def _get_reconnect_delay(self) -> float:
        """Get the reconnection delay based on attempt count."""
        idx = min(self._reconnect_count, len(self.RECONNECT_DELAYS) - 1)
        return self.RECONNECT_DELAYS[idx]

    def _process_frame(self, frame: np.ndarray) -> None:
        """Process a frame and recognize all meters.

        Args:
            frame: Input frame from camera
        """
        timestamp = datetime.now()

        # Use _meters for hot reload support
        for meter in self._meters:
            if meter.id not in self._recognizers:
                continue

            # Apply perspective transform
            warped = apply_perspective_transform(frame, meter.perspective)
            if warped is None:
                continue

            # Recognize digits
            recognizer = self._recognizers[meter.id]
            result, _ = recognizer.recognize(warped)

            # Parse value
            value: float | None = None
            raw_text = result or ""

            if result:
                try:
                    value = float(result)
                except ValueError:
                    pass

            # Create reading
            reading = Reading(
                camera_id=self.config.id,
                meter_id=meter.id,
                value=value,
                raw_text=raw_text,
                timestamp=timestamp,
                confidence=1.0 if value is not None else 0.0,
            )

            # Update meter status
            self._meter_status[meter.id] = MeterStatus(
                meter_id=meter.id,
                name=meter.name,
                last_reading=reading,
            )

            # Publish to queue (non-blocking)
            try:
                self.reading_queue.put_nowait(reading)
            except queue.Full:
                logger.warning(f"Reading queue full, dropping reading from {meter.id}")

    def run(self) -> None:
        """Main worker loop."""
        logger.info(f"Starting camera worker: {self.config.id} ({self.config.name})")

        while not self._stop_event.is_set():
            cap: cv2.VideoCapture | None = None

            try:
                # Connect to stream
                self._set_status(CameraStatus.RECONNECTING if self._reconnect_count > 0 else CameraStatus.DISCONNECTED)

                cap = cv2.VideoCapture(self.config.url)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

                if not cap.isOpened():
                    raise ConnectionError(f"Failed to open stream: {self.config.url}")

                self._set_status(CameraStatus.CONNECTED)
                self._reconnect_count = 0
                self._last_stable_time = datetime.now()

                # Frame processing loop
                frame_times: list[float] = []
                consecutive_failures = 0
                max_failures = 30

                while not self._stop_event.is_set():
                    frame_start = time.time()

                    ret, frame = cap.read()

                    if not ret or frame is None:
                        consecutive_failures += 1
                        if consecutive_failures >= max_failures:
                            raise ConnectionError("Stream read failed")
                        continue

                    consecutive_failures = 0
                    self._last_frame_time = datetime.now()

                    # Check stable connection
                    if self._last_stable_time:
                        elapsed = (datetime.now() - self._last_stable_time).total_seconds()
                        if elapsed >= self.STABLE_CONNECTION_TIME:
                            self._reconnect_count = 0
                            self._last_stable_time = datetime.now()

                    # Store latest frame for streaming
                    with self._frame_lock:
                        self._latest_frame = frame.copy()

                    # Process frame (only if interval elapsed)
                    current_time = time.time()
                    if current_time - self._last_process_time >= self._processing_interval:
                        self._process_frame(frame)
                        self._last_process_time = current_time

                    # Calculate FPS
                    frame_times.append(time.time() - frame_start)
                    if len(frame_times) > 30:
                        frame_times.pop(0)
                    if frame_times:
                        avg_time = sum(frame_times) / len(frame_times)
                        self._fps = 1.0 / avg_time if avg_time > 0 else 0.0

            except Exception as e:
                error_msg = str(e)
                logger.error(f"Camera {self.config.id} error: {error_msg}")
                self._set_status(CameraStatus.DISCONNECTED, error_msg)
                self._reconnect_count += 1

            finally:
                if cap is not None:
                    cap.release()

            # Wait before reconnecting
            if not self._stop_event.is_set():
                delay = self._get_reconnect_delay()
                logger.info(f"Camera {self.config.id} reconnecting in {delay}s...")
                self._stop_event.wait(delay)

        logger.info(f"Camera worker stopped: {self.config.id}")


ReadingCallback = Callable[[Reading], None]


class CameraManager:
    """Manager for multiple camera workers."""

    def __init__(self, max_queue_size: int = 1000):
        """Initialize camera manager.

        Args:
            max_queue_size: Maximum size of reading queue
        """
        self._workers: dict[str, CameraWorker] = {}
        self._workers_lock = threading.Lock()
        self._reading_queue: queue.Queue[Reading] = queue.Queue(maxsize=max_queue_size)
        self._callbacks: list[ReadingCallback] = []
        self._callbacks_lock = threading.Lock()
        self._dispatcher_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def add_camera(
        self,
        config: CameraConfigData,
        on_status_change: Callable[[str, CameraStatus], None] | None = None,
    ) -> None:
        """Add and start a camera worker.

        Args:
            config: Camera configuration
            on_status_change: Optional status change callback
        """
        with self._workers_lock:
            if config.id in self._workers:
                logger.warning(f"Camera {config.id} already exists, skipping")
                return

            if not config.enabled:
                logger.info(f"Camera {config.id} is disabled, skipping")
                return

            worker = CameraWorker(
                config=config,
                reading_queue=self._reading_queue,
                on_status_change=on_status_change,
            )
            self._workers[config.id] = worker
            worker.start()
            logger.info(f"Added camera: {config.id}")

    def remove_camera(self, camera_id: str) -> None:
        """Stop and remove a camera worker.

        Args:
            camera_id: ID of camera to remove
        """
        with self._workers_lock:
            if camera_id not in self._workers:
                return

            worker = self._workers.pop(camera_id)
            worker.stop()
            worker.join(timeout=5.0)
            logger.info(f"Removed camera: {camera_id}")

    def update_camera_meters(
        self,
        camera_id: str,
        meters: tuple[MeterConfigData, ...],
    ) -> bool:
        """Hot update meters for a camera without restarting.

        Args:
            camera_id: ID of camera to update
            meters: New meter configurations

        Returns:
            True if updated, False if camera not found
        """
        with self._workers_lock:
            worker = self._workers.get(camera_id)
            if not worker:
                logger.warning(f"Cannot update meters: camera {camera_id} not found")
                return False

            worker.update_meters(meters)
            return True

    def update_camera_processing_interval(
        self,
        camera_id: str,
        interval_seconds: float,
    ) -> bool:
        """Hot update processing interval for a camera without restarting.

        Args:
            camera_id: ID of camera to update
            interval_seconds: New processing interval in seconds

        Returns:
            True if updated, False if camera not found
        """
        with self._workers_lock:
            worker = self._workers.get(camera_id)
            if not worker:
                logger.warning(f"Cannot update interval: camera {camera_id} not found")
                return False

            worker.update_processing_interval(interval_seconds)
            return True

    def get_camera_status(self, camera_id: str) -> CameraRuntimeStatus | None:
        """Get runtime status of a camera.

        Args:
            camera_id: ID of camera

        Returns:
            Runtime status or None if not found
        """
        with self._workers_lock:
            worker = self._workers.get(camera_id)
            if worker:
                return worker.get_runtime_status()
            return None

    def get_all_camera_status(self) -> list[CameraRuntimeStatus]:
        """Get runtime status of all cameras.

        Returns:
            List of camera runtime statuses
        """
        with self._workers_lock:
            return [w.get_runtime_status() for w in self._workers.values()]

    def get_latest_frame(self, camera_id: str) -> np.ndarray | None:
        """Get the latest frame from a camera.

        Args:
            camera_id: ID of camera

        Returns:
            Latest frame or None if not available
        """
        with self._workers_lock:
            worker = self._workers.get(camera_id)
            if worker:
                return worker.get_latest_frame()
            return None

    def get_camera_ids(self) -> list[str]:
        """Get list of all camera IDs.

        Returns:
            List of camera IDs
        """
        with self._workers_lock:
            return list(self._workers.keys())

    def add_reading_callback(self, callback: ReadingCallback) -> None:
        """Add a callback for new readings.

        Args:
            callback: Function to call with each new reading
        """
        with self._callbacks_lock:
            self._callbacks.append(callback)

    def remove_reading_callback(self, callback: ReadingCallback) -> None:
        """Remove a reading callback.

        Args:
            callback: Callback to remove
        """
        with self._callbacks_lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

    def _dispatch_readings(self) -> None:
        """Dispatcher thread that distributes readings to callbacks."""
        while not self._stop_event.is_set():
            try:
                reading = self._reading_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            with self._callbacks_lock:
                callbacks = list(self._callbacks)

            for callback in callbacks:
                try:
                    callback(reading)
                except Exception as e:
                    logger.error(f"Reading callback error: {e}")

    def start(self) -> None:
        """Start the reading dispatcher."""
        if self._dispatcher_thread is not None:
            return

        self._stop_event.clear()
        self._dispatcher_thread = threading.Thread(
            target=self._dispatch_readings,
            name="ReadingDispatcher",
            daemon=True,
        )
        self._dispatcher_thread.start()
        logger.info("Camera manager started")

    def stop(self) -> None:
        """Stop all camera workers and the dispatcher."""
        # Stop dispatcher
        self._stop_event.set()
        if self._dispatcher_thread:
            self._dispatcher_thread.join(timeout=2.0)
            self._dispatcher_thread = None

        # Stop all workers
        with self._workers_lock:
            for worker in self._workers.values():
                worker.stop()

            for worker in self._workers.values():
                worker.join(timeout=5.0)

            self._workers.clear()

        logger.info("Camera manager stopped")

    def __enter__(self) -> "CameraManager":
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, *args) -> None:
        """Context manager exit."""
        self.stop()
