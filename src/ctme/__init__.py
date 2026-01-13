"""MeterEye - Multi-camera meter monitoring with 7-segment display recognition.

By ChingTech (擎添工業)
"""

from ctme.recognition import SevenSegmentRecognizer
from ctme.camera_manager import CameraManager
from ctme.models import Reading, CameraStatus

__version__ = "1.0.0"
__author__ = "ChingTech"

__all__ = [
    "SevenSegmentRecognizer",
    "CameraManager",
    "Reading",
    "CameraStatus",
]
