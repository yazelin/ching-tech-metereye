#!/usr/bin/env python3
"""Test script to analyze reference photos and develop recognition algorithm."""

import cv2
import numpy as np
from pathlib import Path


def extract_digits_region(img: np.ndarray, color: str) -> np.ndarray | None:
    """Extract the main digit display region based on color."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    if color == "red":
        # Red has hue around 0 or 180
        mask1 = cv2.inRange(hsv, (0, 80, 80), (15, 255, 255))
        mask2 = cv2.inRange(hsv, (165, 80, 80), (180, 255, 255))
        mask = mask1 | mask2
    elif color == "green":
        # Green has hue around 35-85
        mask = cv2.inRange(hsv, (35, 80, 80), (90, 255, 255))
    else:
        return None

    # Find contours
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return None

    # Filter contours by size (remove noise and small text)
    min_area = 100
    significant_contours = [c for c in contours if cv2.contourArea(c) > min_area]

    if not significant_contours:
        return None

    # Find bounding box that encompasses ALL significant contours
    all_points = np.vstack(significant_contours)
    x, y, w, h = cv2.boundingRect(all_points)

    # Filter to get only the main display digits (largest height region)
    # Group contours by vertical position to separate main display from small text
    # First, find the tallest contour to establish reference height
    max_height = 0
    for c in significant_contours:
        _, _, _, ch = cv2.boundingRect(c)
        max_height = max(max_height, ch)

    # Only keep contours that are at least 50% of max height (main digits)
    main_contours = []
    for c in significant_contours:
        cx, cy, cw, ch = cv2.boundingRect(c)
        if ch > max_height * 0.5:
            main_contours.append(c)

    if main_contours:
        all_points = np.vstack(main_contours)
        x, y, w, h = cv2.boundingRect(all_points)

    # Expand slightly to capture full digits
    padding = 10
    x = max(0, x - padding)
    y = max(0, y - padding)
    w = min(img.shape[1] - x, w + 2 * padding)
    h = min(img.shape[0] - y, h + 2 * padding)

    return img[y:y+h, x:x+w]


def preprocess_for_ocr(roi: np.ndarray, color: str) -> np.ndarray:
    """Preprocess ROI for digit recognition."""
    # Extract the specific color channel
    if color == "red":
        gray = roi[:, :, 2]  # Red channel
    elif color == "green":
        gray = roi[:, :, 1]  # Green channel
    else:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    # Light blur to reduce noise
    gray = cv2.GaussianBlur(gray, (3, 3), 0)

    # Threshold - digits are bright on dark background
    if color == "red":
        # For red displays, use higher threshold to cut through LED bloom/glow
        # Otsu often includes too much glow
        otsu_thresh, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        # Use threshold 30% higher than Otsu to cut through glow
        adjusted_thresh = min(255, int(otsu_thresh * 1.3))
        _, binary = cv2.threshold(gray, adjusted_thresh, 255, cv2.THRESH_BINARY)
    else:
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # For red displays, apply morphological opening to break remaining connections
    if color == "red":
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        binary = cv2.erode(binary, kernel, iterations=1)
        binary = cv2.dilate(binary, kernel, iterations=1)

    return binary


def find_decimal_points(binary: np.ndarray, debug: bool = False) -> list[int]:
    """Find decimal point x-positions using contour analysis.

    Returns list of x-center positions of decimal points.
    """
    h, w = binary.shape

    # Look for small circular contours in the bottom portion (last 40%)
    bottom_portion = binary[int(h * 0.6):, :]
    bh, bw = bottom_portion.shape
    contours, _ = cv2.findContours(bottom_portion, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    decimal_positions = []

    for cnt in contours:
        area = cv2.contourArea(cnt)
        x, y, cw, ch = cv2.boundingRect(cnt)

        # Decimal point criteria:
        # 1. Small area
        # 2. Roughly square aspect ratio (more strict)
        # 3. Small dimensions
        # 4. Not touching edges (standalone)
        max_dim = max(cw, ch)
        min_dim = min(cw, ch)

        is_small = max_dim < h * 0.15 and area < (h * 0.12) ** 2
        is_squarish = min_dim > max_dim * 0.5 if max_dim > 0 else False  # More strict

        # Check if contour is isolated (not touching top or bottom edges)
        not_at_top = y > 2
        not_at_bottom = y + ch < bh - 2

        if is_small and is_squarish and area > 20 and not_at_top and not_at_bottom:
            center_x = x + cw // 2
            decimal_positions.append(center_x)
            if debug:
                print(f"  Decimal candidate: x={center_x}, area={area}, size={cw}x{ch}")

    return sorted(decimal_positions)


def find_digit_columns(binary: np.ndarray, debug: bool = False) -> list[tuple[int, int, bool]]:
    """Find digit columns using vertical projection.

    Returns list of (start_x, end_x, is_decimal_point) tuples.
    """
    h, w = binary.shape

    # First, find decimal point positions using contour analysis
    decimal_xs = find_decimal_points(binary, debug)
    if debug and decimal_xs:
        print(f"  Decimal positions found: {decimal_xs}")

    # Vertical projection
    v_proj = np.sum(binary, axis=0) / 255

    # Find regions with content - use LOW threshold to catch decimal points
    threshold = h * 0.02  # Very low threshold
    raw_regions = []
    in_region = False
    start = 0

    for x in range(w):
        if v_proj[x] > threshold:
            if not in_region:
                start = x
                in_region = True
        else:
            if in_region:
                if x - start > 2:  # Minimum width of 2
                    raw_regions.append((start, x))
                in_region = False

    if in_region and w - start > 2:
        raw_regions.append((start, w))

    if debug:
        print(f"  Raw regions (threshold={threshold:.1f}): {raw_regions}")

    # Calculate expected digit width
    expected_digit_width = h // 2

    # Analyze each region to determine if it's a digit or decimal point
    result = []
    for start_x, end_x in raw_regions:
        region_width = end_x - start_x
        col_slice = binary[:, start_x:end_x]

        # Find vertical extent of content
        rows_with_content = np.any(col_slice > 0, axis=1)
        if not np.any(rows_with_content):
            continue

        y_indices = np.where(rows_with_content)[0]
        content_top = y_indices[0]
        content_bottom = y_indices[-1]
        content_height = content_bottom - content_top + 1

        # Check if this region contains a decimal point (from contour analysis)
        contains_decimal = any(start_x <= dx <= end_x for dx in decimal_xs)

        # If region is wide and contains a decimal, we need to split it
        if contains_decimal and region_width > expected_digit_width * 0.6:
            # Find the decimal x position within this region
            decimal_in_region = [dx for dx in decimal_xs if start_x <= dx <= end_x]
            if debug:
                print(f"  Region {start_x}-{end_x} (w={region_width}) contains decimal at {decimal_in_region}")
            if decimal_in_region:
                dx = decimal_in_region[0]
                # Split at the decimal position
                # The decimal is at dx, digits are before and after

                # Simple approach: split before and after decimal position
                # Find where the decimal starts and ends in the region
                rel_dx = dx - start_x  # Decimal x relative to region start

                # Split: look for gaps in projection around decimal
                region_proj = v_proj[start_x:end_x]

                # Find the lowest point near the decimal position
                search_margin = int(expected_digit_width * 0.25)
                search_start = max(0, rel_dx - search_margin)
                search_end = min(region_width, rel_dx + search_margin)

                if debug:
                    print(f"    Decimal relative pos: {rel_dx}, search range: {search_start}-{search_end}")

                if search_start < search_end:
                    # Find split points - before and after decimal
                    # Look for minimum before decimal
                    if rel_dx > 10:
                        before_search = region_proj[max(0, rel_dx-search_margin):rel_dx]
                        if len(before_search) > 0:
                            before_min_rel = np.argmin(before_search)
                            before_min = max(0, rel_dx - search_margin) + before_min_rel
                        else:
                            before_min = rel_dx - 5
                    else:
                        before_min = rel_dx

                    # Look for minimum after decimal
                    if rel_dx < region_width - 10:
                        after_search = region_proj[rel_dx:min(region_width, rel_dx+search_margin)]
                        if len(after_search) > 0:
                            after_min_rel = np.argmin(after_search)
                            after_min = rel_dx + after_min_rel
                        else:
                            after_min = rel_dx + 5
                    else:
                        after_min = rel_dx

                    if debug:
                        print(f"    Split points: before={before_min}, after={after_min}")

                    # Determine how to split based on where decimal is
                    # Case 1: Decimal is near the start of region (digit after decimal is in this region)
                    # Case 2: Decimal is near the end of region (digit before decimal is in this region)
                    # Case 3: Decimal is in the middle (both digits in this region)

                    if before_min > 10 and after_min < region_width - 10:
                        # Case 3: Decimal in middle - split into 3 parts
                        result.append((start_x, start_x + before_min, False))
                        result.append((start_x + before_min, start_x + after_min, True))
                        result.append((start_x + after_min, end_x, False))
                        if debug:
                            print(f"  Split (middle): [{start_x}-{start_x+before_min}] [.] [{start_x+after_min}-{end_x}]")
                        continue
                    elif before_min > 10:
                        # Case 2: Decimal at end - digit before, then decimal
                        result.append((start_x, start_x + before_min, False))
                        result.append((start_x + before_min, end_x, True))
                        if debug:
                            print(f"  Split (end): [{start_x}-{start_x+before_min}] [.]")
                        continue
                    elif after_min < region_width - 10:
                        # Case 1: Decimal at start - decimal, then digit after
                        result.append((start_x, start_x + after_min, True))
                        result.append((start_x + after_min, end_x, False))
                        if debug:
                            print(f"  Split (start): [.] [{start_x+after_min}-{end_x}]")
                        continue

        # Standard decimal point criteria (for standalone decimal regions)
        is_narrow = region_width < expected_digit_width * 0.35
        is_short = content_height < h * 0.4
        is_at_bottom = content_top > h * 0.5

        is_decimal = is_narrow and is_short and is_at_bottom

        if debug:
            print(f"  Region {start_x}-{end_x}: w={region_width}, content_h={content_height}/{h}, top={content_top}, narrow={is_narrow}, short={is_short}, bottom={is_at_bottom} -> {'DOT' if is_decimal else 'DIGIT'}")

        result.append((start_x, end_x, is_decimal))

    return result


# Standard 7-segment patterns
# Segments: a (top), b (top-right), c (bottom-right), d (bottom), e (bottom-left), f (top-left), g (middle)
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


def analyze_digit(digit_img: np.ndarray, debug: bool = False) -> tuple[str | None, list[int]]:
    """Analyze a single digit image and return the recognized digit."""
    h, w = digit_img.shape

    if h < 10 or w < 5:
        return None, []

    # Find actual content bounds (trim empty space)
    rows_with_content = np.any(digit_img > 0, axis=1)
    cols_with_content = np.any(digit_img > 0, axis=0)

    if not np.any(rows_with_content) or not np.any(cols_with_content):
        return None, []

    row_indices = np.where(rows_with_content)[0]
    col_indices = np.where(cols_with_content)[0]

    y_top, y_bottom = row_indices[0], row_indices[-1]
    x_left, x_right = col_indices[0], col_indices[-1]

    # Crop to content
    content = digit_img[y_top:y_bottom+1, x_left:x_right+1]
    ch, cw = content.shape

    if ch < 5 or cw < 2:
        return None, []

    # For very narrow regions (like "1"), check aspect ratio
    # Standard 7-segment aspect ratio is about 2:1 (height:width)
    expected_width = ch // 2

    if cw < expected_width * 0.35:
        # Very narrow = likely "1"
        return "1", [0, 1, 1, 0, 0, 0, 0]

    # Define segment regions based on standard 7-segment layout
    # Using proportions relative to CONTENT bounds
    #     aaaa
    #    f    b
    #    f    b
    #     gggg
    #    e    c
    #    e    c
    #     dddd

    # Segment definitions: (x_start%, y_start%, x_end%, y_end%)
    segments_def = {
        'a': (0.15, 0.0, 0.85, 0.15),   # top
        'b': (0.65, 0.08, 1.0, 0.45),   # top-right
        'c': (0.65, 0.55, 1.0, 0.92),   # bottom-right
        'd': (0.15, 0.85, 0.85, 1.0),   # bottom
        'e': (0.0, 0.55, 0.35, 0.92),   # bottom-left
        'f': (0.0, 0.08, 0.35, 0.45),   # top-left
        'g': (0.15, 0.42, 0.85, 0.58),  # middle
    }

    segments = []
    segment_names = ['a', 'b', 'c', 'd', 'e', 'f', 'g']

    for seg_name in segment_names:
        x1_pct, y1_pct, x2_pct, y2_pct = segments_def[seg_name]

        x1 = int(cw * x1_pct)
        y1 = int(ch * y1_pct)
        x2 = int(cw * x2_pct)
        y2 = int(ch * y2_pct)

        # Ensure valid region
        x1, x2 = max(0, x1), min(cw, x2)
        y1, y2 = max(0, y1), min(ch, y2)

        if x2 <= x1 or y2 <= y1:
            segments.append(0)
            continue

        region = content[y1:y2, x1:x2]
        if region.size == 0:
            segments.append(0)
            continue

        # Calculate fill ratio
        fill_ratio = cv2.countNonZero(region) / region.size

        # Threshold for segment being "on"
        # Use higher threshold (0.35) to avoid false positives from partial coverage
        is_on = 1 if fill_ratio > 0.35 else 0
        segments.append(is_on)

        if debug:
            print(f"  Segment {seg_name}: region ({x1},{y1})-({x2},{y2}), fill={fill_ratio:.2f}, on={is_on}")

    # Match pattern
    pattern = tuple(segments)
    if pattern in SEGMENT_PATTERNS:
        return SEGMENT_PATTERNS[pattern], segments

    # Fuzzy match
    best_match = None
    best_diff = 99
    for pat, digit in SEGMENT_PATTERNS.items():
        diff = sum(abs(a - b) for a, b in zip(segments, pat))
        if diff < best_diff:
            best_diff = diff
            best_match = digit

    if best_diff <= 1:
        return best_match, segments

    return None, segments


def recognize_display(roi: np.ndarray, color: str, debug: bool = False) -> str:
    """Recognize digits from a display ROI."""
    binary = preprocess_for_ocr(roi, color)
    h, w = binary.shape

    if debug:
        cv2.imshow(f"Binary ({color})", binary)

    # Find digit columns (now returns is_decimal flag)
    columns = find_digit_columns(binary, debug=debug)

    if debug:
        col_info = [(f"{x1}-{x2}{'.' if d else ''}" ) for x1, x2, d in columns]
        print(f"Found {len(columns)} columns: {col_info}")

    result = ""

    for i, (x1, x2, is_decimal) in enumerate(columns):
        col_width = x2 - x1
        digit_img = binary[:, x1:x2]

        if is_decimal:
            result += "."
            if debug:
                print(f"Column {i}: decimal point (w={col_width})")
            continue

        # Recognize digit
        digit, segments = analyze_digit(digit_img, debug=debug)

        if debug:
            print(f"Column {i}: width={col_width}, digit={digit}, segments={segments}")

        if digit is not None:
            result += digit
        else:
            result += "?"

    return result


def test_reference_photos(interactive: bool = False):
    """Test recognition on reference photos."""
    ref_dir = Path("/home/ct/SDD/tapocam/參考照片")
    output_dir = Path("/home/ct/SDD/tapocam/test_output")
    output_dir.mkdir(exist_ok=True)

    results = []

    for photo_path in sorted(ref_dir.glob("*.png")):
        # Parse expected values from filename
        # Format: red_XX.X_green_Y.YY.png
        name = photo_path.stem
        parts = name.split("_")
        expected_red = parts[1]
        expected_green = parts[3]

        print(f"\n{'='*60}")
        print(f"Testing: {photo_path.name}")
        print(f"Expected: Red={expected_red}, Green={expected_green}")

        # Load image
        img = cv2.imread(str(photo_path))
        if img is None:
            print(f"  ERROR: Could not load image")
            continue

        # Test both colors
        for color, expected in [("red", expected_red), ("green", expected_green)]:
            print(f"\n  Processing {color} display...")

            # Extract digit region
            roi = extract_digits_region(img, color)
            if roi is None:
                print(f"    ERROR: Could not extract {color} region")
                continue

            # Save ROI for debugging
            roi_path = output_dir / f"{name}_{color}_roi.png"
            cv2.imwrite(str(roi_path), roi)

            # Save binary for debugging
            binary = preprocess_for_ocr(roi, color)
            binary_path = output_dir / f"{name}_{color}_binary.png"
            cv2.imwrite(str(binary_path), binary)

            # Recognize
            result = recognize_display(roi, color, debug=True)

            correct = result == expected
            status = "✓" if correct else "✗"
            print(f"    Result: {result} (expected: {expected}) {status}")

            results.append({
                'file': photo_path.name,
                'color': color,
                'expected': expected,
                'result': result,
                'correct': correct
            })

        if interactive:
            cv2.waitKey(0)

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")

    total = len(results)
    correct = sum(1 for r in results if r['correct'])

    for r in results:
        status = "✓" if r['correct'] else "✗"
        print(f"  {r['file']} [{r['color']}]: {r['result']} (expected: {r['expected']}) {status}")

    print(f"\nAccuracy: {correct}/{total} ({100*correct/total:.1f}%)")
    print(f"Debug images saved to: {output_dir}")

    if interactive:
        cv2.destroyAllWindows()


if __name__ == "__main__":
    test_reference_photos()
