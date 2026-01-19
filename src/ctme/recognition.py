"""7-segment display recognition module."""

import cv2
import numpy as np

# Each digit maps to which segments are ON (a,b,c,d,e,f,g)
SEGMENT_PATTERNS = {
    (1, 1, 1, 1, 1, 1, 0): "0",
    (0, 1, 1, 0, 0, 0, 0): "1",
    (1, 1, 0, 1, 1, 0, 1): "2",
    (1, 1, 1, 1, 0, 0, 1): "3",
    (0, 1, 1, 0, 0, 1, 1): "4",
    (1, 0, 1, 1, 0, 1, 1): "5",
    (1, 0, 1, 1, 1, 1, 1): "6",
    (1, 1, 1, 0, 0, 0, 0): "7",
    (1, 1, 1, 1, 1, 1, 1): "8",
    (1, 1, 1, 1, 0, 1, 1): "9",
}


class SevenSegmentRecognizer:
    """Recognizes 7-segment display digits."""

    def __init__(
        self,
        display_mode: str = "light_on_dark",
        color_channel: str = "green",  # Default to green for Mindman
        threshold: int = 0,
        segment_threshold: float = 0.15,
        expected_digits: int = 0,  # 0 = auto-detect, >0 = fixed digit count
    ):
        self.display_mode = display_mode
        self.color_channel = color_channel
        self.threshold = threshold
        self.segment_threshold = segment_threshold
        self.expected_digits = expected_digits

    def preprocess(self, roi_image: np.ndarray) -> np.ndarray:
        """Preprocess ROI image."""
        if self.color_channel == "gray":
            gray = cv2.cvtColor(roi_image, cv2.COLOR_BGR2GRAY)
        elif self.color_channel == "red":
            gray = roi_image[:, :, 2]
        elif self.color_channel == "green":
            gray = roi_image[:, :, 1]
        elif self.color_channel == "blue":
            gray = roi_image[:, :, 0]
        else:
            gray = cv2.cvtColor(roi_image, cv2.COLOR_BGR2GRAY)

        # Light blur
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)

        # Threshold
        if self.threshold == 0:
            _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        else:
            _, binary = cv2.threshold(blurred, self.threshold, 255, cv2.THRESH_BINARY)

        if self.display_mode == "dark_on_light":
            binary = cv2.bitwise_not(binary)

        return binary

    def find_digit_bounds(self, binary: np.ndarray) -> list[tuple[int, int, bool]]:
        """Find digit x-bounds using vertical projection."""
        h, w = binary.shape

        # Vertical projection (sum per column)
        v_proj = np.sum(binary, axis=0) / 255

        # Find continuous regions
        threshold = h * 0.03  # Very low threshold
        regions = []
        in_region = False
        start = 0

        for x in range(w):
            if v_proj[x] > threshold:
                if not in_region:
                    start = x
                    in_region = True
            else:
                if in_region:
                    width = x - start
                    if width >= 2:
                        regions.append((start, x, width))
                    in_region = False

        if in_region:
            width = w - start
            if width >= 2:
                regions.append((start, w, width))

        # Now determine if each region is a dot or digit
        # A dot is narrow AND short (content only in bottom portion)
        # A "1" is narrow but TALL (content spans full height)
        result = []
        for start_x, end_x, width in regions:
            col_slice = binary[:, start_x:end_x]

            # Find vertical extent of content
            rows_with_content = np.any(col_slice > 0, axis=1)
            if not np.any(rows_with_content):
                continue

            y_indices = np.where(rows_with_content)[0]
            content_top = y_indices[0]
            content_bottom = y_indices[-1]
            content_height = content_bottom - content_top + 1

            # Dot criteria: narrow AND short (less than 40% of full height)
            # AND located in bottom half of image
            is_narrow = width < h * 0.15
            is_short = content_height < h * 0.4
            is_at_bottom = content_top > h * 0.5

            is_dot = is_narrow and is_short and is_at_bottom
            result.append((start_x, end_x, is_dot))

        return result

    def find_digit_bounds_fixed(self, binary: np.ndarray, num_digits: int) -> list[tuple[int, int, bool]]:
        """Find digit x-bounds using fixed equal-width segmentation.

        This method divides the FULL ROI width evenly by expected digit count.
        The ROI is assumed to be user-defined to exactly contain the digits,
        so we use its full width rather than detecting content bounds.

        This approach is immune to decimal point interference because:
        - We divide the full ROI, not content-detected regions
        - Decimal points are simply part of adjacent digit's slot margin
        - Equal division ensures consistent digit positioning

        Args:
            binary: Binary image of the ROI
            num_digits: Expected number of digits

        Returns:
            List of (start_x, end_x, is_decimal_point=False) tuples
        """
        h, w = binary.shape

        if num_digits <= 0:
            return []

        # Use FULL ROI width for division (not content-detected bounds)
        # This ensures consistent digit slots regardless of content variations
        digit_width = w / num_digits

        # Extract digits at fixed intervals across full ROI
        result = []
        for i in range(num_digits):
            x1 = int(i * digit_width)
            x2 = int((i + 1) * digit_width)

            # Ensure within bounds
            x1 = max(0, x1)
            x2 = min(w, x2)

            if x2 > x1:
                # Always treat as digit, never as decimal point
                result.append((x1, x2, False))

        return result

    def analyze_digit(self, digit_binary: np.ndarray) -> tuple[str | None, list[int], np.ndarray]:
        """Analyze a single digit image using the actual slot dimensions.

        This method works directly with the digit slot from fixed division,
        without assuming a specific aspect ratio. Segment positions are
        calculated proportionally based on the actual slot size.

        Note: We always use the full slot width for analysis. Narrow digits
        like "1" are naturally handled by the segment pattern matching since
        only segments b and c will have content above threshold.

        Returns:
            (digit, segments, visualization)
            - digit: "0"-"9" if recognized, "" if blank/empty, None if recognition failed
        """
        h, w = digit_binary.shape[:2]

        # Create color visualization
        vis = cv2.cvtColor(digit_binary, cv2.COLOR_GRAY2BGR)

        if h < 5 or w < 2:
            return "", [], vis  # Too small = treat as blank

        # Check if there's any content at all
        content_ratio = np.sum(digit_binary > 0) / digit_binary.size
        if content_ratio < 0.01:  # Less than 1% lit = blank/empty digit
            cv2.putText(vis, "_", (3, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (128, 128, 128), 2)
            return "", [], vis  # Empty string = blank position (not recognition failure)

        # Use full slot dimensions for analysis
        # This ensures consistent segment detection regardless of digit width
        ch, cw = h, w

        if ch < 5 or cw < 2:
            return None, [], vis

        # Define segment sample regions (relative to analysis area)
        # Standard 7-segment layout:
        #    aaaa
        #   f    b
        #   f    b
        #    gggg
        #   e    c
        #   e    c
        #    dddd
        # Regions should NOT overlap - use smaller, focused detection areas
        seg_defs = {
            "a": (0.20, 0.02, 0.80, 0.12),   # top horizontal
            "b": (0.70, 0.15, 0.98, 0.42),   # top-right vertical
            "c": (0.70, 0.58, 0.98, 0.85),   # bottom-right vertical
            "d": (0.20, 0.88, 0.80, 0.98),   # bottom horizontal
            "e": (0.02, 0.58, 0.30, 0.85),   # bottom-left vertical
            "f": (0.02, 0.15, 0.30, 0.42),   # top-left vertical
            "g": (0.20, 0.44, 0.80, 0.56),   # middle horizontal
        }

        colors = [
            (255, 100, 100),  # a - light blue
            (100, 255, 100),  # b - light green
            (100, 100, 255),  # c - light red
            (255, 255, 100),  # d - cyan
            (255, 100, 255),  # e - magenta
            (100, 255, 255),  # f - yellow
            (200, 200, 255),  # g - pink
        ]

        segments = []
        for i, seg in enumerate(["a", "b", "c", "d", "e", "f", "g"]):
            px1, py1, px2, py2 = seg_defs[seg]
            # Calculate segment region using full slot dimensions
            sx1 = int(cw * px1)
            sy1 = int(ch * py1)
            sx2 = int(cw * px2)
            sy2 = int(ch * py2)

            # Clamp to image bounds
            sx1, sx2 = max(0, sx1), min(w, sx2)
            sy1, sy2 = max(0, sy1), min(h, sy2)

            if sx2 <= sx1 or sy2 <= sy1:
                segments.append(0)
                continue

            # Sample from original digit_binary
            region = digit_binary[sy1:sy2, sx1:sx2]
            ratio = np.mean(region) / 255.0 if region.size > 0 else 0
            is_on = 1 if ratio > self.segment_threshold else 0
            segments.append(is_on)

            # Draw on visualization
            cv2.rectangle(vis,
                         (sx1, sy1),
                         (sx2, sy2),
                         colors[i], 2 if is_on else 1)

        # Match pattern
        pattern = tuple(segments)
        digit = SEGMENT_PATTERNS.get(pattern)

        # Fuzzy match if needed
        if digit is None:
            best, best_diff = None, 99
            for pat, d in SEGMENT_PATTERNS.items():
                diff = sum(abs(a - b) for a, b in zip(segments, pat))
                if diff < best_diff:
                    best_diff = diff
                    best = d
            if best_diff <= 1:  # Stricter matching
                digit = best

        # Add labels
        label = digit if digit else "?"
        cv2.putText(vis, label, (3, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                   (0, 255, 0) if digit else (0, 0, 255), 2)

        seg_str = "".join(map(str, segments))
        cv2.putText(vis, seg_str, (3, h - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (180, 180, 180), 1)

        return digit, segments, vis

    def recognize(self, roi_image: np.ndarray) -> tuple[str | None, np.ndarray]:
        """Recognize digits from ROI image.

        When expected_digits > 0, uses fixed position extraction which is more
        reliable for displays where decimal points merge with adjacent digits.

        Returns:
            (recognized_text, debug_image)
            recognized_text is None if recognition failed or digit count doesn't match expected.
        """
        if roi_image is None or roi_image.size == 0:
            return None, np.zeros((80, 200, 3), dtype=np.uint8)

        binary = self.preprocess(roi_image)
        h, w = binary.shape

        # Find digit regions - use fixed positions if expected_digits is set
        if self.expected_digits > 0:
            regions = self.find_digit_bounds_fixed(binary, self.expected_digits)
        else:
            regions = self.find_digit_bounds(binary)

        if not regions:
            debug = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
            cv2.putText(debug, "No digits", (5, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            return None, debug

        # Process each region
        result = ""
        visuals = []
        digit_count = 0  # Count actual digits (not decimal points)

        for x1, x2, is_dot in regions:
            col_img = binary[:, x1:x2]

            if is_dot:
                # Small region = decimal point
                result += "."
                dot_vis = np.zeros((h, max(x2-x1, 15), 3), dtype=np.uint8)
                cv2.putText(dot_vis, ".", (2, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
                visuals.append(dot_vis)
            else:
                digit, segs, vis = self.analyze_digit(col_img)
                # digit is: "0"-"9" = recognized, "" = blank/empty, None = recognition failed
                if digit is None:
                    result += "?"  # Recognition failed (has content but unrecognized)
                else:
                    result += digit  # Could be "0"-"9" or "" (blank)
                digit_count += 1
                visuals.append(vis)

        # Validate digit count if expected_digits is set
        recognition_ok = "?" not in result
        if self.expected_digits > 0 and digit_count != self.expected_digits:
            recognition_ok = False

        # Build debug image
        if visuals:
            max_h = max(v.shape[0] for v in visuals)
            parts = []
            for v in visuals:
                if v.shape[0] < max_h:
                    pad = np.zeros((max_h - v.shape[0], v.shape[1], 3), dtype=np.uint8)
                    v = np.vstack([v, pad])
                parts.append(v)
                parts.append(np.full((max_h, 4, 3), 30, dtype=np.uint8))  # separator

            debug = np.hstack(parts[:-1]) if parts else np.zeros((h, w, 3), dtype=np.uint8)
        else:
            debug = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)

        # Header with result and mode info
        header = np.zeros((35, debug.shape[1], 3), dtype=np.uint8)
        status_color = (0, 255, 0) if recognition_ok else (0, 0, 255)
        status_text = f"Result: {result}"
        if self.expected_digits > 0:
            status_text += f" [{digit_count}/{self.expected_digits}]"
        cv2.putText(header, status_text, (5, 25),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, status_color, 2)
        debug = np.vstack([header, debug])

        return result if recognition_ok else None, debug
