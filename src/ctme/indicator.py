"""Indicator/alarm light detection module."""

import cv2
import numpy as np


class IndicatorDetector:
    """Detects ON/OFF state of indicator lights."""

    # HSV color ranges for different colors
    COLOR_RANGES = {
        "red": [
            # Red wraps around in HSV, so we need two ranges
            ((0, 100, 100), (10, 255, 255)),
            ((160, 100, 100), (180, 255, 255)),
        ],
        "green": [
            ((35, 100, 100), (85, 255, 255)),
        ],
        "blue": [
            ((100, 100, 100), (130, 255, 255)),
        ],
        "yellow": [
            ((20, 100, 100), (35, 255, 255)),
        ],
        "orange": [
            ((10, 100, 100), (20, 255, 255)),
        ],
    }

    def __init__(
        self,
        detection_mode: str = "brightness",
        threshold: int = 128,
        on_color: str = "red",
    ):
        """Initialize indicator detector.

        Args:
            detection_mode: "brightness" or "color"
            threshold: Brightness threshold (0=auto Otsu, 1-255=manual)
            on_color: Color to detect in color mode (red, green, blue, yellow, orange)
        """
        self.detection_mode = detection_mode
        self.threshold = threshold
        self.on_color = on_color.lower()

    def detect(self, roi_image: np.ndarray) -> tuple[bool, float, np.ndarray]:
        """Detect indicator state from ROI image.

        Args:
            roi_image: BGR image of the indicator ROI (after perspective transform)

        Returns:
            Tuple of (state, brightness/ratio, debug_image)
            - state: True if ON, False if OFF
            - brightness: Average brightness (0-255) or color ratio (0-100)
            - debug_image: Visualization for debugging
        """
        if self.detection_mode == "color":
            return self._detect_by_color(roi_image)
        else:
            return self._detect_by_brightness(roi_image)

    def _detect_by_brightness(self, roi_image: np.ndarray) -> tuple[bool, float, np.ndarray]:
        """Detect indicator by average brightness.

        Args:
            roi_image: BGR image of the indicator ROI

        Returns:
            Tuple of (state, brightness, debug_image)
        """
        # Convert to grayscale
        gray = cv2.cvtColor(roi_image, cv2.COLOR_BGR2GRAY)

        # Calculate average brightness
        brightness = float(np.mean(gray))

        # Determine threshold
        if self.threshold == 0:
            # Auto threshold using Otsu
            thresh_value, _ = cv2.threshold(
                gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
            )
        else:
            thresh_value = self.threshold

        # Determine state
        state = brightness > thresh_value

        # Create debug image
        debug = self._create_debug_image(roi_image, state, brightness, thresh_value)

        return state, brightness, debug

    def _detect_by_color(self, roi_image: np.ndarray) -> tuple[bool, float, np.ndarray]:
        """Detect indicator by color presence.

        Args:
            roi_image: BGR image of the indicator ROI

        Returns:
            Tuple of (state, color_ratio, debug_image)
        """
        # Convert to HSV
        hsv = cv2.cvtColor(roi_image, cv2.COLOR_BGR2HSV)

        # Get color ranges
        color_ranges = self.COLOR_RANGES.get(self.on_color, self.COLOR_RANGES["red"])

        # Create mask for the target color
        mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
        for lower, upper in color_ranges:
            lower_bound = np.array(lower, dtype=np.uint8)
            upper_bound = np.array(upper, dtype=np.uint8)
            mask |= cv2.inRange(hsv, lower_bound, upper_bound)

        # Calculate color ratio (percentage of pixels matching the color)
        total_pixels = mask.shape[0] * mask.shape[1]
        color_pixels = np.count_nonzero(mask)
        color_ratio = (color_pixels / total_pixels) * 100 if total_pixels > 0 else 0

        # Determine threshold for color mode
        # Default: if more than 10% of pixels match the color, it's ON
        if self.threshold == 0:
            thresh_value = 10.0  # Default 10%
        else:
            # Map 1-255 to 1-100%
            thresh_value = (self.threshold / 255) * 100

        state = color_ratio > thresh_value

        # Create debug image with color mask overlay
        debug = self._create_color_debug_image(roi_image, mask, state, color_ratio, thresh_value)

        return state, color_ratio, debug

    def _create_debug_image(
        self,
        roi_image: np.ndarray,
        state: bool,
        brightness: float,
        threshold: float,
    ) -> np.ndarray:
        """Create debug visualization for brightness mode.

        Args:
            roi_image: Original ROI image
            state: Detected state
            brightness: Measured brightness
            threshold: Used threshold

        Returns:
            Debug image with visualization
        """
        # Resize for better visibility
        h, w = roi_image.shape[:2]
        scale = max(1, 100 // min(h, w))
        debug = cv2.resize(roi_image, (w * scale, h * scale), interpolation=cv2.INTER_NEAREST)

        # Add header with status
        header_height = 40
        header = np.zeros((header_height, debug.shape[1], 3), dtype=np.uint8)

        # Status indicator
        status_color = (0, 255, 0) if state else (128, 128, 128)
        status_text = "ON" if state else "OFF"

        cv2.putText(
            header,
            f"{status_text} | Brightness: {brightness:.1f} (th={threshold:.0f})",
            (5, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            status_color,
            1,
        )

        # Combine header and image
        debug = np.vstack([header, debug])

        # Add border based on state
        border_color = (0, 255, 0) if state else (128, 128, 128)
        debug = cv2.copyMakeBorder(debug, 2, 2, 2, 2, cv2.BORDER_CONSTANT, value=border_color)

        return debug

    def _create_color_debug_image(
        self,
        roi_image: np.ndarray,
        mask: np.ndarray,
        state: bool,
        color_ratio: float,
        threshold: float,
    ) -> np.ndarray:
        """Create debug visualization for color mode.

        Args:
            roi_image: Original ROI image
            mask: Color detection mask
            state: Detected state
            color_ratio: Percentage of matching pixels
            threshold: Used threshold

        Returns:
            Debug image with visualization
        """
        # Resize for better visibility
        h, w = roi_image.shape[:2]
        scale = max(1, 100 // min(h, w))
        debug_orig = cv2.resize(roi_image, (w * scale, h * scale), interpolation=cv2.INTER_NEAREST)
        debug_mask = cv2.resize(mask, (w * scale, h * scale), interpolation=cv2.INTER_NEAREST)

        # Convert mask to 3-channel for display
        mask_colored = cv2.cvtColor(debug_mask, cv2.COLOR_GRAY2BGR)

        # Combine original and mask side by side
        debug = np.hstack([debug_orig, mask_colored])

        # Add header with status
        header_height = 40
        header = np.zeros((header_height, debug.shape[1], 3), dtype=np.uint8)

        status_color = (0, 255, 0) if state else (128, 128, 128)
        status_text = "ON" if state else "OFF"

        cv2.putText(
            header,
            f"{status_text} | {self.on_color}: {color_ratio:.1f}% (th={threshold:.1f}%)",
            (5, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            status_color,
            1,
        )

        # Combine header and image
        debug = np.vstack([header, debug])

        # Add border based on state
        border_color = (0, 255, 0) if state else (128, 128, 128)
        debug = cv2.copyMakeBorder(debug, 2, 2, 2, 2, cv2.BORDER_CONSTANT, value=border_color)

        return debug
